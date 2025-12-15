# Telegram Notifications Setup

AutoScalper can send real-time trading alerts to your Telegram account.

## What You'll Receive

1. **Order Submitted** - When an order is sent to IBKR
2. **Order Filled** - When an order is filled (or rejected/cancelled)
3. **Daily Summary** - End-of-day recap of all trades

## Setup Steps

### 1. Create a Telegram Bot

1. Open Telegram and search for `@BotFather`
2. Start a chat and send `/newbot`
3. Follow the prompts:
   - Choose a name for your bot (e.g., "AutoScalper Alerts")
   - Choose a username (must end in `bot`, e.g., "autoscalper_alerts_bot")
4. **Save the bot token** - it looks like: `123456789:ABCdefGHIjklMNOpqrsTUVwxyz`

### 2. Get Your Chat ID

**Option A: Use @userinfobot (Easiest)**

1. Search for `@userinfobot` in Telegram
2. Start a chat and send any message
3. The bot will reply with your user info, including your **Chat ID**
4. Save this number (e.g., `123456789`)

**Option B: Use the API**

1. Start a chat with your bot (the one you created with @BotFather)
2. Send any message to it (e.g., "hello")
3. Open this URL in your browser (replace `YOUR_BOT_TOKEN`):
   ```
   https://api.telegram.org/botYOUR_BOT_TOKEN/getUpdates
   ```
4. Look for `"chat":{"id":123456789}` in the response
5. Save that number

### 3. Configure AutoScalper

Edit your `.env` file:

```bash
# Telegram Notifications
TELEGRAM_ENABLED=true
TELEGRAM_BOT_TOKEN=123456789:ABCdefGHIjklMNOpqrsTUVwxyz
TELEGRAM_CHAT_ID=123456789
```

**Configuration Options:**

- `TELEGRAM_ENABLED` - Set to `true` to enable notifications
- `TELEGRAM_BOT_TOKEN` - Your bot token from @BotFather
- `TELEGRAM_CHAT_ID` - Your Telegram chat ID

**Daily Summary Time:**

The daily summary is automatically sent after trading hours close, using your `TRADING_HOURS_END` setting (default: `20:00` UTC = 4:00 PM ET)

### 4. Install Dependencies

If you haven't already:

```bash
cd /opt/autoscalper  # or your local directory
source venv/bin/activate
pip install -r requirements.txt
```

This will install `aiohttp` which is needed for Telegram API calls.

### 5. Test It

Restart your bot:

```bash
# If running locally
python -m src.orchestrator.main

# If running on server with systemd
systemctl restart autoscalper.service
```

You should see:

```
Telegram notifications enabled
Daily summary will be sent at 00:00 UTC
```

Then trigger a test trade (send a Discord message or wait for a real signal).

## Notification Examples

### Order Submitted

```
📝 PAPER ORDER SUBMITTED

Action: NEW
Symbol: SPY 685C
Expiry: 2025-12-15
Quantity: 1 contracts
Entry: $0.51
Stop: $0.38
Targets: $0.89

Session: abc123...
Time: 14:30:45 UTC
```

### Order Filled

```
✅ 📝 PAPER ORDER FILLED

Action: NEW
Symbol: SPY 685C
Order ID: 12345
Fill Price: $0.51

Entry filled at $0.51 | Bracket active: Stop=$0.38 Target=$0.89

Session: abc123...
Time: 14:30:52 UTC
```

### Order Rejected

```
❌ 🔴 LIVE ORDER REJECTED

Action: NEW
Symbol: SPX 6850P
Order ID: 12346

Contract not found: SPX 6850P (tried expiries: 2025-12-15, 20251215)

Session: def456...
Time: 15:20:10 UTC
```

### Daily Summary

```
📊 DAILY TRADING SUMMARY
Date: 2025-12-15

📈 Sessions
• Total: 5
• Closed: 3
• Open: 2

📋 Activity
• Orders Submitted: 8
• Orders Filled: 7

🔒 Closed Positions
• SPY 685C - 2 events
• SPX 6800P - 3 events
• SPY 690C - 2 events

🔓 Open Positions
• SPY 695C - 1 contracts
• SPX 6825P - 1 contracts

Summary generated at 00:00:15 UTC
```

## Customization

### Change Daily Summary Time

The daily summary uses `TRADING_HOURS_END` from your `.env`:

```bash
# Send summary at market close (4:00 PM ET = 20:00 UTC)
TRADING_HOURS_END=20:00

# Send summary at 5:00 PM ET (22:00 UTC)
TRADING_HOURS_END=22:00

# Send summary at 8:00 PM ET (01:00 UTC next day)
TRADING_HOURS_END=01:00
```

**Note:** Time is in UTC, not your local timezone.

**Conversion (EST/EDT to UTC):**
- 4:00 PM ET (market close) = 20:00 UTC (same day) or 21:00 UTC (DST)
- 5:00 PM ET = 22:00 UTC (same day) or 21:00 UTC (DST)
- 8:00 PM ET = 01:00 UTC (next day) or 00:00 UTC (DST)

### Disable Notifications

Set in `.env`:

```bash
TELEGRAM_ENABLED=false
```

Or remove the Telegram configuration entirely - the bot will work fine without it.

## Troubleshooting

### Not receiving notifications

1. **Check bot is enabled:**
   ```bash
   # Look for this in bot output
   Telegram notifications enabled
   ```

2. **Verify bot token and chat ID:**
   ```bash
   # Test manually with curl
   curl -X POST "https://api.telegram.org/bot<YOUR_BOT_TOKEN>/sendMessage" \
     -d "chat_id=<YOUR_CHAT_ID>" \
     -d "text=Test from AutoScalper"
   ```

3. **Check you started a chat with your bot:**
   - Open Telegram
   - Search for your bot's username
   - Click "Start" or send a message

4. **Check logs for errors:**
   ```bash
   # Look for Telegram errors
   grep "Telegram" logs/$(date +%Y-%m-%d)/*.log
   ```

### Getting "Forbidden: bot was blocked by the user"

You blocked the bot. Unblock it:
1. Open Telegram
2. Search for your bot
3. Click "Unblock" or "Restart"

### Getting "Bad Request: chat not found"

Your chat ID is wrong. Double-check it using @userinfobot or the API method above.

### Daily summary not sending

1. Check the time setting matches UTC
2. Wait for the scheduled time
3. Check logs: `grep "daily summary" logs/YYYY-MM-DD/*.log`

## Privacy & Security

### Is this secure?

- Bot token is stored in `.env` (not committed to git)
- Bot can only send messages to your chat ID
- No one else can use your bot without the token
- Messages are sent over HTTPS

### Best practices:

1. **Never share your bot token**
2. **Keep `.env` file secure** (already in .gitignore)
3. **Use a unique bot** for each trading system
4. **Regenerate token if compromised:**
   - Message @BotFather
   - Send `/mybots`
   - Select your bot → "API Token" → "Revoke current token"

## Advanced: Multiple Recipients

To send alerts to multiple people/groups:

1. Create a Telegram group
2. Add your bot to the group
3. Make the bot an admin (optional, but recommended)
4. Get the group chat ID (it will be negative, like `-987654321`)
5. Use the group ID as `TELEGRAM_CHAT_ID`

Now everyone in the group gets the alerts!

## Cost

Telegram Bot API is **100% free**. No limits on messages.

---

**Once configured, you'll get instant notifications for every trade - perfect for monitoring your bot remotely!**
