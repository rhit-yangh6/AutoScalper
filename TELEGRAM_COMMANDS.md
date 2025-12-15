# Telegram Commands Guide

## Overview

Your AutoScalper bot now supports **interactive commands** via Telegram! Send commands to get instant status updates without SSH or scripts.

---

## Available Commands

### 📊 `/status` - Check Current Positions

Get instant snapshot of your trading status.

**Usage:**
```
/status
```

**Response Example:**
```
📊 🔴 LIVE STATUS

💰 Account Balance: $10,523.45

🔓 Open Positions (2):
• SPY 677.0P: 1 @ $1.00 📈 +0.30 (+30.0%)
• SPX 5950C: 2 @ $2.50 📉 -0.50 (-10.0%)

📋 Open Orders (1):
• BUY 1 SPY 680P @ $1.20 - Submitted

🔄 Active Sessions (2):
• SPY 677.0P - 1 contracts
• SPX 5950C - 2 contracts

Updated: 16:30:15 UTC
```

**What It Shows:**
- 💰 Current account balance
- 🔓 All open positions with P&L
- 📋 Pending orders
- 🔄 Active trading sessions
- ⏰ Last update time

**When to Use:**
- Quick position check from your phone
- Verify entry filled
- Check unrealized P&L
- Monitor pending orders

---

### 🖥️ `/server` - Check Bot & IBKR Health

Get comprehensive health check of the entire system.

**Usage:**
```
/server
```

**Response Example:**
```
🖥️ 🔴 LIVE SERVER HEALTH

🤖 Bot Status
• Status: ✅ Running
• Uptime: ⏱️ 5h 32m
• Mode: 🔴 LIVE

🏦 IBKR Connection
• Status: ✅ Connected
• Host: 127.0.0.1
• Port: 4001
• Account: 💰 $10,523.45

💬 Discord Listener
• Status: ✅ Running
• Channels: 2
• Users: All

📊 Session Manager
• Total Sessions: 12
• Open: 🟢 2
• Closed: ⚪ 10

💻 System Resources
• CPU: ✅ 15.3%
• Memory: ✅ 42.8% (1.7GB / 4.0GB)
• Disk: ✅ 35.2% (14.1GB / 40.0GB)

🖥️ System Info
• OS: Linux 5.15.0
• Python: 3.11.5

🛡️ Risk Gate
• Kill Switch: ✅ Inactive
• Daily P&L: $125.50
• Loss Streak: 0

📱 Telegram Bot
• Status: ✅ Enabled
• Chat ID: -5031664746

🕐 Updated: 16:30:15 UTC
```

**What It Shows:**
- 🤖 Bot running status & uptime
- 🏦 IBKR connection & account balance
- 💬 Discord listener health
- 📊 Session statistics
- 💻 CPU, Memory, Disk usage
- 🛡️ Risk gate status & P&L
- 📱 Telegram bot status
- 🖥️ System information

**When to Use:**
- Daily health check
- Troubleshoot connection issues
- Monitor system resources
- Verify bot is running correctly
- Check if IBKR is connected

**Status Indicators:**
- ✅ Green = Healthy/Normal
- ⚠️ Yellow = Warning
- 🔴 Red = Critical/Error
- ⏸️ Paused/Disabled

---

## How Commands Work

### Polling System
- Bot checks for new commands every **5 seconds**
- Responds within 5-10 seconds of sending
- No webhooks needed, works anywhere

### Security
- **Only your chat ID** can send commands
- Set in `.env`: `TELEGRAM_CHAT_ID=-5031664746`
- Other users get no response

### Response Time
```
You send: /status
↓ (5-10 seconds)
Bot responds: [Status message]
```

---

## Command Behavior by Mode

### Paper Mode (`PAPER_MODE=true`)
```
📊 📝 PAPER STATUS

💰 Account Balance: Not available

🔓 Open Positions (0):
  No open positions

📋 Open Orders (0):
  No open orders

🔄 Active Sessions (1):
• SPY 677.0P - 1 contracts

Updated: 16:30:15 UTC
```

**Note:** In paper mode, IBKR isn't connected, so positions/orders show as empty. Sessions are still tracked.

### Live Mode (`PAPER_MODE=false`)
```
📊 🔴 LIVE STATUS

💰 Account Balance: $10,523.45
[Full position and order details...]
```

**Real-time data from IBKR.**

---

## Understanding the Status Output

### Position P&L Format
```
• SPY 677.0P: 1 @ $1.00 📈 +0.30 (+30.0%)
  └── Symbol   Qty   Entry  Direction  P&L $  P&L %
```

**Emojis:**
- 📈 Green = Profit
- 📉 Red = Loss

**Calculation:**
- Entry: $1.00
- Current value: $1.30
- P&L: +$0.30 (+30%)

