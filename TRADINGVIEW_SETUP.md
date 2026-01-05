# TradingView Integration (INDICATOR Mode)

## Overview

INDICATOR mode allows AutoScalper to receive trading signals directly from TradingView via webhooks, bypassing Discord and LLM parsing.

## Architecture

```
TradingView Alert
      ↓
  Webhook POST
      ↓
AutoScalper Webhook Server (port 8080)
      ↓
Parse JSON → Event
      ↓
Risk Gate → Execution → IBKR
```

**Key Differences from MIKE Mode:**
- ✅ No Discord monitoring
- ✅ No LLM parsing (structured JSON)
- ✅ Faster signal processing
- ✅ Lower API costs (no Anthropic API calls)
- ✅ More precise control over signals

## Setup

### 1. Configure AutoScalper

Edit `.env`:
```bash
# Switch to INDICATOR mode
MODE=INDICATOR

# TradingView webhook settings
TRADINGVIEW_WEBHOOK_PORT=8080
TRADINGVIEW_WEBHOOK_SECRET=your_secret_key_here  # Change this!

# Keep other settings (IBKR, risk, etc.) the same
```

### 2. Start AutoScalper

```bash
python -m src.orchestrator.main
```

You should see:
```
✓ Signal source: INDICATOR mode (TradingView webhook)
✓ TradingView webhook listening on http://0.0.0.0:8080/webhook
  Health check: http://0.0.0.0:8080/health
  Webhook secret configured: your_sec...
```

### 3. Expose Webhook (if running locally)

**Option A: Use ngrok (recommended for testing)**
```bash
ngrok http 8080
```
Copy the HTTPS URL (e.g., `https://abc123.ngrok.io`)

**Option B: Deploy to VPS**
Use your server's public IP: `http://your-server-ip:8080/webhook`

**Option C: Use Cloudflare Tunnel**
```bash
cloudflared tunnel --url http://localhost:8080
```

### 4. Configure TradingView Alert

1. **Open TradingView** → Create an alert
2. **Set Alert Conditions** (your indicator/strategy)
3. **Webhook URL**: Use your public URL + `/webhook`
   ```
   https://abc123.ngrok.io/webhook
   ```
4. **Message** (JSON format):
   ```json
   {
     "secret": "your_secret_key_here",
     "action": "NEW",
     "ticker": "{{ticker}}",
     "strike": 680.0,
     "direction": "PUT",
     "expiry": "2025-12-24",
     "entry_price": {{close}},
     "stop_loss": 0.18,
     "target": 0.70,
     "quantity": 1,
     "risk_level": "EXTREME",
     "notes": "0DTE momentum trade"
   }
   ```

### 5. Test the Webhook

**Manual test with curl:**
```bash
curl -X POST http://localhost:8080/webhook \
  -H "Content-Type: application/json" \
  -d '{
    "secret": "your_secret_key_here",
    "action": "NEW",
    "ticker": "SPY",
    "strike": 680.0,
    "direction": "PUT",
    "expiry": "2025-12-24",
    "entry_price": 0.35,
    "stop_loss": 0.18,
    "target": 0.70,
    "quantity": 1,
    "risk_level": "EXTREME",
    "notes": "Test signal"
  }'
```

Expected response:
```json
{
  "status": "success",
  "event_type": "NEW",
  "ticker": "SPY 680.0P"
}
```

## JSON Payload Reference

### Required Fields

| Field | Type | Description | Example |
|-------|------|-------------|---------|
| `secret` | string | Webhook authentication secret | `"your_secret_key"` |
| `action` | string | Event type (see below) | `"NEW"` |
| `ticker` | string | Underlying symbol | `"SPY"` |
| `strike` | float | Strike price | `680.0` |
| `direction` | string | PUT or CALL | `"PUT"` |
| `expiry` | string | Expiration date (YYYY-MM-DD) | `"2025-12-24"` |

### Optional Fields

| Field | Type | Description | Default |
|-------|------|-------------|---------|
| `entry_price` | float | Entry price | `0` |
| `stop_loss` | float | Stop loss price | Auto-calculated |
| `target` | float | Target price | Auto-calculated |
| `quantity` | int | Number of contracts | `1` |
| `risk_level` | string | LOW, MEDIUM, HIGH, EXTREME | `"MEDIUM"` |
| `notes` | string | Additional notes | `""` |

### Action Types

| Action | Description | Use Case |
|--------|-------------|----------|
| `NEW` | Open new position | Entry signal from indicator |
| `ADD` | Add to existing position | Scale into winner |
| `EXIT` | Close entire position | Exit signal from indicator |
| `TRIM` | Partial exit | Take partial profits |
| `MOVE_STOP` | Update stop loss | Tighten stop as position moves in favor |

## TradingView Alert Examples

### Entry Signal (NEW)
```json
{
  "secret": "{{secret}}",
  "action": "NEW",
  "ticker": "{{ticker}}",
  "strike": {{strike}},
  "direction": "{{direction}}",
  "expiry": "{{expiry}}",
  "entry_price": {{close}},
  "stop_loss": {{stop_price}},
  "target": {{target_price}},
  "risk_level": "EXTREME",
  "notes": "Momentum breakout"
}
```

