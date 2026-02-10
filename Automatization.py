import os
import time
import hashlib
import feedparser
import asyncio
import ssl
import concurrent.futures
import requests
import socket
from bs4 import BeautifulSoup
from dotenv import load_dotenv
from telegram import Bot
from datetime import datetime

# Load environment variables
load_dotenv()
TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
CHANNEL_ID = os.getenv("TELEGRAM_CHANNEL_ID")
bot = Bot(token=TOKEN)

# Fix SSL certificate issues
if hasattr(ssl, '_create_unverified_context'):
    ssl._create_default_https_context = ssl._create_unverified_context

# Persistent post memory
POST_LOG_FILE = "sent_posts.txt"
sent_posts = set()

if os.path.exists(POST_LOG_FILE):
    with open(POST_LOG_FILE, "r") as f:
        for line in f:
            sent_posts.add(line.strip())

# Working and verified RSS feeds only
SOURCES = {
    "AI News": [
        "https://techcrunch.com/category/artificial-intelligence/feed/",
        "https://venturebeat.com/category/ai/feed/",
        "https://www.artificialintelligence-news.com/feed/",
        "https://spectrum.ieee.org/rss/fulltext",
    ],
    "AI Tools & Development": [
        "https://blog.tensorflow.org/feeds/posts/default",
        "https://www.kdnuggets.com/feed",
        "https://machinelearningmastery.com/feed/",
        "https://huggingface.co/blog/feed.xml",
        "https://pytorch.org/blog/feed.xml",
        "https://blog.paperspace.com/rss/",
        "https://blog.roboflow.com/rss/",
        "https://wandb.ai/site/rss.xml",
        "https://blog.streamlit.io/rss/",
        "https://blog.keras.io/rss.xml"
    ],
    "AI Research": [
        "https://deepmind.google/blog/rss.xml",
        "https://www.microsoft.com/en-us/research/feed/",
        "https://blog.research.google/feeds/posts/default",
        "https://blogs.nvidia.com/blog/category/deep-learning/feed/",
        "https://distill.pub/rss.xml",
        "https://bair.berkeley.edu/blog/feed.xml",
        "https://ai.stanford.edu/blog/rss.xml"
    ],
    "Data Science & ML": [
        "https://www.datasciencecentral.com/feed/",
        "https://blog.dominodatalab.com/rss/",
        "https://medium.com/feed/@towards.data.science",
        "https://blog.dataiku.com/rss.xml",
        "https://www.datacamp.com/blog/rss.xml",
        "https://blog.mlflow.org/rss.xml"
    ],
    "AI Business & Industry": [
        "https://www.mckinsey.com/business-functions/mckinsey-analytics/our-insights/rss",
        "https://www.accenture.com/_acnmedia/rss/accenture-artificial-intelligence-rss.xml",
        "https://www2.deloitte.com/us/en/insights/rss.xml",
        "https://www.pwc.com/us/en/tech-effect/rss.xml"
    ],
    "Open Source AI": [
        "https://github.com/blog/category/engineering.atom",
        "https://opensource.com/feed",
        "https://blog.apache.org/feed.xml",
        "https://blog.python.org/feeds/posts/default"
    ]
}


def clean_html(raw_html):
    """Clean HTML content and extract readable text"""
    if not raw_html:
        return ""
    soup = BeautifulSoup(raw_html, "html.parser")
    # Remove script and style elements
    for script in soup(["script", "style"]):
        script.decompose()
    text = soup.get_text()
    # Clean up whitespace
    lines = (line.strip() for line in text.splitlines())
    chunks = (phrase.strip() for line in lines for phrase in line.split("  "))
    return ' '.join(chunk for chunk in chunks if chunk)


def hash_post(title, link):
    """Generate unique hash for each post"""
    return hashlib.sha256(f"{title}{link}".encode()).hexdigest()


