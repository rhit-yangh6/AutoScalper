# AutoScalper Docker Deployment Guide

## Overview

This guide covers deploying AutoScalper with IBKR Gateway using Docker Compose, including automatic reconnection handling and supervised restarts.

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                    Docker Compose Stack                      │
├─────────────────────────────────────────────────────────────┤
│                                                               │
│  ┌──────────────────────┐      ┌──────────────────────┐     │
│  │   ib-gateway         │      │   autoscalper        │     │
│  │                      │      │                      │     │
│  │ IBKR Gateway API     │◄─────┤ Trading Bot          │     │
│  │ Port: 4001 (live)    │      │                      │     │
│  │       4002 (paper)   │      │ Auto-reconnect ✓     │     │
│  │                      │      │ State rebuild  ✓     │     │
│  │ Healthcheck:         │      │ Telegram alerts ✓    │     │
│  │   nc -z 4003         │      │                      │     │
│  │   interval: 10s      │      │ Depends on:          │     │
│  │   retries: 30        │      │   ib-gateway         │     │
│  │                      │      │   (service_healthy)  │     │
│  └──────────────────────┘      └──────────────────────┘     │
│           │                              │                   │
│           │ healthcheck pass             │ restarts on       │
│           └──────────────────────────────┘ unhealthy         │
│                                                               │
└─────────────────────────────────────────────────────────────┘
```

## Prerequisites

1. **Docker & Docker Compose**
   ```bash
   docker --version  # 20.10+
   docker compose version  # 2.0+
   ```

2. **IBKR Account**
   - Active Interactive Brokers account
   - IB Key for mobile authentication
   - API access enabled in account settings

3. **Environment Variables**
   - Copy `.env.example` to `.env`
   - Fill in all required credentials

## Environment Setup

Create `.env` file with:

```bash
# IBKR Credentials
IB_USERNAME=your_username
IB_PASSWORD=your_password
VNC_PASSWORD=change_me_vnc_password

# Trading Configuration
TRADING_MODE=live  # or "paper" for paper trading
IBKR_PORT=4001     # 4001 for live, 4002 for paper

# API Keys
ANTHROPIC_API_KEY=sk-ant-...
DISCORD_USER_TOKEN=...
DISCORD_CHANNEL_IDS=...

# Telegram Alerts
TELEGRAM_ENABLED=true
TELEGRAM_BOT_TOKEN=...
TELEGRAM_CHAT_ID=...

# Risk Parameters
ACCOUNT_BALANCE=10000
RISK_PER_TRADE_PERCENT=0.5
DAILY_MAX_LOSS_PERCENT=2.0
MAX_CONTRACTS=2
```

## Deployment

### 1. Start Services

```bash
# Start all services
docker compose up -d

# Check service status
docker compose ps

# Expected output:
# NAME           STATUS                    PORTS
# ib-gateway     Up (healthy)             127.0.0.1:4001->4003/tcp, ...
# autoscalper    Up
```

### 2. Monitor Logs

```bash
# Watch all logs
docker compose logs -f

# Watch specific service
docker compose logs -f autoscalper
docker compose logs -f ib-gateway
```

### 3. IB Key Approval

IBKR Gateway requires weekly IB Key approval:

1. You'll receive IB Key notification on your phone
2. Open IBKR Mobile app
3. Approve the authentication request
4. Gateway will connect automatically
5. Bot will auto-reconnect once gateway is healthy

**Expected Telegram alert:**
```
⚠️ WARNING: IBKR Gateway Disconnected

Reconnection attempts: 3
Estimated downtime: ~5 minutes

Status: Auto-reconnecting...

Possible causes:
• Gateway restarting (normal daily restart)
• Network interruption
• Gateway requires IB Key approval

No action needed - bot will auto-reconnect
```

## Runtime Behavior

### Normal Operation

1. **Gateway starts** → Healthcheck passes when API port (4003) is reachable
2. **Bot starts** → Only after gateway is marked healthy
3. **Trading begins** → Bot connects to gateway and starts monitoring Discord

### Gateway Restart Event

```
┌─────────────────────────────────────────────────────────┐
│ 1. Gateway restarts (daily reset or IB Key timeout)    │
│    └─> Healthcheck fails (port unreachable)            │
│                                                          │
│ 2. Bot detects disconnection                            │
│    └─> Auto-reconnect begins (infinite retries)        │
│                                                          │
│ 3. Gateway becomes healthy again                        │
│    └─> Healthcheck passes (port reachable)             │
│                                                          │
│ 4. Bot reconnects successfully                          │
│    └─> State rebuild: positions, orders, balance       │
│                                                          │
│ 5. Trading resumes automatically                        │
│    └─> Telegram notification sent                      │
└─────────────────────────────────────────────────────────┘
```

### Progressive Alerting

The bot sends Telegram alerts at these thresholds:

| Failures | Duration | Alert Level | Action Required |
|----------|----------|-------------|-----------------|
| 3        | ~5 min   | ⚠️ WARNING   | None (auto-reconnecting) |
| 10       | ~17 min  | 🔴 CRITICAL  | Check gateway logs, IB Key |
| 30       | ~60 min  | 🚨 SEVERE    | Manual intervention needed |
| 60+      | 2+ hours | 🚨 OUTAGE    | Restart gateway manually |

## State Rebuild After Reconnection

When bot reconnects, it automatically rebuilds internal state:

```python
✓ Account balance refreshed      # get_account_balance()
✓ Positions reconciled            # get_positions()
✓ Open orders re-synced           # get_open_orders()
✓ Sessions matched to positions   # reconciliation task
✓ Order callbacks re-registered   # orderStatusEvent
```

This ensures **idempotent reconnection** - no duplicate orders, accurate state.

## VNC Access (Optional)

Access IBKR Gateway UI remotely via VNC:

```bash
# VNC server runs on port 5900
# Connect using any VNC client:
vnc://localhost:5900

