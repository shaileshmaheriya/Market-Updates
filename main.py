"""
Market News Intelligence -> Instagram bot.

Flow:
  1. Every N hours, fetch headlines from RSS feeds.
  2. Send them to Claude with master_prompt.txt to get a report + IG caption.
  3. If a caption was produced, generate an image card and send BOTH to your
     Telegram chat with Approve / Reject buttons.
  4. On Approve, publish to Instagram. On Reject, discard. Nothing ever posts
     without your tap.

Run this as a single long-lived process (see README.md for deployment).
"""
import json
import logging
import os
import time

import feedparser
import requests
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
)

from image_card import make_public_image_url

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("ig-market-bot")

# ---- required to run at all ----
ANTHROPIC_API_KEY = os.environ["ANTHROPIC_API_KEY"]
TELEGRAM_BOT_TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
TELEGRAM_CHAT_ID = os.environ["TELEGRAM_CHAT_ID"]

# ---- optional until you're ready to actually publish to Instagram ----
# The bot will start and send you drafts on Telegram without these. Tapping
# "Approve & Post" before they're set just shows a clear error instead of
# crashing the whole bot.
IG_USER_ID = os.environ.get("IG_USER_ID")
IG_ACCESS_TOKEN = os.environ.get("IG_ACCESS_TOKEN")
IMGBB_API_KEY_SET = bool(os.environ.get("IMGBB_API_KEY"))

RUN_INTERVAL_HOURS = float(os.environ.get("RUN_INTERVAL_HOURS", "4"))
CLAUDE_MODEL = os.environ.get("CLAUDE_MODEL", "claude-sonnet-4-6")

HERE = os.path.dirname(os.path.abspath(__file__))
with open(os.path.join(HERE, "master_prompt.txt"), encoding="utf-8") as f:
    MASTER_PROMPT = f.read()

NEWS_FEEDS = [
    "https://news.google.com/rss/search?q=stock+market+when:1d&hl=en-US&gl=US&ceid=US:en",
    "https://news.google.com/rss/search?q=earnings+when:1d&hl=en-US&gl=US&ceid=US:en",
    "https://news.google.com/rss/search?q=federal+reserve+when:1d&hl=en-US&gl=US&ceid=US:en",
    # Add/replace with feeds relevant to your market (e.g. NSE/BSE, RBI, etc.)
]

# in-memory store of drafts awaiting a Telegram tap: post_id -> dict
pending_posts: dict[str, dict] = {}


def fetch_headlines(max_per_feed: int = 8) -> list[dict]:
    items = []
    for url in NEWS_FEEDS:
        try:
            feed = feedparser.parse(url)
        except Exception as e:
            log.warning("Failed to parse feed %s: %s", url, e)
            continue
        for entry in feed.entries[:max_per_feed]:
            items.append(
                {
                    "title": entry.get("title", ""),
                    "link": entry.get("link", ""),
                    "published": entry.get("published", ""),
                    "source": entry.get("source", {}).get("title", "") if hasattr(entry, "source") else "",
                }
            )
    return items


def call_claude(headlines: list[dict]) -> dict:
    prompt = (
        MASTER_PROMPT
        + "\n\nToday's raw headlines (JSON):\n"
        + json.dumps(headlines, indent=2)
        + "\n\nRespond with ONLY the JSON object described above. No markdown fences."
    )
    resp = requests.post(
        "https://api.anthropic.com/v1/messages",
        headers={
            "x-api-key": ANTHROPIC_API_KEY,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        },
        json={
            "model": CLAUDE_MODEL,
            "max_tokens": 2000,
            "messages": [{"role": "user", "content": prompt}],
        },
        timeout=60,
    )
    resp.raise_for_status()
    data = resp.json()
    text = "".join(block.get("text", "") for block in data.get("content", []))
    text = text.strip()
    if text.startswith("```"):
        text = text.strip("`")
        if text.startswith("json"):
            text = text[4:]
    return json.loads(text)


