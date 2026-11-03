# Telegram Coupon Bot

<p align="center">
  A portfolio-ready Telegram bot for discovering and sharing sale offers and coupon codes directly in chat.
</p>

<p align="center">
  <a href="https://github.com/AkashMagare/Telegram-Coupon-Bot/actions/workflows/ci.yml"><img src="https://github.com/AkashMagare/Telegram-Coupon-Bot/actions/workflows/ci.yml/badge.svg" alt="CI status"></a>
  <img src="https://img.shields.io/badge/Python-3.10%2B-3776AB?logo=python&logoColor=white" alt="Python 3.10 or newer">
  <img src="https://img.shields.io/badge/Telegram-Bot%20API-26A5E4?logo=telegram&logoColor=white" alt="Telegram Bot API">
  <img src="https://img.shields.io/badge/Storage-SQLite-003B57?logo=sqlite&logoColor=white" alt="SQLite">
  <a href="LICENSE"><img src="https://img.shields.io/badge/License-MIT-green.svg" alt="MIT License"></a>
</p>

<p align="center">
  <b>Search deals. Share codes. Save more.</b>
</p>

## Features

- `/start` and `/help` commands with simple onboarding
- Browse active coupons with `/coupons`
- Search by store, product, category, discount, or code with `/search`
- Filter by category with `/category`
- List available categories and stores
- Inline pagination and coupon detail buttons
- Optional offer links and expiry dates
- Admin-only coupon management through Telegram
- SQLite storage with indexes, automatic expiry filtering, and FTS5 search when available
- Safe configuration through environment variables; no token is stored in source code
- Basic view/use counters for understanding which offers are useful
- Per-user request throttling to avoid accidental command floods
- Portfolio demo catalogue covering major Indian shopping and service platforms
- Automated tests and GitHub Actions CI
- Docker-ready deployment with a persistent SQLite volume

## Commands

| Command | Description |
| --- | --- |
| `/start` | Show the welcome message |
| `/coupons` | Browse active coupons |
| `/search nike` | Search for a store, product, or coupon code |
| `/category Electronics` | Filter offers by category |
| `/categories` | Show active categories |
| `/stores` | Show active stores |
| `/help` | Show command help |
| `/addcoupon ...` | Add an offer (admins only) |
| `/deactivate 12` | Hide a coupon by ID (admins only) |
| `/stats` | Show usage statistics (admins only) |

Users can also send a normal text message such as `running shoes` and the bot will treat it as a search.

## Included platform catalogue

The repository includes demo entries for:

- **Shopping:** Amazon India, Flipkart, Myntra, AJIO, Meesho, Tata CLiQ
- **Electronics:** Croma, Reliance Digital
- **Beauty:** Nykaa, Purplle
- **Grocery:** BigBasket, Blinkit, Zepto, JioMart
- **Food delivery:** Swiggy, Zomato
- **Travel:** MakeMyTrip, Goibibo, Cleartrip
- **Entertainment and mobility:** BookMyShow, Uber, Ola

The demo codes intentionally use a `DEMO-` prefix. They demonstrate the complete bot flow for a GitHub portfolio and are not guaranteed live offers. Verify a code before publishing it to real users.

## Example user flow

```text
User:   /search nykaa
Bot:    🔎 Search results for: nykaa
        Portfolio demo beauty offer — Nykaa
        💸 Up to 20% off beauty products · code DEMO-NYKAA-20

User:   taps the offer → views details → opens the store link
```

## How coupons are stored

Coupons are stored locally in SQLite. The database is created automatically at the path configured by `DATABASE_PATH`.

Each offer contains:

- Store, title, code, discount, and category
- Optional description and offer URL
- Optional expiry date in `YYYY-MM-DD` format
- Active status, view count, and used count

The repository adds indexes for active status, expiry, store, and category. When the installed SQLite build supports FTS5, search uses a full-text index; otherwise it safely falls back to a `LIKE` query. Expired coupons are excluded automatically and cleaned up once per day.

The current project uses admin-managed data rather than scraping or depending on a third-party coupon feed. This keeps the bot predictable and makes it easy to add a provider integration later.

## Getting started

### 1. Install

```bash
git clone https://github.com/AkashMagare/Telegram-Coupon-Bot.git
cd Telegram-Coupon-Bot

python -m venv .venv
# Windows PowerShell:
.venv\Scripts\Activate.ps1
# macOS/Linux:
# source .venv/bin/activate

pip install -r requirements.txt
```

Python 3.10 or newer is recommended.

### 2. Create a bot token

1. Open Telegram and message [@BotFather](https://t.me/BotFather).
2. Run `/newbot` and copy the token.
3. Copy `.env.example` to `.env`.
4. Set `BOT_TOKEN` in `.env`.

To manage coupons, add your numeric Telegram user ID to `ADMIN_IDS`. Multiple IDs can be comma-separated:

```env
BOT_TOKEN=123456:replace_me
ADMIN_IDS=123456789,987654321
```

Leave `ADMIN_IDS` empty for read-only mode.

### 3. Run

```bash
# Optional: populate the bot with the included platform demo catalogue
python scripts/seed_demo_data.py

python main.py
```

The first start creates `coupons.db` automatically. Keep `.env` and the database out of source control.

The seed script is safe to run more than once: existing store/code pairs are skipped. To use another database, pass `--database path/to/coupons.db`.

### Docker

```bash
docker build -t telegram-coupon-bot .
docker run --rm \
  --env-file .env \
  -v telegram-coupon-data:/data \
  telegram-coupon-bot
```

The container stores the SQLite database in `/data/coupons.db`. Keep the volume so coupons survive container restarts.

## Adding coupons

An admin can send this pipe-separated command in Telegram:

```text
/addcoupon Store | CODE | Title | Discount | Category | YYYY-MM-DD | URL | Description
```

Example:

```text
/addcoupon Example Store | SAVE20 | Twenty percent off shoes | 20% off | Fashion | 2026-12-31 | https://example.com/offer | Valid on selected products.
```

Expiry, URL, and description are optional. Use `-` for an empty expiry or URL. The bot rejects invalid URLs, invalid dates, duplicate store/code pairs, and oversized fields.

## Testing

The database tests use only Python's standard library and do not need a Telegram token:

```bash
python -m unittest discover -s tests -v
```

GitHub Actions runs compilation and the test suite on Python 3.10 through 3.13 for every push and pull request.

## What this project demonstrates

- Secure environment-based API configuration
- Async Telegram command and callback handling
- Input validation and admin authorization
- Indexed SQLite persistence with FTS5 search and expiry cleanup
- A maintainable separation between bot handlers, configuration, and storage

## Project structure

```text
Telegram-Coupon-Bot/
├── .github/workflows/ci.yml
├── coupon_bot/
│   ├── bot.py          # Telegram handlers, pagination, and admin commands
│   ├── config.py       # Validated environment configuration
│   └── database.py     # SQLite schema, search, expiry, and statistics
├── data/
│   └── demo_coupons.json
├── scripts/
│   └── seed_demo_data.py
├── tests/
│   ├── test_database.py
│   └── test_seed_demo_data.py
├── .env.example
├── CONTRIBUTING.md
├── Dockerfile
├── LICENSE
├── main.py
├── requirements.txt
└── README.md
```

## Possible next steps

- Add verified coupon-provider adapters or scheduled imports from trusted feeds
- Add opt-in notifications for newly added offers
- Add CSV import/export for larger coupon catalogues
- Add per-store usage analytics and a small admin dashboard
