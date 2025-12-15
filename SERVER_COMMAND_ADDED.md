# ✅ Added `/server` Command

## What Was Added

New Telegram command for comprehensive system health monitoring!

**Command:** `/server`

**Shows:**
- 🤖 Bot running status & uptime
- 🏦 IBKR connection health & account balance
- 💬 Discord listener status
- 📊 Session statistics (open/closed)
- 💻 System resources (CPU, Memory, Disk)
- 🖥️ System info (OS, Python version)
- 🛡️ Risk gate status & daily P&L
- 📱 Telegram bot status

---

## Example Response

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

---

## Status Indicators

### Health Emojis
- ✅ **Green** - Healthy, Normal operation
- ⚠️ **Yellow** - Warning, Attention needed
- 🔴 **Red** - Critical, Action required
- ⏸️ **Gray** - Paused/Disabled

### Resource Thresholds

**CPU:**
- ✅ < 50% - Healthy
- ⚠️ 50-80% - Warning
- 🔴 > 80% - Critical

**Memory:**
- ✅ < 70% - Healthy
- ⚠️ 70-90% - Warning
- 🔴 > 90% - Critical

**Disk:**
- ✅ < 70% - Healthy
- ⚠️ 70-90% - Warning
- 🔴 > 90% - Critical

---

## Files Modified

### 1. `src/orchestrator/main.py`
- Added `start_time` tracking for uptime
- Added `_handle_server_command()` method
- Registered "server" command handler

**Lines added:** ~155 lines

### 2. `src/notifications/telegram_notifier.py`
- Updated unknown command message to show /server

### 3. `requirements.txt`
- Added `psutil>=5.9.0` for system monitoring

### 4. `TELEGRAM_COMMANDS.md`
- Added full documentation for /server command

---

## Dependencies

### New Dependency: `psutil`

Used for system resource monitoring (CPU, memory, disk).

**Install on server:**
```bash
pip install psutil>=5.9.0
```

**Or update from requirements:**
```bash
pip install -r requirements.txt
```

**Note:** Command gracefully degrades if psutil not available:
```
💻 System Resources
• Status: ⚠️ Not available (install psutil)
```

---

## Use Cases

### Daily Health Check
```
9:00 AM - /server (morning health check)
```
Verify everything is running before market open.

### Troubleshooting
```
Problem: Orders not executing
Action: /server
Check: IBKR connection status
```

### Resource Monitoring
```
/server
Check: CPU/Memory usage
Alert if > 80%
```

### Uptime Tracking
```
/server
Check: How long bot has been running
Verify no unexpected restarts
```

### Kill Switch Check
```
/server
Check: Risk gate status
Verify kill switch not accidentally active
```

---

## Deployment

### 1. Install Dependencies
```bash
ssh root@auto-scalper
cd /opt/autoscalper
pip install psutil>=5.9.0
```

### 2. Update Code
```bash
# From local machine
cd /Users/hanyuyang/Documents/Python/AutoScalper
rsync -av src/ root@auto-scalper:/opt/autoscalper/src/
rsync requirements.txt root@auto-scalper:/opt/autoscalper/
```

### 3. Restart Bot
```bash
ssh root@auto-scalper "sudo systemctl restart autoscalper"
```

### 4. Test Command
```
# In your Telegram group
/server
```

Should respond within 5-10 seconds with full health report!

---

## Available Commands

Now you have **two commands:**

| Command | Purpose | Response Time |
|---------|---------|---------------|
| `/status` 📊 | Check positions & P&L | 5-10 seconds |
| `/server` 🖥️ | Check bot & system health | 5-10 seconds |

---

## Monitoring Checklist

Use `/server` to check:
- [ ] Bot is running
- [ ] IBKR is connected
- [ ] Discord listener is active
- [ ] No open sessions stuck
- [ ] CPU/Memory not overloaded
- [ ] Disk space available
- [ ] Kill switch not active
- [ ] Telegram bot working

**All green ✅** = System healthy!

---

## Error Handling

### If Command Fails
```
❌ Error getting server health: [error message]
```

**Common causes:**
1. Bot just restarted (uptime not set)
2. psutil import error
3. IBKR connection check timeout

**Solution:** Try again in 10 seconds

### If psutil Missing
```
💻 System Resources
• Status: ⚠️ Not available (install psutil)
```

**Solution:**
```bash
ssh root@auto-scalper
pip install psutil
sudo systemctl restart autoscalper
```

---

## Future Enhancements

Potential additions to `/server`:
- Network latency to IBKR
- Last message received from Discord
- Error log summary
- Recent trade count
- WebSocket connection status
- Last successful heartbeat time

**Feedback welcome!**

---

## Summary

✅ Added comprehensive `/server` health monitoring
✅ Shows bot, IBKR, Discord, system status
✅ Color-coded health indicators (✅⚠️🔴)
✅ System resource monitoring (CPU/Memory/Disk)
✅ Uptime tracking
✅ Risk gate and P&L status
✅ Works in paper and live mode
✅ Responds in 5-10 seconds

**Try it:** Send `/server` to your Telegram bot! 🚀
