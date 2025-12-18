# AutoScalper - 0DTE Options Trading Bot

Automated trading bot that parses Discord trading alerts and executes 0DTE SPY/QQQ options trades via Interactive Brokers.

## Quick Start

### Start the Bot
```bash
screen -dmS bot /opt/autoscalper/start_bot.sh
```

### Attach to Running Bot
```bash
screen -r bot
```

### Detach from Screen (Keep Bot Running)
Press `Ctrl+A` then `D`

### Stop the Bot
```bash
screen -r bot
# Then press Ctrl+C
```

---

## Trading Modes

The bot supports three modes for testing and trading:

| Mode | Description | IBKR Connection | Order Execution | Use Case |
|------|-------------|-----------------|-----------------|----------|
| **1. Dry-Run** | No IBKR connection | ❌ None | Simulated | Test Discord parsing |
| **2. IBKR Paper** | IBKR paper account | ✅ Port 4002 | Market orders | Test with fake money |
| **3. IBKR Live** | IBKR live account | ✅ Port 4001 | Limit orders (5¢) | Real trading |

---

## Mode 1: Dry-Run (Discord Parsing Only)

**Purpose:** Test Discord message parsing without connecting to IBKR.

### Configuration
Edit `.env`:
```bash
DRY_RUN=true
# IBKR_PORT is ignored in this mode
```

### What Happens
- ✅ Bot listens to Discord
- ✅ Parses messages with Claude API
- ✅ Logs trades to `logs/`
- ❌ Does NOT connect to IBKR
- ❌ Does NOT execute orders

### Expected Output
```
Mode: PAPER TRADING
IBKR Connection: ⏸️ Disconnected (Paper Mode)

[PAPER MODE] Would execute:
  Event: NEW
  Quantity: 1
  Entry: $0.50
```

### When to Use
- Testing Discord token and channel setup
- Verifying LLM parsing accuracy
- Checking session correlation logic

---

## Mode 2: IBKR Paper Trading (Fake Money)

**Purpose:** Test actual order execution with IBKR's paper trading account.

### Prerequisites
1. **IBKR Paper Account** - Separate from live account
2. **IB Gateway running in Docker**

### Start IB Gateway (Docker)
```bash
docker-compose up -d
```

Check status:
```bash
docker ps
# Should see: ib-gateway container running
```

Access VNC (for manual login if needed):
```
http://localhost:5900
```

### Configuration
Edit `.env`:
```bash
DRY_RUN=false
IBKR_HOST=127.0.0.1
IBKR_PORT=4002          # Paper trading port
IBKR_CLIENT_ID=1
```

### What Happens
- ✅ Connects to IBKR paper account
- ✅ Executes MARKET orders (delayed data, no subscription needed)
- ✅ Tracks positions in fake money account
- ✅ Creates OCO brackets (stop-loss + take-profit)
- ✅ Sends Telegram notifications (if enabled)

### Expected Output
```
Mode: LIVE TRADING
Connected to IBKR at 127.0.0.1:4002
📊 Order Strategy: MARKET orders (delayed data)

✓ Qualified contract: SPY   251217C00682000
ⓘ MARKET order submitted for 1 contracts
✓ Entry filled at $0.57
✓ Stop order created: $0.43 (Order #123)
✓ Target order created: $0.85 (Order #124)
```

### When to Use
- Testing full order flow with fake money
- Verifying bracket order creation
- Testing position reconciliation
- Practice before going live

---

## Mode 3: IBKR Live Trading (Real Money)

**Purpose:** Execute real trades with real money.

⚠️ **WARNING: This mode uses REAL MONEY. Only proceed if you've thoroughly tested in paper mode.**

### Prerequisites
1. **IBKR Live Account** - Funded account
2. **Real-time market data subscription** (required for limit orders)
3. **IB Gateway configured for live trading**

### Start IB Gateway (Docker - Live)
Edit `docker-compose.yml`:
```yaml
services:
  ib-gateway:
    environment:
      - TRADING_MODE=live         # Change from 'paper' to 'live'
      - IBEAM_ACCOUNT=YOUR_LIVE_USERNAME
      - IBEAM_PASSWORD=YOUR_LIVE_PASSWORD
    ports:
      - "127.0.0.1:4001:4003"      # Live port mapping
```

Then:
```bash
docker-compose down
docker-compose up -d
```

### Configuration
Edit `.env`:
```bash
DRY_RUN=false
IBKR_HOST=127.0.0.1
IBKR_PORT=4001          # Live trading port
IBKR_CLIENT_ID=1

# Risk management
ACCOUNT_BALANCE=10000
MAX_CONTRACTS=1
RISK_PER_TRADE_PERCENT=0.5
```

### What Happens
- ✅ Connects to IBKR live account
- ✅ Executes LIMIT orders with 5¢ flexibility (uses real-time data)
- ✅ Tracks positions in real account
- ✅ Creates OCO brackets
- ✅ Auto-closes positions at 4:00 PM ET
- ✅ Sends critical alerts via Telegram

### Expected Output
```
Mode: LIVE TRADING
Connected to IBKR at 127.0.0.1:4001
📊 Order Strategy: LIMIT orders with 5¢ flexibility (real-time data)

✓ Qualified contract: SPY   251217C00682000
Fetching current market data...
📊 Market: Bid $0.55 | Ask $0.58 | Last $0.57
ⓘ Adjusting entry: $0.50 → $0.58 (market moved, within 5¢)
ⓘ LIMIT order submitted @ $0.58
✓ Entry filled at $0.58
✓ Stop order created: $0.44 (Order #123)
✓ Target order created: $0.86 (Order #124)
```

