"""Telegram handlers and presentation layer for the coupon bot."""

from __future__ import annotations

import html
import logging
import sqlite3
import time
from threading import Lock
from typing import Any

from telegram import BotCommand, InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.constants import ParseMode
from telegram.ext import (
    Application,
    ApplicationBuilder,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

from .config import Settings
from .database import Coupon, CouponPage, CouponRepository


logger = logging.getLogger(__name__)
MAX_SEARCH_LENGTH = 100
MAX_TELEGRAM_MESSAGE_LENGTH = 4096


class RateLimiter:
    """Small in-memory per-user limiter for command and text searches."""

    def __init__(self, interval_seconds: float) -> None:
        self.interval_seconds = interval_seconds
        self._last_request: dict[int, float] = {}
        self._lock = Lock()

    def allow(self, user_id: int) -> bool:
        if self.interval_seconds == 0:
            return True

        now = time.monotonic()
        with self._lock:
            previous = self._last_request.get(user_id)
            if previous is not None and now - previous < self.interval_seconds:
                return False
            self._last_request[user_id] = now
            if len(self._last_request) > 10_000:
                cutoff = now - max(self.interval_seconds, 60.0)
                self._last_request = {
                    key: value
                    for key, value in self._last_request.items()
                    if value >= cutoff
                }
            return True


class CouponBot:
    """Build and run the Telegram application."""

    def __init__(self, settings: Settings) -> None:
        logging.basicConfig(
            level=getattr(logging, settings.log_level),
            format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        )
        self.settings = settings
        self.repository = CouponRepository(settings.database_path)
        self.rate_limiter = RateLimiter(settings.rate_limit_seconds)
        self.application = self._build_application()

    def _build_application(self) -> Application:
        application = (
            ApplicationBuilder()
            .token(self.settings.bot_token)
            .post_init(self._post_init)
            .build()
        )
        application.add_handler(CommandHandler("start", self.start))
        application.add_handler(CommandHandler("help", self.help_command))
        application.add_handler(CommandHandler("coupons", self.coupons))
        application.add_handler(CommandHandler("search", self.search))
        application.add_handler(CommandHandler("category", self.category))
        application.add_handler(CommandHandler("categories", self.categories))
        application.add_handler(CommandHandler("stores", self.stores))
        application.add_handler(CommandHandler("addcoupon", self.add_coupon))
        application.add_handler(CommandHandler("deactivate", self.deactivate))
        application.add_handler(CommandHandler("stats", self.stats))
        application.add_handler(CallbackQueryHandler(self.callback_query))
        application.add_handler(
            MessageHandler(filters.TEXT & ~filters.COMMAND, self.text_search)
        )
        application.add_error_handler(self.error_handler)
        return application

    async def _post_init(self, application: Application) -> None:
        self.repository.deactivate_expired()
        if application.job_queue is not None:
            application.job_queue.run_repeating(
                self._cleanup_expired,
                interval=24 * 60 * 60,
                first=24 * 60 * 60,
                name="deactivate-expired-coupons",
            )

        await application.bot.set_my_commands(
            [
                BotCommand("start", "Welcome message and quick help"),
                BotCommand("coupons", "Browse active coupons"),
                BotCommand("search", "Search by store, code, or product"),
                BotCommand("category", "Browse one coupon category"),
                BotCommand("categories", "List available categories"),
                BotCommand("stores", "List available stores"),
                BotCommand("help", "Show command help"),
            ]
        )

    async def _cleanup_expired(self, context: ContextTypes.DEFAULT_TYPE) -> None:
        del context
        changed = self.repository.deactivate_expired()
        if changed:
            logger.info("Deactivated %d expired coupons", changed)

    def run(self) -> None:
        """Start long polling until the process exits."""

        try:
            self.application.run_polling(allowed_updates=Update.ALL_TYPES)
        finally:
            self.repository.close()

    async def _allowed(self, update: Update) -> bool:
        user = update.effective_user
        message = update.effective_message
        if user is None or message is None:
            return False
        if self.rate_limiter.allow(user.id):
            return True
        await message.reply_text("Please wait a moment before sending another request.")
        return False

    async def _require_admin(self, update: Update) -> bool:
        if not await self._allowed(update):
            return False
        user = update.effective_user
        if user is None or user.id not in self.settings.admin_ids:
            await update.effective_message.reply_text(
                "This command is available only to configured bot admins."
            )
            return False
        return True

    @staticmethod
    def _html(value: Any) -> str:
        return html.escape(str(value), quote=True)

    @staticmethod
    def _shorten(value: str, maximum: int) -> str:
        if len(value) <= maximum:
            return value
        return f"{value[: maximum - 1].rstrip()}…"

    async def start(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        del context
        if not await self._allowed(update):
            return
        first_name = self._html(update.effective_user.first_name or "there")
        await update.effective_message.reply_text(
            f"👋 <b>Hi {first_name}!</b>\n\n"
            "Find active sale offers and coupon codes in seconds.\n\n"
            "Try <code>/coupons</code> to browse or "
            "<code>/search nike</code> to search.",
            parse_mode=ParseMode.HTML,
        )

    async def help_command(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ) -> None:
        del context
        if not await self._allowed(update):
            return
        text = (
            "<b>Coupon bot commands</b>\n\n"
            "<code>/coupons</code> — browse active offers\n"
            "<code>/search &lt;words&gt;</code> — search stores, products, or codes\n"
            "<code>/category &lt;name&gt;</code> — filter by category\n"
            "<code>/categories</code> — list categories\n"
            "<code>/stores</code> — list stores\n\n"
            "You can also send a store or product name as a normal message."
        )
        if update.effective_user and update.effective_user.id in self.settings.admin_ids:
            text += (
                "\n\n<b>Admin commands</b>\n"
                "<code>/addcoupon</code> — add an offer\n"
                "<code>/deactivate &lt;id&gt;</code> — hide an offer\n"
                "<code>/stats</code> — view bot statistics"
            )
        await update.effective_message.reply_text(text, parse_mode=ParseMode.HTML)

    @staticmethod
    def _page_argument(context: ContextTypes.DEFAULT_TYPE) -> int:
        if not context.args:
            return 1
        try:
            return max(1, int(context.args[0]))
        except ValueError:
            return 1

    async def coupons(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not await self._allowed(update):
            return
        await self._show_page(
            update,
            context,
            kind="coupons",
            page=self._page_argument(context),
        )

    async def search(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not await self._allowed(update):
            return
        query = " ".join(context.args).strip()
        await self._run_search(update, context, query)

    async def text_search(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not await self._allowed(update):
            return
        query = (update.effective_message.text or "").strip()
        await self._run_search(update, context, query)

    async def _run_search(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
        query: str,
    ) -> None:
        if not query:
            await update.effective_message.reply_text(
                "Use <code>/search &lt;store or product&gt;</code>.",
                parse_mode=ParseMode.HTML,
            )
            return
        if len(query) > MAX_SEARCH_LENGTH:
            await update.effective_message.reply_text(
                f"Searches must be {MAX_SEARCH_LENGTH} characters or fewer."
            )
            return
        await self._show_page(update, context, kind="search", page=1, query=query)

    async def category(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not await self._allowed(update):
            return
        category = " ".join(context.args).strip()
        if not category:
            await update.effective_message.reply_text(
                "Use <code>/category &lt;name&gt;</code> or see <code>/categories</code>.",
                parse_mode=ParseMode.HTML,
            )
            return
        await self._show_page(
            update,
            context,
            kind="category",
            page=1,
            category=category,
        )

    async def categories(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        del context
        if not await self._allowed(update):
            return
        values = self.repository.categories()
        if not values:
            await update.effective_message.reply_text("No categories have been added yet.")
            return
        text = "<b>Categories</b>\n\n" + "\n".join(
            f"• {self._html(value)}" for value in values
        )
        await update.effective_message.reply_text(text, parse_mode=ParseMode.HTML)

    async def stores(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        del context
        if not await self._allowed(update):
            return
        values = self.repository.stores()
        if not values:
            await update.effective_message.reply_text("No stores have been added yet.")
            return
        text = "<b>Stores</b>\n\n" + "\n".join(
            f"• {self._html(value)}" for value in values
        )
        await update.effective_message.reply_text(text, parse_mode=ParseMode.HTML)

    def _fetch_page(
        self,
        *,
        kind: str,
        page: int,
        query: str = "",
        category: str = "",
    ) -> CouponPage:
        if kind == "search":
            return self.repository.search(query, page=page, page_size=self.settings.page_size)
        if kind == "category":
            return self.repository.list_active(
                page=page,
                page_size=self.settings.page_size,
                category=category,
            )
        return self.repository.list_active(page=page, page_size=self.settings.page_size)

    async def _show_page(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
        *,
        kind: str,
        page: int,
        query: str = "",
        category: str = "",
    ) -> None:
        self.repository.deactivate_expired()
        coupon_page = self._fetch_page(
            kind=kind,
            page=page,
            query=query,
            category=category,
        )
        if coupon_page.total and page > coupon_page.total_pages:
            page = coupon_page.total_pages
            coupon_page = self._fetch_page(
                kind=kind,
                page=page,
                query=query,
                category=category,
            )

        context.user_data["last_view"] = {
            "kind": kind,
            "page": page,
            "query": query,
            "category": category,
        }
        text = self._format_page(coupon_page, kind, query=query, category=category)
        keyboard = self._page_keyboard(coupon_page, kind)
        await update.effective_message.reply_text(
            text,
            parse_mode=ParseMode.HTML,
            reply_markup=keyboard,
            disable_web_page_preview=True,
        )

    def _format_page(
        self,
        coupon_page: CouponPage,
        kind: str,
        *,
        query: str = "",
        category: str = "",
    ) -> str:
        if kind == "search":
            heading = f"🔎 <b>Search results for:</b> {self._html(query)}"
        elif kind == "category":
            heading = f"🏷 <b>Category:</b> {self._html(category)}"
        else:
            heading = "🎟 <b>Active coupons</b>"

        if not coupon_page.items:
            return f"{heading}\n\nNo matching active coupons found."

        footer = f"\n\nPage {coupon_page.page}/{coupon_page.total_pages} · {coupon_page.total} offer(s)"
        cards: list[str] = []
        for coupon in coupon_page.items:
            card = self._format_summary(coupon)
            candidate = f"{heading}\n\n" + "\n\n".join(
                [*cards, card]
            ) + footer
            if len(candidate) > MAX_TELEGRAM_MESSAGE_LENGTH and cards:
                break
            cards.append(card)
        return f"{heading}\n\n" + "\n\n".join(cards) + footer

    def _format_summary(self, coupon: Coupon) -> str:
        expiry = (
            f" · expires {self._html(coupon.expires_at)}"
            if coupon.expires_at
            else " · no expiry listed"
        )
        return (
            f"<b>{self._html(self._shorten(coupon.title, 70))}</b>"
            f" — {self._html(self._shorten(coupon.store, 40))}\n"
            f"💸 {self._html(self._shorten(coupon.discount, 60))} · "
            f"code <code>{self._html(self._shorten(coupon.code, 50))}</code>\n"
            f"🏷 {self._html(self._shorten(coupon.category, 30))}{expiry}"
        )

    def _page_keyboard(self, coupon_page: CouponPage, kind: str) -> InlineKeyboardMarkup | None:
        if not coupon_page.items and coupon_page.total_pages <= 1:
            return None

        rows: list[list[InlineKeyboardButton]] = []
        for coupon in coupon_page.items:
            title = self._shorten(coupon.title, 24)
            rows.append(
                [
                    InlineKeyboardButton(
                        f"🔎 {title}", callback_data=f"details:{coupon.id}"
                    ),
                    InlineKeyboardButton("✅ Used", callback_data=f"use:{coupon.id}"),
                ]
            )

        navigation: list[InlineKeyboardButton] = []
        if coupon_page.page > 1:
            navigation.append(
                InlineKeyboardButton(
                    "◀️ Previous",
                    callback_data=f"{kind}:page:{coupon_page.page - 1}",
                )
            )
        if coupon_page.page < coupon_page.total_pages:
            navigation.append(
                InlineKeyboardButton(
                    "Next ▶️",
                    callback_data=f"{kind}:page:{coupon_page.page + 1}",
                )
            )
        if navigation:
            rows.append(navigation)
        return InlineKeyboardMarkup(rows) if rows else None

    def _format_detail(self, coupon: Coupon) -> str:
        lines = [
            f"🎟 <b>{self._html(coupon.title)}</b>",
            f"🏪 <b>Store:</b> {self._html(coupon.store)}",
            f"💸 <b>Offer:</b> {self._html(coupon.discount)}",
            f"🔑 <b>Code:</b> <code>{self._html(coupon.code)}</code>",
            f"🏷 <b>Category:</b> {self._html(coupon.category)}",
        ]
        if coupon.expires_at:
            lines.append(f"⏰ <b>Expires:</b> {self._html(coupon.expires_at)}")
        if coupon.description:
            lines.append(f"\n{self._html(coupon.description)}")
        return "\n".join(lines)

    def _detail_keyboard(self, coupon: Coupon, kind: str, page: int) -> InlineKeyboardMarkup:
        rows: list[list[InlineKeyboardButton]] = []
        if coupon.url:
            rows.append(
                [
                    InlineKeyboardButton(
                        "🔗 Open offer",
                        url=coupon.url,
                    )
                ]
            )
        rows.append(
            [
                InlineKeyboardButton("✅ I used this", callback_data=f"use:{coupon.id}"),
                InlineKeyboardButton("◀️ Back", callback_data=f"back:{kind}:{page}"),
            ]
        )
        return InlineKeyboardMarkup(rows)

    async def callback_query(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ) -> None:
        query = update.callback_query
        if query is None:
            return
        data = query.data or ""

        if data.startswith("details:"):
            coupon_id = self._callback_id(data)
            if coupon_id is None:
                await query.answer("Invalid coupon", show_alert=True)
                return
            coupon = self.repository.record_view(coupon_id)
            if coupon is None:
                await query.answer("This coupon has expired.", show_alert=True)
                return
            state = context.user_data.get("last_view", {})
            kind = str(state.get("kind", "coupons"))
            page = max(1, int(state.get("page", 1)))
            await query.answer()
            await query.edit_message_text(
                self._format_detail(coupon),
                parse_mode=ParseMode.HTML,
                reply_markup=self._detail_keyboard(coupon, kind, page),
                disable_web_page_preview=True,
            )
            return

        if data.startswith("use:"):
            coupon_id = self._callback_id(data)
            if coupon_id is None or not self.repository.mark_used(coupon_id):
                await query.answer("This coupon is no longer active.", show_alert=True)
            else:
                await query.answer("Marked as used. Good luck with your purchase!", show_alert=False)
            return

        if ":page:" in data:
            kind, raw_page = data.split(":page:", 1)
            if kind not in {"coupons", "search", "category"}:
                await query.answer("Invalid page", show_alert=True)
                return
            try:
                page = max(1, int(raw_page))
            except ValueError:
                await query.answer("Invalid page", show_alert=True)
                return
            state = context.user_data.get("last_view", {})
            query_text = str(state.get("query", "")) if kind == "search" else ""
            category = str(state.get("category", "")) if kind == "category" else ""
            coupon_page = self._fetch_page(
                kind=kind,
                page=page,
                query=query_text,
                category=category,
            )
            if coupon_page.total and page > coupon_page.total_pages:
                page = coupon_page.total_pages
                coupon_page = self._fetch_page(
                    kind=kind,
                    page=page,
                    query=query_text,
                    category=category,
                )
            context.user_data["last_view"] = {
                "kind": kind,
                "page": page,
                "query": query_text,
                "category": category,
            }
            await query.answer()
            await query.edit_message_text(
                self._format_page(coupon_page, kind, query=query_text, category=category),
                parse_mode=ParseMode.HTML,
                reply_markup=self._page_keyboard(coupon_page, kind),
                disable_web_page_preview=True,
            )
            return

        if data.startswith("back:"):
            parts = data.split(":")
            if len(parts) != 3 or parts[1] not in {"coupons", "search", "category"}:
                await query.answer("Invalid page", show_alert=True)
                return
            kind = parts[1]
            try:
                page = max(1, int(parts[2]))
            except ValueError:
                await query.answer("Invalid page", show_alert=True)
                return
            state = context.user_data.get("last_view", {})
            query_text = str(state.get("query", "")) if kind == "search" else ""
            category = str(state.get("category", "")) if kind == "category" else ""
            coupon_page = self._fetch_page(
                kind=kind,
                page=page,
                query=query_text,
                category=category,
            )
            await query.answer()
            await query.edit_message_text(
                self._format_page(coupon_page, kind, query=query_text, category=category),
                parse_mode=ParseMode.HTML,
                reply_markup=self._page_keyboard(coupon_page, kind),
                disable_web_page_preview=True,
            )
            return

        await query.answer()

    @staticmethod
    def _callback_id(data: str) -> int | None:
        try:
            value = int(data.split(":", 1)[1])
        except (IndexError, ValueError):
            return None
        return value if value > 0 else None

    @staticmethod
    def _payload(update: Update) -> str:
        text = update.effective_message.text or ""
        return text.split(" ", 1)[1].strip() if " " in text else ""

    async def add_coupon(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        del context
        if not await self._require_admin(update):
            return

        fields = [part.strip() for part in self._payload(update).split("|")]
        if len(fields) < 5 or len(fields) > 8:
            await update.effective_message.reply_text(
                "Format:\n"
                "<code>/addcoupon Store | CODE | Title | Discount | Category | "
                "YYYY-MM-DD | URL | Description</code>\n\n"
                "Expiry, URL, and description are optional; use <code>-</code> to skip a field.",
                parse_mode=ParseMode.HTML,
            )
            return
        fields.extend([""] * (8 - len(fields)))
        store, code, title, discount, category, expiry, url, description = fields
        try:
            coupon_id = self.repository.add_coupon(
                store=store,
                code=code,
                title=title,
                discount=discount or "Special offer",
                category=category or "Other",
                expires_at=expiry or None,
                url=url or None,
                description=description,
                created_by=update.effective_user.id,
            )
        except sqlite3.IntegrityError:
            await update.effective_message.reply_text(
                "A coupon with that store and code already exists."
            )
            return
        except ValueError as exc:
            await update.effective_message.reply_text(f"Could not add coupon: {exc}")
            return

        await update.effective_message.reply_text(
            f"✅ Coupon added successfully with ID <code>{coupon_id}</code>.",
            parse_mode=ParseMode.HTML,
        )

    async def deactivate(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        del context
        if not await self._require_admin(update):
            return
        if not update.effective_message.text:
            return
        parts = update.effective_message.text.split()
        if len(parts) != 2 or not parts[1].isdigit():
            await update.effective_message.reply_text(
                "Use <code>/deactivate &lt;coupon_id&gt;</code>.",
                parse_mode=ParseMode.HTML,
            )
            return
        if self.repository.deactivate(int(parts[1])):
            await update.effective_message.reply_text("✅ Coupon deactivated.")
        else:
            await update.effective_message.reply_text("Coupon not found or already inactive.")

    async def stats(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        del context
        if not await self._require_admin(update):
            return
        values = self.repository.stats()
        await update.effective_message.reply_text(
            "<b>Coupon statistics</b>\n\n"
            f"Total records: {values['total']}\n"
            f"Active offers: {values['active']}\n"
            f"Details viewed: {values['views']}\n"
            f"Marked used: {values['uses']}",
            parse_mode=ParseMode.HTML,
        )

    async def error_handler(
        self, update: object, context: ContextTypes.DEFAULT_TYPE
    ) -> None:
        error = context.error
        if error is None:
            logger.error("Unhandled Telegram update %r", update)
            return
        logger.error(
            "Unhandled Telegram update %r: %s",
            update,
            error,
            exc_info=(type(error), error, error.__traceback__),
        )
