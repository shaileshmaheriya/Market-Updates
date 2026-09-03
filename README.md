# Market News Intelligence → Instagram Bot

Checks the market news every few hours, has Claude analyze it against your
master prompt, and sends you the draft (report + Instagram caption + image
preview) on Telegram. You approve or reject with one tap — from your phone —
and only approved posts go to Instagram.

Nothing runs on your laptop. Once deployed, this runs 24/7 in the cloud.

## 1. Get your credentials

You'll need 5 things — see `.env.example` for exactly what each one is:

| Variable | Where to get it |
|---|---|
| `ANTHROPIC_API_KEY` | console.anthropic.com → API Keys |
| `TELEGRAM_BOT_TOKEN` | Message **@BotFather** on Telegram → `/newbot` |
| `TELEGRAM_CHAT_ID` | Message **@userinfobot** on Telegram, it replies with your ID |
| `IG_USER_ID` + `IG_ACCESS_TOKEN` | developers.facebook.com → your app → Graph API Explorer (see below) |
| `IMGBB_API_KEY` | Free signup at api.imgbb.com |

### Getting the Instagram credentials specifically
1. Convert your Instagram to a **Business** or **Creator** account and link it
   to a Facebook Page (Settings → Account type).
2. Create an app at developers.facebook.com, add the **Instagram Graph API**
   product, and add yourself as an **Instagram Tester** under Roles → Roles.
   Since you're only publishing to your own account, this skips the multi-week
   app review process.
3. In Graph API Explorer, select your app, generate a **User Access Token**
   with `instagram_business_basic` and `instagram_business_content_publish`
   permissions, and exchange it for a long-lived token (docs.developers.facebook.com
   has an "Access Token Debugger" that will do this for you).
4. Call `GET /me/accounts` then `GET /{page-id}?fields=instagram_business_account`
   to find your numeric `IG_USER_ID`.

## 2. Install locally to test (optional)

```bash
pip install -r requirements.txt
cp .env.example .env   # fill in your real values
export $(cat .env | xargs)   # loads them into your shell
python main.py
```

Send `/start` to your bot on Telegram, then `/runnow` to trigger an
analysis cycle immediately instead of waiting for the schedule.

## 3. Deploy so it runs 24/7 (recommended: Railway)

Railway's free tier is enough for this and needs no server management:

1. Push this folder to a GitHub repo.
2. Go to railway.app → New Project → Deploy from GitHub repo.
3. In the project's **Variables** tab, paste in everything from your `.env`.
4. Railway will run `python main.py` automatically and keep it alive.

(Render.com or Fly.io work the same way if you prefer those.)

## 4. Using it day to day

- The bot checks news every `RUN_INTERVAL_HOURS` (default 4) and messages
  you on Telegram — from your phone, tablet, or laptop, doesn't matter which
  is on.
- Tap **✅ Approve & Post** to publish immediately, or **❌ Reject** to
  discard. Nothing posts without your tap.
- Send `/runnow` anytime to trigger a check on demand.

## Notes / things to tune

- `NEWS_FEEDS` in `main.py` currently uses generic Google News RSS queries.
  Swap in feeds specific to your market (e.g. NSE/BSE announcements, RBI, a
  specific news publisher's RSS) for better signal.
- The image card is intentionally simple (headline + verdict badge). Edit
  `image_card.py` if you want your own branding/logo/colors.
- X/Twitter was left out per your last message — the `post_to_instagram`
  function is isolated, so adding an X posting step later is a small addition,
  not a rebuild.
