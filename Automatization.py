import os
import time
import hashlib
import feedparser
import asyncio
import ssl
import concurrent.futures
import socket
from bs4 import BeautifulSoup
from dotenv import load_dotenv
from telegram import Bot
from datetime import datetime, timedelta

# Load environment variables
load_dotenv()
TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
CHANNEL_ID = os.getenv("TELEGRAM_CHANNEL_ID")

# Validate environment variables
if not TOKEN or not CHANNEL_ID:
    raise ValueError("TELEGRAM_BOT_TOKEN and TELEGRAM_CHANNEL_ID must be set in .env file")

bot = Bot(token=TOKEN)

# Fix SSL certificate issues
if hasattr(ssl, '_create_unverified_context'):
    ssl._create_default_https_context = ssl._create_unverified_context

# Add Flask for health check (to prevent Render from sleeping)
try:
    from flask import Flask
    app = Flask(__name__)
    
    @app.route('/')
    def home():
        return "Bot is running!", 200
    
    # Run Flask in a separate thread
    import threading
    def run_flask():
        app.run(host='0.0.0.0', port=int(os.environ.get('PORT', 5000)))
    
    flask_thread = threading.Thread(target=run_flask, daemon=True)
    flask_thread.start()
except ImportError:
    pass

# Persistent post memory
POST_LOG_FILE = "sent_posts.txt"
MAX_MEMORY_SIZE = 10000

def load_sent_posts():
    """Load sent posts with size limit"""
    sent = set()
    if os.path.exists(POST_LOG_FILE):
        with open(POST_LOG_FILE, "r") as f:
            lines = f.readlines()
            for line in lines[-MAX_MEMORY_SIZE:]:
                sent.add(line.strip())
    return sent

sent_posts = load_sent_posts()

# Working and verified RSS feeds only
SOURCES = {
    "AI News": [
        "https://techcrunch.com/category/artificial-intelligence/feed/",
        "https://venturebeat.com/category/ai/feed/",
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
        "https://blog.streamlit.io/rss/",
    ],
    "AI Research": [
        "https://deepmind.google/blog/rss.xml",
        "https://www.microsoft.com/en-us/research/feed/",
        "https://blog.research.google/feeds/posts/default",
        "https://blogs.nvidia.com/blog/category/deep-learning/feed/",
        "https://distill.pub/rss.xml",
        "https://bair.berkeley.edu/blog/feed.xml",
    ],
    "Data Science & ML": [
        "https://blog.dataiku.com/rss.xml",
    ],
    "Open Source AI": [
        "https://opensource.com/feed",
        "https://blog.python.org/feeds/posts/default"
    ]
}

def clean_html(raw_html):
    """Clean HTML content and extract readable text"""
    if not raw_html:
        return ""
    soup = BeautifulSoup(raw_html, "html.parser")
    for script in soup(["script", "style"]):
        script.decompose()
    text = soup.get_text()
    lines = (line.strip() for line in text.splitlines())
    chunks = (phrase.strip() for line in lines for phrase in line.split("  "))
    return ' '.join(chunk for chunk in chunks if chunk)

def hash_post(title, link):
    """Generate unique hash for each post"""
    return hashlib.sha256(f"{title}{link}".encode()).hexdigest()

