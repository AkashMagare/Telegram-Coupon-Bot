"""Load the portfolio demo catalogue into the configured SQLite database."""

from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
from pathlib import Path

from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DATA_FILE = PROJECT_ROOT / "data" / "demo_coupons.json"
sys.path.insert(0, str(PROJECT_ROOT))

from coupon_bot.database import CouponRepository


def load_records() -> list[dict[str, str | None]]:
    with DATA_FILE.open(encoding="utf-8") as file:
        records = json.load(file)
    if not isinstance(records, list):
        raise ValueError("demo_coupons.json must contain a list")
    return records


def seed(database_path: str) -> tuple[int, int]:
    repository = CouponRepository(database_path)
    inserted = 0
    skipped = 0
    try:
        for record in load_records():
            try:
                repository.add_coupon(
                    store=str(record["store"] or ""),
                    code=str(record["code"] or ""),
                    title=str(record["title"] or ""),
                    discount=str(record["discount"] or "Special offer"),
                    category=str(record["category"] or "Other"),
                    description=str(record["description"] or ""),
                    url=record.get("url"),
                    expires_at=record.get("expires_at"),
                )
            except sqlite3.IntegrityError:
                skipped += 1
            else:
                inserted += 1
    finally:
        repository.close()
    return inserted, skipped


def main() -> None:
    load_dotenv(PROJECT_ROOT / ".env")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--database",
        default=os.getenv("DATABASE_PATH", "coupons.db"),
        help="SQLite database path (defaults to DATABASE_PATH or coupons.db)",
    )
    args = parser.parse_args()
    inserted, skipped = seed(args.database)
    print(f"Demo catalogue loaded: {inserted} inserted, {skipped} already present.")


if __name__ == "__main__":
    main()