def fetch_feed(url, category):
    """Fetch and parse RSS feed with better error handling and retry logic"""
    max_retries = 2

    for attempt in range(max_retries):
        try:
            print(f"Fetching {category}: {url} (attempt {attempt + 1}/{max_retries})")

            # Set socket timeout to prevent hanging
            old_timeout = socket.getdefaulttimeout()
            socket.setdefaulttimeout(30)

            try:
                # Custom headers to avoid blocking
                headers = {
                    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
                    'Accept': 'application/rss+xml, application/xml, text/xml, application/atom+xml, */*',
                    'Accept-Language': 'en-US,en;q=0.9',
                    'Accept-Encoding': 'gzip, deflate',
                    'Cache-Control': 'no-cache',
                    'Connection': 'keep-alive',
                    'Sec-Fetch-Dest': 'document',
                    'Sec-Fetch-Mode': 'navigate',
                    'Sec-Fetch-Site': 'none'
                }

                # Parse the feed with custom headers
                feed = feedparser.parse(url, request_headers=headers)

            finally:
                # Restore original timeout
                socket.setdefaulttimeout(old_timeout)

            # Check for feed parsing errors
            if hasattr(feed, 'bozo') and feed.bozo and feed.bozo_exception:
                print(f"[!] Feed parsing warning for {url}: {feed.bozo_exception}")

            if not feed.entries:
                status = getattr(feed, 'status', 'Unknown')
                print(f"[!] No entries for {url} (Status: {status})")

                # If it's a server error, try again
                if attempt < max_retries - 1 and status in [500, 502, 503, 504, 520, 521, 522, 523, 524]:
                    time.sleep(5)  # Wait 5 seconds before retry
                    continue

                return []

            print(f"[+] Found {len(feed.entries)} entries from {url}")

            entries = []
            for entry in feed.entries[:5]:  # Limit to 5 most recent entries
                try:
                    title = entry.get("title", "No Title").strip()
                    link = entry.get("link", "")

                    # Get summary from multiple possible fields
                    summary = ""
                    if entry.get("summary"):
                        summary = entry.summary
                    elif entry.get("description"):
                        summary = entry.description
                    elif entry.get("content"):
                        if isinstance(entry.content, list) and len(entry.content) > 0:
                            summary = entry.content[0].get("value", "")
                        else:
                            summary = str(entry.content)

                    if not summary and hasattr(entry, 'summary_detail'):
                        summary = entry.summary_detail.get('value', '')

                    summary = clean_html(summary)

                    # Skip if no meaningful content
                    if not title or not link:
                        continue

                    # Allow shorter summaries but provide a default
                    if len(summary) < 30:
                        summary = "Click to read the full article for more details."

                    uid = hash_post(title, link)

                    if uid in sent_posts:
                        continue

                    # Get publication date if available
                    pub_date = ""
                    if hasattr(entry, 'published'):
                        try:
                            pub_date = f"\n<b>📅 Published:</b> {entry.published}"
                        except:
                            pass

                    # Format message with better structure
                    message = (
                        f"🧠 <b>[{category}]</b>\n\n"
                        f"<b>📰 {title}</b>\n\n"
                        f"<b>📝 Summary:</b> {summary[:500]}{'...' if len(summary) > 500 else ''}\n\n"
                        f"<b>🔗 Read More:</b> <a href=\"{link}\">Full Article</a>{pub_date}\n\n"
                        f"<code>━━━━━━━━━━━━━━━━━━━━━━━</code>"
                    )

                    entries.append((uid, title, message))

                except Exception as e:
                    print(f"Error processing entry from {url}: {e}")
                    continue

            return entries

        except Exception as e:
            print(f"Error fetching {url} (attempt {attempt + 1}): {e}")
            if attempt < max_retries - 1:
                time.sleep(5)  # Wait before retry
                continue
            return []

    return []


def fetch_all(sources):
    """Fetch all feeds concurrently"""
    all_entries = []
    tasks = [(url, category) for category, urls in sources.items() for url in urls]

    print(f"Starting to fetch {len(tasks)} RSS feeds...")

    with concurrent.futures.ThreadPoolExecutor(max_workers=5) as executor:  # Reduced workers to be more respectful
        futures = [executor.submit(fetch_feed, url, category) for url, category in tasks]

        for future in concurrent.futures.as_completed(futures, timeout=300):  # 5 minute timeout
            try:
                result = future.result()
                if result:
                    all_entries.extend(result)
            except Exception as e:
                print(f"Future failed: {e}")

    print(f"Total entries collected: {len(all_entries)}")
    return all_entries


async def post_scheduled(posts, interval_minutes=5):
    """Post messages to Telegram with scheduling"""
    if not posts:
        print("No posts to send.")
        return

    print(f"Starting to post {len(posts)} messages with {interval_minutes} minute intervals...")

    for i, (uid, title, message) in enumerate(posts):
        try:
            await bot.send_message(
                chat_id=CHANNEL_ID,
                text=message,
                parse_mode="HTML",
                disable_web_page_preview=False
            )

            print(f"[{datetime.now().strftime('%H:%M:%S')}] ({i + 1}/{len(posts)}) Posted: {title[:50]}...")

            # Save to sent posts
            sent_posts.add(uid)
            with open(POST_LOG_FILE, "a", encoding='utf-8') as f:
                f.write(uid + "\n")

            # Wait before next post (except for the last one)
            if i < len(posts) - 1:
                await asyncio.sleep(interval_minutes * 60)

        except Exception as e:
            print(f"Error posting message: {e}")
            await asyncio.sleep(30)  # Wait 30 seconds before continuing


def cleanup_old_posts():
    """Clean up old post IDs to prevent file from growing too large"""
    if os.path.exists(POST_LOG_FILE):
        try:
            with open(POST_LOG_FILE, "r", encoding='utf-8') as f:
                lines = f.readlines()

            # Keep only last 10000 entries
            if len(lines) > 10000:
                with open(POST_LOG_FILE, "w", encoding='utf-8') as f:
                    f.writelines(lines[-10000:])
                print("Cleaned up old post IDs")
        except Exception as e:
            print(f"Error cleaning up post log: {e}")


if __name__ == "__main__":
    async def main():
        print(f"Starting AI RSS Bot at {datetime.now()}")

        while True:
            try:
                print(f"\n--- New fetch cycle started at {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} ---")

                # Clean up old posts periodically
                cleanup_old_posts()

                # Fetch all posts
                posts = fetch_all(SOURCES)

                if posts:
                    print(f"Found {len(posts)} new posts to send")
                    await post_scheduled(posts, interval_minutes=0)
                    print("Finished posting batch")
                else:
                    print("No new posts found in this cycle")

                # Wait 3 hours before next cycle
                print(f"Waiting 3 hours until next fetch cycle...")
                await asyncio.sleep(3 * 60 * 60)

            except KeyboardInterrupt:
                print("Bot stopped by user")
                break
            except Exception as e:
                print(f"Unexpected error in main loop: {e}")
                print("Waiting 10 minutes before retry...")
                await asyncio.sleep(10 * 60)


    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nBot stopped gracefully")