### Order Status
```
• BUY 1 SPY 680P @ $1.20 - Submitted
  └── Action Qty Symbol Price  Status
```

**Common Statuses:**
- `Submitted` - Order sent to IBKR
- `PreSubmitted` - IBKR received, not yet active
- `Filled` - Order completed (usually won't show as "open")
- `Cancelled` - Order cancelled (won't show in status)

### Active Sessions
Shows internal session tracking:
```
• SPY 677.0P - 1 contracts
```

Sessions track entire trade lifecycle, even if IBKR position closed.

---

## Troubleshooting

### Command Not Responding

**Problem:** Send `/status`, no response after 30 seconds

**Solutions:**
1. **Check bot is running:**
   ```bash
   ssh root@auto-scalper
   sudo systemctl status autoscalper
   # Should show "active (running)"
   ```

2. **Check logs for errors:**
   ```bash
   sudo journalctl -u autoscalper -f | grep -i telegram
   ```

3. **Verify Telegram config:**
   ```bash
   cat /opt/autoscalper/.env | grep TELEGRAM
   # Verify TELEGRAM_ENABLED=true
   # Verify bot token and chat ID present
   ```

4. **Restart bot:**
   ```bash
   sudo systemctl restart autoscalper
   # Wait 10 seconds, try /status again
   ```

---

### Getting "Unknown command" Error

**Response:**
```
❓ Unknown command: /help

Available commands:
/status - Check positions and account
```

**Reason:** Only `/status` is implemented currently.

**Note:** `/help` and other commands may be added in future updates.

---

### Getting Error Response

**Response:**
```
❌ Error executing /status: This event loop is already running
```

**Reason:** Internal error, usually temporary.

**Fix:**
1. Try again in 10 seconds
2. If persists, restart bot:
   ```bash
   sudo systemctl restart autoscalper
   ```

---

## Advanced Usage

### Checking Status After Discord Alert

**Workflow:**
```
1. Discord: "NEW SPY 677P @ $1.00"
   ↓
2. Bot processes trade
   ↓
3. Telegram: Order submitted notification
   ↓
4. You send: /status
   ↓
5. Bot replies: Position confirmed, shows P&L
```

**Use case:** Verify trade execution without opening TWS.

---

### Monitoring During Trading Hours

Set reminders to check status:
```
9:30 AM  - /status (check open positions)
12:00 PM - /status (check P&L at midday)
3:00 PM  - /status (pre-close check)
4:00 PM  - End-of-day summary (automatic)
```

---

### Quick P&L Check

Use `/status` for instant P&L without calculating:
```
📈 +0.30 (+30.0%)  ← Winning trade, let it run
📉 -0.40 (-40.0%)  ← Near stop, watch closely
```

---

## Future Commands (Coming Soon)

**Potential additions:**
- `/close <symbol>` - Close specific position
- `/cancel <order_id>` - Cancel pending order
- `/summary` - Today's P&L summary
- `/sessions` - Detailed session info
- `/help` - Command list with descriptions

**Feedback welcome!** Let me know what commands would be useful.

---

## Technical Details

### How It Works

**Architecture:**
1. `TelegramNotifier` polls Telegram API every 5 seconds
2. Detects messages starting with `/`
3. Matches command to registered handler
4. Handler queries `ExecutionEngine` for live data
5. Formats response and sends back

**Code location:**
- Command polling: `src/notifications/telegram_notifier.py`
- Status handler: `src/orchestrator/main.py:_handle_status_command()`

### Latency

**Typical response time:**
- Paper mode: 5-10 seconds (no IBKR queries)
- Live mode: 5-15 seconds (includes IBKR API calls)

**Why not instant?**
- Polling every 5 seconds (trade-off for simplicity)
- IBKR API queries take 1-2 seconds
- Could be optimized with webhooks in future

---

## Privacy & Security

### What's Logged
Command usage is logged locally:
```
Telegram command polling active (send /status to check positions)
Processing command: /status from chat -5031664746
✓ Status command executed
```

### Who Can Use Commands
**Only you!**
- Commands filtered by `TELEGRAM_CHAT_ID`
- Other users' messages ignored
- No response to unauthorized requests

### Data Transmission
- All communication over HTTPS
- Telegram Bot API (official)
- No third-party services

---

## Summary

✅ **Two commands available:**
- 📊 `/status` - Check positions and P&L
- 🖥️ `/server` - Check bot and IBKR health

✅ **Shows real-time data** from IBKR and system
✅ **5-10 second response time** via polling
✅ **Secure** - only works for your chat ID
✅ **Works in paper and live mode**
✅ **Full system monitoring** - CPU, memory, disk, uptime

**Try them now:**
- Send `/status` to check your positions
- Send `/server` to check bot health
