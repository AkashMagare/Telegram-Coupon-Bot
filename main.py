"""Application entry point for the Telegram coupon bot."""

from coupon_bot.bot import CouponBot
from coupon_bot.config import ConfigurationError, load_settings


def main() -> None:
    try:
        settings = load_settings()
    except ConfigurationError as exc:
        raise SystemExit(f"Configuration error: {exc}") from exc

    CouponBot(settings).run()


if __name__ == "__main__":
    main()