### Exit Signal (EXIT)
```json
{
  "secret": "{{secret}}",
  "action": "EXIT",
  "ticker": "{{ticker}}",
  "strike": {{strike}},
  "direction": "{{direction}}",
  "expiry": "{{expiry}}",
  "notes": "Reversal detected"
}
```

### Move Stop (MOVE_STOP)
```json
{
  "secret": "{{secret}}",
  "action": "MOVE_STOP",
  "ticker": "{{ticker}}",
  "strike": {{strike}},
  "direction": "{{direction}}",
  "expiry": "{{expiry}}",
  "stop_loss": {{new_stop}},
  "notes": "Trailing stop"
}
```

## Using TradingView Variables

TradingView allows dynamic values in alert messages:

| Variable | Description |
|----------|-------------|
| `{{ticker}}` | Ticker symbol |
| `{{close}}` | Current close price |
| `{{time}}` | Alert trigger time |
| `{{interval}}` | Chart timeframe |
| `{{strategy.order.action}}` | BUY or SELL (for strategies) |

**Example with variables:**
```json
{
  "secret": "my_secret",
  "action": "NEW",
  "ticker": "{{ticker}}",
  "strike": 680.0,
  "direction": "PUT",
  "expiry": "2025-12-24",
  "entry_price": {{close}},
  "notes": "{{time}} - {{interval}} momentum"
}
```

## Security

### Webhook Secret

**CRITICAL**: Change `TRADINGVIEW_WEBHOOK_SECRET` in `.env` to a strong random string!

```bash
# Generate secure secret
openssl rand -hex 32

# Or use this
python -c "import secrets; print(secrets.token_hex(32))"
```

### IP Whitelisting (Optional)

TradingView webhooks come from these IPs:
```
52.89.214.238
34.212.75.30
54.218.53.128
52.32.178.7
```

Add firewall rules if needed:
```bash
# Example: UFW
sudo ufw allow from 52.89.214.238 to any port 8080
sudo ufw allow from 34.212.75.30 to any port 8080
sudo ufw allow from 54.218.53.128 to any port 8080
sudo ufw allow from 52.32.178.7 to any port 8080
```

## Troubleshooting

### Webhook Not Receiving Signals

1. **Check webhook is running:**
   ```bash
   curl http://localhost:8080/health
   ```
   Should return: `{"status": "healthy", ...}`

2. **Check ngrok/tunnel:**
   ```bash
   curl https://your-ngrok-url.ngrok.io/health
   ```

3. **Check TradingView alert log:**
   - TradingView → Alerts → View sent webhooks
   - Look for error messages

### Authentication Failures

**Error**: `{"error": "Invalid secret"}`

**Fix**: Ensure `secret` in JSON matches `TRADINGVIEW_WEBHOOK_SECRET` in `.env`

### Invalid Payload

**Error**: `{"error": "Invalid signal format"}`

**Fix**: Check required fields in JSON:
- `secret`, `action`, `ticker`, `strike`, `direction`, `expiry` are all required

## Advanced: Pine Script Integration

Example Pine Script that sends webhook on entry:

```pine
//@version=5
strategy("AutoScalper Integration", overlay=true)

// Your strategy logic here
longCondition = ta.crossover(ta.sma(close, 14), ta.sma(close, 28))

if (longCondition)
    // Send webhook via strategy.entry alert
    alert('{"secret":"my_secret","action":"NEW","ticker":"SPY","strike":680.0,"direction":"PUT","expiry":"2025-12-24","entry_price":' + str.tostring(close) + ',"risk_level":"HIGH"}', alert.freq_once_per_bar)
    strategy.entry("Long", strategy.long)
```

## Monitoring

View webhook activity:
```bash
# Bot logs
tail -f logs/$(date +%Y-%m-%d)/*.log

# Look for:
# [TRADINGVIEW SIGNAL]
# Action: NEW
# Ticker: SPY 680.0P 2025-12-24
```

## Switching Between Modes

**To switch from MIKE → INDICATOR:**
1. Set `MODE=INDICATOR` in `.env`
2. Restart bot
3. Configure TradingView alerts

**To switch from INDICATOR → MIKE:**
1. Set `MODE=MIKE` in `.env`
2. Restart bot
3. Bot resumes Discord monitoring

**All other settings (IBKR, risk, Telegram) remain unchanged.**

## FAQ

**Q: Can I run both MIKE and INDICATOR modes simultaneously?**
A: Not in the same process. Run two separate bots on different ports.

**Q: Do I still need Claude API in INDICATOR mode?**
A: No! INDICATOR mode doesn't use LLM parsing, saving API costs.

**Q: Can I use TradingView strategies instead of alerts?**
A: Yes, but you'll need to set up alerts on strategy entries/exits.

**Q: What happens if webhook is unreachable?**
A: TradingView will retry a few times, then stop. Use Telegram alerts to monitor bot health.

## Support

For issues:
1. Check bot logs: `logs/YYYY-MM-DD/*.log`
2. Test webhook manually with curl
3. Verify TradingView alert sent successfully
4. Check firewall/network settings
