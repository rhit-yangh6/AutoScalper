# Telegram Notifications Feature

## Summary

Added real-time Telegram notifications for all trading activity.

## New Files

1. **src/notifications/telegram_notifier.py** - Telegram notification module
2. **src/notifications/__init__.py** - Module exports
3. **TELEGRAM_SETUP.md** - Complete setup guide

## Updated Files

1. **src/orchestrator/main.py**
   - Integrated TelegramNotifier
   - Sends notifications on order submission
   - Sends notifications on order fills/rejections
   - Background task for daily summary

2. **requirements.txt**
   - Added `aiohttp>=3.9.0` for Telegram API

3. **.env.example**
   - Added Telegram configuration section

## Features

### ✅ Order Submission Notifications

When any order is submitted to IBKR:
- Event type (NEW, ADD, EXIT, etc.)
- Symbol and strike
- Quantity
- Entry price
- Stop loss
- Targets
- Paper vs Live mode indicator

### ✅ Order Fill Notifications

When any order is filled (or rejected/cancelled):
- Fill status (✅ FILLED, ❌ REJECTED, ⚠️ CANCELLED)
- Order ID
- Fill price
- Error message (if rejected)
- Paper vs Live mode indicator

### ✅ Daily Summary

Sent automatically after trading hours close (uses `TRADING_HOURS_END` - default: 20:00 UTC = 4:00 PM ET):
- Total sessions (open + closed)
- Total orders submitted
- Total orders filled
- List of closed positions
- List of open positions

## Configuration

Add to `.env`:

```bash
TELEGRAM_ENABLED=true
TELEGRAM_BOT_TOKEN=your_bot_token_here
TELEGRAM_CHAT_ID=your_chat_id_here
# Daily summary uses TRADING_HOURS_END (default: 20:00 UTC)
```

## Setup

1. Create Telegram bot with @BotFather
2. Get your chat ID from @userinfobot
3. Add config to `.env`
4. Install dependencies: `pip install -r requirements.txt`
5. Restart bot

See **TELEGRAM_SETUP.md** for detailed instructions.

## Example Notifications

### Paper Mode - Order Submitted
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

### Live Mode - Order Filled
```
✅ 🔴 LIVE ORDER FILLED

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

Contract not found: SPX 6850P (tried expiries: 2025-12-15, 20251215)

Session: def456...
Time: 15:20:10 UTC
```

## Technical Details

### Async HTTP Calls

Uses `aiohttp` for non-blocking Telegram API calls:
- Won't slow down trading execution
- Timeout after 10 seconds
- Errors are logged but don't crash the bot

### Daily Summary Scheduler

Background task that:
- Calculates time until next summary
- Sleeps until that time
- Sends summary
- Resets for next day

### Error Handling

If Telegram is unavailable:
- Logs warning to console
- Continues trading normally
- Doesn't block order execution

### HTML Formatting

Messages use Telegram's HTML format:
- `<b>bold</b>` for important info
- `<i>italic</i>` for metadata
- Emojis for visual status indicators

## Benefits

1. **Real-time monitoring** - No need to check logs
2. **Mobile alerts** - Get notifications on your phone
3. **Remote monitoring** - Monitor bot from anywhere
4. **Quick debugging** - See errors immediately
5. **Daily accountability** - Review performance every day

## Optional Configuration

### Disable Notifications

```bash
TELEGRAM_ENABLED=false
```

### Change Summary Time

Daily summary uses `TRADING_HOURS_END`:

```bash
# Send at market close: 4 PM ET (20:00 UTC)
TRADING_HOURS_END=20:00

# Send later: 8 PM ET (01:00 UTC next day)
TRADING_HOURS_END=01:00
```

### Send to Group

1. Create Telegram group
2. Add your bot
3. Get group chat ID (negative number)
4. Use as `TELEGRAM_CHAT_ID`

## Privacy

- Bot token stored in `.env` (not in git)
- Only sends to your chat ID
- Sent over HTTPS
- No data stored by Telegram bot

## Next Steps

1. Follow **TELEGRAM_SETUP.md** to configure
2. Restart bot to enable notifications
3. Test with a Discord message
4. Wait for daily summary at configured time

---

**Stay informed about every trade - even when you're away from your computer!**
