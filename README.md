# Telegram AI Channel Bot

This bot fetches AI-related news from various RSS feeds and posts them to a Telegram channel.

## Features
- Fetches RSS feeds from multiple AI news sources
- Posts 9 articles per day (3 in the morning, 3 in the afternoon, 3 in the evening)
- Prevents duplicate posts using a log file
- Cleans up old log entries periodically

## Deployment to Render

### Prerequisites
- A GitHub account
- A Render account (sign up at https://render.com)
- A Telegram bot token from @BotFather
- A Telegram channel where the bot has posting permissions

### Steps

1. **Prepare your repository**
   - Fork or clone this repository to your GitHub account
   - Make sure all files are present: `Automatization.py`, `requirements.txt`, `runtime.txt`

2. **Set up environment variables**
   - Create environment variables on Render for:
     - `TELEGRAM_BOT_TOKEN` - Your bot's API token from @BotFather
     - `TELEGRAM_CHANNEL_ID` - The ID of your Telegram channel (e.g., @your_channel_name)

3. **Deploy to Render**
   - Go to https://dashboard.render.com
   - Click "New +" and select "Web Service"
   - Connect your GitHub account
   - Select your forked repository
   - Configure the deployment:
     - Environment: Python
     - Build Command: `pip install -r requirements.txt`
     - Start Command: `python Automatization.py`
   - Add the environment variables mentioned above
   - Click "Create Web Service"

4. **Monitor the deployment**
   - Check the logs to ensure the bot starts correctly
   - Verify that the bot is posting to your Telegram channel

## Important Notes
- The free tier on Render may have limitations on continuous operation
- For true 24/7 operation, consider upgrading to a paid plan
- The bot schedules posts for 8-10 AM, 1-3 PM, and 6-8 PM (in the server's timezone)
- A health check endpoint is included to help prevent the service from sleeping
- Include a simple ping service to keep the free tier active (though this may violate terms of service)