# Password: Value of VNC_PASSWORD in .env
```

Use VNC to:
- Manually approve IB Key
- Check gateway UI status
- Troubleshoot connection issues
- View IBKR error messages

## Troubleshooting

### Gateway Not Starting

```bash
# Check container logs
docker logs ib-gateway

# Common issues:
# 1. IB_USERNAME or IB_PASSWORD incorrect
# 2. TRADING_MODE mismatch (live vs paper)
# 3. Port conflict (4001/4002 already in use)
```

### Bot Not Connecting

```bash
# Check if gateway is healthy
docker compose ps ib-gateway
# Should show "Up (healthy)"

# Check gateway healthcheck
docker inspect ib-gateway | grep -A 10 Health

# Test port manually
nc -z 127.0.0.1 4001  # Should succeed if gateway is up
```

### Reconnection Loop

If bot keeps reconnecting but gateway is healthy:

```bash
# 1. Check IBKR_PORT matches TRADING_MODE
# Live: 4001, Paper: 4002

# 2. Verify client_id is unique (default: 1)
# Multiple bots need different client_ids

# 3. Check IBKR API permissions
# Account > Settings > API > Enable Socket Clients
```

### Emergency Manual Restart

```bash
# Restart both services
docker compose restart

# Restart gateway only
docker restart ib-gateway

# Restart bot only
docker restart autoscalper

# Hard reset (destroys gateway settings)
docker compose down -v
docker compose up -d
```

## Health Monitoring

### Docker Health Status

```bash
# Check healthchecks
docker compose ps

# Detailed health info
docker inspect ib-gateway | jq '.[0].State.Health'
docker inspect autoscalper | jq '.[0].State.Health'
```

### Bot Telegram Commands

From Telegram, send:

- `/status` - Account balance, positions, open orders
- `/server` - Bot health, IBKR connection, system resources
- `/closeall` - Emergency close all positions

### Application Logs

```bash
# Bot logs (in container)
docker exec autoscalper ls -la /app/logs

# Copy logs to host
docker cp autoscalper:/app/logs ./logs-backup
```

## Production Checklist

Before going live:

- [ ] `.env` file configured with live credentials
- [ ] `TRADING_MODE=live` in docker-compose.yml
- [ ] `IBKR_PORT=4001` for live trading
- [ ] `DRY_RUN=false` in .env
- [ ] Telegram alerts enabled and tested
- [ ] VNC access tested (port 5900)
- [ ] IB Key approval process tested
- [ ] Emergency `/closeall` command tested
- [ ] Logs directory mounted and writable
- [ ] Gateway settings volume persisted
- [ ] Backup strategy for logs and settings

## Updating

```bash
# Pull latest changes
git pull

# Rebuild bot image
docker compose build bot

# Restart with new image (preserves gateway settings)
docker compose up -d

# Verify
docker compose logs -f autoscalper
```

## Limitations

### Cannot Be Automated

1. **IB Key approval** - Requires manual approval weekly
2. **Initial authentication** - First login needs manual approval
3. **Gateway restarts** - Daily restarts are normal IBKR behavior

### Expected Downtime

- **Daily gateway restart**: 1-2 minutes (auto-reconnects)
- **Weekly IB Key approval**: 5-15 minutes (until you approve)
- **Network issues**: Variable (auto-reconnects)

## Success Criteria

✅ No manual intervention on daily gateway restarts
✅ Bot auto-reconnects within 2 minutes
✅ State rebuild happens automatically
✅ Progressive alerts sent to Telegram
✅ Only weekly IB Key approval requires human action
✅ Zero duplicate orders after reconnection
✅ Positions and orders accurately reconciled

## Support

For issues:
1. Check Telegram alerts for specific error details
2. Review bot logs: `docker logs autoscalper`
3. Review gateway logs: `docker logs ib-gateway`
4. Use VNC to access gateway UI: `vnc://localhost:5900`
5. Check GitHub Issues or create new issue
