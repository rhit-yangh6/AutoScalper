# IB Gateway Docker - Quick Start Guide

This guide gets you up and running with IB Gateway in Docker in 5 minutes.

## What This Gives You

- ✅ **Auto-login on restarts** - No manual login required
- ✅ **Auto-restart on crashes** - Gateway automatically recovers
- ✅ **Isolated environment** - Runs in container, no system conflicts
- ✅ **Persistent settings** - Configuration saved across restarts
- ✅ **Works with bot's auto-reconnection** - Full resilience

## Prerequisites

1. Docker Desktop installed and running
2. Interactive Brokers account (paper or live)
3. API access enabled in your IB account

## Setup (5 minutes)

### Step 1: Configure Credentials

```bash
# Copy example config
cp .env.example .env

# Edit and add your IB credentials
nano .env
```

Add these lines (scroll to IB section):
```
IB_USERNAME=your_ib_username
IB_PASSWORD=your_ib_password
```

**Security Note**: The `.env` file is in `.gitignore` and won't be committed to git.

### Step 2: Start IB Gateway

```bash
# Run the startup script
./start-docker.sh

# OR manually:
docker-compose up -d ibgateway
```

**First startup takes 60-90 seconds** while Gateway initializes and auto-logins.

### Step 3: Verify Connection

```bash
# Check if Gateway is accepting connections
nc -zv localhost 4002

# Should output: Connection to localhost port 4002 [tcp/*] succeeded!
```

### Step 4: Start Your Bot

```bash
# Your bot will automatically connect to Gateway
python -m src.orchestrator.main
```

The bot's auto-reconnection logic will handle any connection issues.

## Daily Usage

### Start Everything
```bash
docker-compose up -d ibgateway
python -m src.orchestrator.main
```

### View Logs
```bash
# Gateway logs
docker-compose logs -f ibgateway

# Bot logs (in separate terminal)
# Your bot outputs to console
```

### Stop Everything
```bash
# Stop Gateway
docker-compose stop ibgateway

# Stop bot
# Ctrl+C in bot's terminal
```

### Restart Gateway (if needed)
```bash
docker-compose restart ibgateway
# Bot will auto-reconnect after ~30 seconds
```

## Configuration Reference

### Port Configuration

| Port | Purpose | Mode |
|------|---------|------|
| 4002 | API (Paper Trading) | Paper |
| 4001 | API (Live Trading) | Live |
| 5900 | VNC (Remote UI) | Both |

Your bot connects to:
- **Host**: `localhost` or `127.0.0.1`
- **Port**: `4002` (paper) or `4001` (live)

### Switch Paper ↔ Live

**docker-compose.yml**:
```yaml
environment:
  TRADING_MODE: paper  # Change to "live"
```

**.env** (bot config):
```bash
PAPER_MODE=false  # For live
IBKR_PORT=4001    # Live port
```

Restart Gateway:
```bash
docker-compose restart ibgateway
```

## Troubleshooting

### Gateway won't start

```bash
# View detailed logs
docker-compose logs ibgateway

# Common causes:
# 1. Wrong credentials → Check IB_USERNAME/IB_PASSWORD in .env
# 2. Account locked → Login to IB website first
# 3. 2FA timeout → Use IBKR Mobile app to approve
```

### Bot can't connect

```bash
# 1. Check Gateway is running
docker-compose ps
# Should show "Up (healthy)"

# 2. Test port
nc -zv localhost 4002

# 3. Check bot's .env
# IBKR_HOST=127.0.0.1
# IBKR_PORT=4002
```

### Gateway disconnects after some time

This shouldn't happen anymore with Docker auto-restart, but if it does:

```bash
# Check container status
docker-compose ps

# Check logs for errors
docker-compose logs ibgateway

# Force restart
docker-compose restart ibgateway
```

### View Gateway UI (debugging)

Connect via VNC:
```bash
# macOS
open vnc://localhost:5900

# Linux
vncviewer localhost:5900

# Password: value of VNC_PASSWORD from .env (default: ibgateway)
```

## Architecture

```
┌─────────────────────────────┐
│  Docker Container           │
│  ┌─────────────────────┐    │
│  │  IB Gateway         │    │
│  │  + IB Controller    │    │
│  │  (auto-login)       │    │
│  └─────────────────────┘    │
│  Port 4002 ←→ localhost     │
└─────────────────────────────┘
           ↑
           │ API Connection
           ↓
┌─────────────────────────────┐
│  AutoScalper Bot            │
│  (Your Python script)       │
│  - Auto-reconnection        │
│  - Bracket monitoring       │
│  - Telegram notifications   │
└─────────────────────────────┘
```

## How Auto-Restart Works

1. **Gateway crashes** → Docker restarts container → IBC auto-logins → Bot reconnects
2. **Network blip** → Bot's reconnection logic handles it automatically
3. **Host reboots** → Docker auto-starts Gateway → IBC auto-logins → Start bot manually
4. **Docker restarts** → Gateway auto-starts → IBC auto-logins → Bot reconnects

## Production Deployment (VPS/Server)

```bash
# 1. Install Docker
curl -fsSL https://get.docker.com | sh

# 2. Clone repo
git clone <your-repo>
cd AutoScalper

# 3. Configure
nano .env

# 4. Start Gateway
docker-compose up -d ibgateway

# 5. Start bot (in tmux/screen for persistence)
tmux new -s trading
python -m src.orchestrator.main
# Detach: Ctrl+B, then D

# 6. Check status anytime
tmux attach -t trading
docker-compose ps
```

## Useful Commands

```bash
# Status
docker-compose ps

# Logs (real-time)
docker-compose logs -f ibgateway

# Logs (last 50 lines)
docker-compose logs --tail=50 ibgateway

# Resource usage
docker stats ibgateway

# Restart
docker-compose restart ibgateway

# Stop
docker-compose stop ibgateway

# Full reset (removes container, keeps settings)
docker-compose down
docker-compose up -d ibgateway

# Update Gateway to latest version
docker-compose pull ibgateway
docker-compose up -d ibgateway
```

## Security Best Practices

1. ✅ Never commit `.env` to git (already in `.gitignore`)
2. ✅ Use paper trading for testing
3. ✅ Enable "Read-Only API" in IB if not trading manually
4. ✅ Whitelist your server IP in IB account settings
5. ✅ Use strong VNC password
6. ✅ Rotate credentials regularly

## Support

- **Full Documentation**: See `docker/README.md`
- **IB Gateway Image**: https://github.com/gnzsnz/ib-gateway-docker
- **IB Controller**: https://github.com/IbcAlpha/IBC
- **IBKR API**: https://interactivebrokers.github.io/tws-api/

## Next Steps

After setup:

1. ✅ Test with paper trading first
2. ✅ Monitor logs for first few trades
3. ✅ Set up Telegram notifications
4. ✅ Test auto-reconnection (restart Gateway while bot running)
5. ✅ Test bracket fill notifications (let stop loss or target hit)
6. ✅ Review daily summary after market close

---

**You're all set!** Gateway will auto-login on every restart, and your bot will automatically reconnect. 🚀
