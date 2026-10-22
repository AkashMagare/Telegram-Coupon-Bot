# Telegram Coupon Bot

A Telegram bot that helps users find and share coupon codes directly in chat.

## Why I built it

I wanted to practice building a real, working tool that people can use from their phone. This project taught me how to connect an external messaging API, handle user commands, and keep data organized.

## Features

- *(List the main commands, for example `/start`, `/coupons`, `/search`)*
- *(Describe how coupons are stored or fetched)*

## How it works

1. A user sends a command to the bot in Telegram.
2. The bot reads the command and looks up matching coupons.
3. The bot replies in the chat with the result.

## Tech stack

- Python
- Telegram Bot API
- *(Add any libraries you used, for example python-telegram-bot)*

## Getting started

```bash
# 1. Clone the repository
git clone https://github.com/AkashMagare/telegram-coupon-bot.git
cd telegram-coupon-bot

# 2. Install dependencies
pip install -r requirements.txt

# 3. Add your bot token
# Create a .env file and add: BOT_TOKEN=your_token_here

# 4. Run the bot
python main.py
```

*(Update the file names above to match your project.)*

## What I learned

- How to use an API token securely, without putting it in the code
- How to structure a bot so each command does one job
- How to test a bot by using a private test chat first

## Possible next steps

- Store coupons in a database instead of a file
- Add expiry dates and automatic cleanup of old coupons
- Track which coupons are used most often