### When to Use
- After thorough testing in paper mode
- When ready to trade with real money

---

## Switching Between Modes

### Dry-Run → IBKR Paper
1. Edit `.env`:
   ```bash
   DRY_RUN=false  # Changed from true
   IBKR_PORT=4002
   ```
2. Start IB Gateway: `docker-compose up -d`
3. Restart bot: `screen -r bot` → Ctrl+C → `/opt/autoscalper/start_bot.sh`

### IBKR Paper → IBKR Live
1. Edit `docker-compose.yml`:
   ```yaml
   TRADING_MODE=live  # Changed from paper
   ```
   Change ports: `4001:4003` (changed from `4002:4004`)

2. Edit `.env`:
   ```bash
   IBKR_PORT=4001  # Changed from 4002
   ```

3. Restart IB Gateway:
   ```bash
   docker-compose down
   docker-compose up -d
   ```

4. Restart bot: `screen -r bot` → Ctrl+C → `/opt/autoscalper/start_bot.sh`

### IBKR Live → IBKR Paper (Emergency Revert)
1. Edit `.env`:
   ```bash
   IBKR_PORT=4002  # Changed from 4001
   ```

2. Edit `docker-compose.yml`:
   ```yaml
   TRADING_MODE=paper  # Changed from live
   ```
   Change ports: `4002:4004`

3. Restart:
   ```bash
   docker-compose down
   docker-compose up -d
   screen -r bot  # Ctrl+C then restart
   ```

---

## Configuration Reference

### Required Environment Variables (.env)

```bash
# Mode Selection
DRY_RUN=false           # true = dry-run (no IBKR), false = IBKR trading

# IBKR Connection
IBKR_HOST=127.0.0.1
IBKR_PORT=4002            # 4002 = paper, 4001 = live
IBKR_CLIENT_ID=1

# Discord
DISCORD_USER_TOKEN=your_discord_token
DISCORD_CHANNEL_IDS=123456789,987654321

# Claude API
ANTHROPIC_API_KEY=sk-ant-...

# Risk Management
ACCOUNT_BALANCE=10000
RISK_PER_TRADE_PERCENT=0.5
MAX_CONTRACTS=1
MAX_LOSS_STREAK=3
DAILY_MAX_LOSS_PERCENT=2.0

# Trading Hours (UTC)
TRADING_HOURS_START=13:30  # 9:30 AM ET
TRADING_HOURS_END=20:00    # 4:00 PM ET

# Telegram (Optional)
TELEGRAM_ENABLED=true
TELEGRAM_BOT_TOKEN=your_bot_token
TELEGRAM_CHAT_ID=your_chat_id
```

---

## Order Strategy by Mode

| Operation | Dry-Run | IBKR Paper | IBKR Live |
|-----------|---------|------------|-----------|
| Entry (NEW) | Simulated | Market | Limit (5¢) |
| Add (ADD) | Simulated | Market | Limit (5¢) |
| Exit (EXIT) | Simulated | Market | Market |
| Trim (TRIM) | Simulated | Market | Market |
| Stop-Loss | N/A | Limit | Limit |
| Take-Profit | N/A | Limit | Limit |

**Why different strategies?**
- **Paper mode:** Uses market orders because delayed data (15-min) makes limit orders unreliable
- **Live mode:** Uses limit orders with 5¢ flexibility to control entry price with real-time data

---

## Monitoring

### View Logs
```bash
tail -f logs/trading_bot.log
```

### Check Today's Trades
```bash
ls logs/$(date +%Y-%m-%d)/
cat logs/$(date +%Y-%m-%d)/session_*.json
```

### View IB Gateway Logs
```bash
docker logs ib-gateway
```

### Telegram Commands (If Enabled)
- `/status` - Bot status and positions
- `/balance` - Account balance
- `/sessions` - Active sessions

---

## Troubleshooting

### Bot Won't Connect to IBKR
```bash
# Check IB Gateway is running
docker ps

# Check Gateway logs
docker logs ib-gateway

# Verify .env port matches Gateway mode
# Paper: IBKR_PORT=4002
# Live:  IBKR_PORT=4001
```

### Orders Timing Out (Paper Mode)
This is normal - paper mode uses market orders which always fill. If you see timeouts, check:
```bash
# Verify connection
docker logs ib-gateway | grep -i error

# Check bot is in right mode
grep IBKR_PORT .env
```

### Positions Not Closing at EOD
Check trading hours configuration:
```bash
grep TRADING_HOURS_END .env
# Should be: TRADING_HOURS_END=20:00 (4:00 PM ET in UTC)
```

### Discord Not Working
```bash
# Verify token
grep DISCORD_USER_TOKEN .env

# Check channel IDs
grep DISCORD_CHANNEL_IDS .env

# View Discord connection logs
tail -f logs/trading_bot.log | grep -i discord
```

---

## Safety Features

✅ **Kill switch** - Emergency stop if account drops below threshold
✅ **Position reconciliation** - Syncs bot state with IBKR every 60s
✅ **EOD auto-close** - Closes all positions at market close
✅ **Risk limits** - Max contracts, daily loss, loss streak
✅ **Emergency exit** - If brackets fail, immediately closes position
✅ **Validation** - Rejects incomplete or low-confidence trades

---

## Support

For issues or questions, check:
- Bot logs: `logs/trading_bot.log`
- Session files: `logs/YYYY-MM-DD/session_*.json`
- IB Gateway logs: `docker logs ib-gateway`