def fetch_feed(url, category):
    """Fetch and parse RSS feed"""
    max_retries = 2
    for attempt in range(max_retries):
        try:
            print(f"Fetching {category}: {url} (attempt {attempt + 1}/{max_retries})")
            
            old_timeout = socket.getdefaulttimeout()
            socket.setdefaulttimeout(30)
            
            try:
                headers = {
                    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
                    'Accept': 'application/rss+xml, application/xml, text/xml, */*',
                }
                
                feed = feedparser.parse(url, request_headers=headers)
            finally:
                socket.setdefaulttimeout(old_timeout)
            
            if hasattr(feed, 'bozo') and feed.bozo and feed.bozo_exception:
                print(f"[!] Feed parsing warning for {url}: {feed.bozo_exception}")
            
            if not feed.entries:
                status = getattr(feed, 'status', 'Unknown')
                print(f"[!] No entries for {url} (Status: {status})")
                if attempt < max_retries - 1 and status in [500, 502, 503, 504]:
                    time.sleep(5)
                    continue
                return []
            
            print(f"[+] Found {len(feed.entries)} entries from {url}")
            entries = []
            
            for entry in feed.entries[:3]:  # Only take 3 most recent per feed
                try:
                    title = entry.get("title", "No Title").strip()
                    link = entry.get("link", "")
                    
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
                    
                    if not title or not link:
                        continue
                    
                    if len(summary) < 30:
                        summary = "Click to read the full article for more details."
                    
                    uid = hash_post(title, link)
                    if uid in sent_posts:
                        continue
                    
                    pub_date = ""
                    if hasattr(entry, 'published'):
                        try:
                            pub_date = f"\n📅 {entry.published}"
                        except:
                            pass
                    
                    summary_text = summary[:500] + ('...' if len(summary) > 500 else '')
                    
                    message = (
                        f"🧠 *{category}*\n\n"
                        f"📰 *{title}*\n\n"
                        f"📝 {summary_text}\n\n"
                        f"🔗 [Read Full Article]({link}){pub_date}\n\n"
                        f"━━━━━━━━━━━━━━━━━━━━━━━"
                    )
                    
                    entries.append((uid, title, message))
                    
                except Exception as e:
                    print(f"Error processing entry: {e}")
                    continue
            
            return entries
            
        except Exception as e:
            print(f"Error fetching {url}: {e}")
            if attempt < max_retries - 1:
                time.sleep(5)
                continue
            return []
    
    return []

def fetch_all(sources):
    """Fetch all feeds concurrently"""
    all_entries = []
    tasks = [(url, category) for category, urls in sources.items() for url in urls]
    
    print(f"\n🔍 Fetching {len(tasks)} RSS feeds...")
    
    with concurrent.futures.ThreadPoolExecutor(max_workers=5) as executor:
        futures = [executor.submit(fetch_feed, url, category) for url, category in tasks]
        
        for future in concurrent.futures.as_completed(futures, timeout=300):
            try:
                result = future.result()
                if result:
                    all_entries.extend(result)
            except Exception as e:
                print(f"Future failed: {e}")
    
    print(f"✅ Total new entries collected: {len(all_entries)}\n")
    return all_entries

async def post_article(uid, title, message):
    """Post a single article"""
    try:
        await bot.send_message(
            chat_id=CHANNEL_ID,
            text=message,
            parse_mode='Markdown',
            disable_web_page_preview=False
        )
        
        sent_posts.add(uid)
        with open(POST_LOG_FILE, 'a', encoding='utf-8') as f:
            f.write(f"{uid}\n")
        
        print(f"✅ Posted: {title[:60]}...")
        return True
        
    except Exception as e:
        print(f"❌ Error posting: {e}")
        return False

async def main():
    print("="*60)
    print("🤖 AI RSS Bot - Continuous Posting Mode")
    print("="*60)
    print(f"📢 Channel: {CHANNEL_ID}")
    print(f"⏰ Posting interval: 12 minutes")
    print(f"📊 Tracked posts: {len(sent_posts)}")
    print("="*60)
    
    while True:
        try:
            print(f"\n⏰ {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} - Fetching feeds...\n")
            
            # Fetch new articles
            articles = fetch_all(SOURCES)
            
            if articles:
                print(f"📬 Starting to post {len(articles)} articles...\n")
                
                for i, (uid, title, message) in enumerate(articles):
                    # Post the article
                    success = await post_article(uid, title, message)
                    
                    # Wait 12 minutes before next post (except for the last one)
                    if success and i < len(articles) - 1:
                        next_post_time = datetime.now() + timedelta(minutes=12)
                        print(f"⏳ Next post at {next_post_time.strftime('%H:%M:%S')}\n")
                        await asyncio.sleep(12 * 60)  # 12 minutes
                
                print(f"\n✅ Finished posting {len(articles)} articles")
            else:
                print("📭 No new articles found")
            
            # After posting all, wait 12 minutes before fetching again
            next_fetch = datetime.now() + timedelta(minutes=12)
            print(f"\n⏸️  Next fetch cycle at {next_fetch.strftime('%H:%M:%S')}")
            await asyncio.sleep(12 * 60)
            
        except KeyboardInterrupt:
            print("\n\n👋 Bot stopped")
            break
        except Exception as e:
            print(f"\n❌ Error: {e}")
            print("⏳ Retrying in 5 minutes...\n")
            await asyncio.sleep(5 * 60)

if __name__ == "__main__":
    asyncio.run(main())