def post_to_instagram(caption: str, image_url: str) -> dict:
    if not (IG_USER_ID and IG_ACCESS_TOKEN):
        raise RuntimeError(
            "Instagram isn't set up yet — IG_USER_ID and IG_ACCESS_TOKEN are missing. "
            "Add them in Railway's Variables tab once you've completed the Meta setup."
        )
    if not IMGBB_API_KEY_SET:
        raise RuntimeError(
            "IMGBB_API_KEY is missing — needed to host the post image publicly. "
            "Add it in Railway's Variables tab."
        )
    container = requests.post(
        f"https://graph.facebook.com/v21.0/{IG_USER_ID}/media",
        data={"image_url": image_url, "caption": caption, "access_token": IG_ACCESS_TOKEN},
        timeout=30,
    ).json()
    if "id" not in container:
        raise RuntimeError(f"Container creation failed: {container}")

    publish = requests.post(
        f"https://graph.facebook.com/v21.0/{IG_USER_ID}/media_publish",
        data={"creation_id": container["id"], "access_token": IG_ACCESS_TOKEN},
        timeout=30,
    ).json()
    if "id" not in publish:
        raise RuntimeError(f"Publish failed: {publish}")
    return publish


async def run_analysis_job(context: ContextTypes.DEFAULT_TYPE):
    log.info("Running analysis job...")
    headlines = fetch_headlines()
    if not headlines:
        log.info("No headlines fetched, skipping.")
        return

    try:
        result = call_claude(headlines)
    except Exception as e:
        log.exception("Claude analysis failed")
        await context.bot.send_message(TELEGRAM_CHAT_ID, f"⚠️ Analysis failed: {e}")
        return

    caption = result.get("instagram_caption")
    if not caption:
        log.info("No story strong enough to publish this cycle.")
        await context.bot.send_message(
            TELEGRAM_CHAT_ID,
            "🟡 No story met the bar for publishing this cycle. Report below for your reference:\n\n"
            + result.get("report", "")[:3500],
        )
        return

    post_id = str(int(time.time()))
    pending_posts[post_id] = {
        "caption": caption,
        "headline": result.get("image_headline") or "Market Update",
        "verdict": result.get("image_verdict") or "UNCLEAR",
    }

    keyboard = InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton("✅ Approve & Post", callback_data=f"approve:{post_id}"),
                InlineKeyboardButton("❌ Reject", callback_data=f"reject:{post_id}"),
            ]
        ]
    )
    message = (
        f"📊 *Draft ready*\n\n{result.get('report', '')[:2500]}\n\n"
        f"---\n*Instagram caption:*\n{caption}"
    )
    await context.bot.send_message(TELEGRAM_CHAT_ID, message, reply_markup=keyboard, parse_mode="Markdown")


async def handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    action, post_id = query.data.split(":", 1)
    draft = pending_posts.pop(post_id, None)

    if not draft:
        await query.edit_message_text("This draft has expired or was already handled.")
        return

    if action == "reject":
        await query.edit_message_text("❌ Rejected — nothing was posted.")
        return

    if not (IG_USER_ID and IG_ACCESS_TOKEN and IMGBB_API_KEY_SET):
        await query.edit_message_text(
            "⚠️ Instagram isn't fully set up yet (missing IG_USER_ID, IG_ACCESS_TOKEN, "
            "and/or IMGBB_API_KEY in Railway). This draft was approved but not posted — "
            "add those variables and try again next cycle."
        )
        return

    await query.edit_message_text("⏳ Posting to Instagram...")
    try:
        image_url = make_public_image_url(draft["headline"], draft["verdict"])
        post_to_instagram(draft["caption"], image_url)
        await query.edit_message_text("✅ Posted to Instagram.")
    except Exception as e:
        log.exception("Failed to post to Instagram")
        await query.edit_message_text(f"⚠️ Post failed: {e}")


async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Bot is running. I'll check the news every "
        f"{RUN_INTERVAL_HOURS} hours and send you drafts here for approval."
    )


async def run_now_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Running analysis now...")
    await run_analysis_job(context)


def main():
    app = Application.builder().token(TELEGRAM_BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start_command))
    app.add_handler(CommandHandler("runnow", run_now_command))
    app.add_handler(CallbackQueryHandler(handle_callback))
    app.job_queue.run_repeating(run_analysis_job, interval=RUN_INTERVAL_HOURS * 3600, first=15)
    log.info("Bot started. Polling for Telegram updates...")
    app.run_polling()


if __name__ == "__main__":
    main()
