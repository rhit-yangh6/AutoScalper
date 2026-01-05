# TradingView Setup Guide (Simplified)

## Overview

AutoScalper automatically calculates strike prices and expiry dates. TradingView only needs to provide:
- Underlying ticker and price
- Direction (CALL or PUT)
- Option premium and brackets

**Strike is auto-calculated:** 3-4 dollars away from current price, rounded to nearest $5
**Expiry is auto-calculated:** Default 0DTE (same day expiration)

## JSON Format

### ENTRY Signal (Open Position + Brackets)

```json
{
  "secret": "your_webhook_secret",
  "action": "NEW",
  "ticker": "SPY",
  "direction": "PUT",
  "underlying_price": 682.50,
  "option_premium": 0.35,
  "stop_loss": 0.18,
  "target": 0.70,
  "strike_offset": 3.5,
  "expiry_days": 0
}
```

**What AutoScalper calculates:**
- `underlying_price=682.50, direction=PUT, strike_offset=3.5`
  - → Strike = 682.50 - 3.5 = 679.0 → **rounds to 680.0**
- `expiry_days=0` → **Today's date** (0DTE)
- Result: **SPY 680P expiring today**

### EXIT Signal (Close Position)

```json
{
  "secret": "your_webhook_secret",
  "action": "EXIT",
  "ticker": "SPY",
  "direction": "PUT",
  "underlying_price": 682.50,
  "strike_offset": 3.5,
  "expiry_days": 0
}
```

**What AutoScalper does:**
- Calculates strike (680.0) and expiry (today)
- Finds matching open position
- Closes entire position immediately
- Cancels remaining bracket orders

## Field Reference

### Required Fields

| Field | Type | Description | Example |
|-------|------|-------------|---------|
| `secret` | string | Webhook authentication | `"your_secret"` |
| `action` | string | NEW or EXIT | `"NEW"` |
| `ticker` | string | Underlying symbol | `"SPY"` |
| `direction` | string | PUT or CALL | `"PUT"` |
| `underlying_price` | float | Current underlying price | `682.50` |

### Optional Fields (NEW only)

| Field | Type | Description | Default |
|-------|------|-------------|---------|
| `option_premium` | float | Entry price for option | `0` (market) |
| `stop_loss` | float | Stop loss price | Auto-calculated |
| `target` | float | Target price | Auto-calculated |
| `strike_offset` | float | Dollars away from underlying | `3.5` |
| `expiry_days` | int | Days until expiry (0=today) | `0` |
| `quantity` | int | Number of contracts | `1` |
| `risk_level` | string | LOW/MEDIUM/HIGH/EXTREME | `"EXTREME"` |
| `notes` | string | Additional notes | `""` |

## Strike Calculation Examples

### Example 1: PUT Option
```json
{
  "ticker": "SPY",
  "direction": "PUT",
  "underlying_price": 682.50,
  "strike_offset": 3.5
}
```
**Calculation:**
- 682.50 - 3.5 = 679.0
- Round to nearest $5 = **680.0**
- Result: **SPY 680P**

### Example 2: CALL Option
```json
{
  "ticker": "QQQ",
  "direction": "CALL",
  "underlying_price": 515.30,
  "strike_offset": 4.0
}
```
**Calculation:**
- 515.30 + 4.0 = 519.30
- Round to nearest $5 = **520.0**
- Result: **QQQ 520C**

### Example 3: Custom Offset
```json
{
  "ticker": "SPY",
  "direction": "PUT",
  "underlying_price": 682.50,
  "strike_offset": 2.0
}
```
**Calculation:**
- 682.50 - 2.0 = 680.50
- Round to nearest $5 = **680.0**
- Result: **SPY 680P** (closer to ATM)

## TradingView Alert Setup

### Alert 1: ENTRY Signal

**Condition:** Your indicator triggers BUY

**Webhook URL:** `https://your-ngrok-url.ngrok.io/webhook`

**Message:**
```json
{
  "secret": "your_secret",
  "action": "NEW",
  "ticker": "{{ticker}}",
  "direction": "PUT",
  "underlying_price": {{close}},
  "option_premium": 0.35,
  "stop_loss": 0.18,
  "target": 0.70,
  "strike_offset": 3.5,
  "expiry_days": 0,
  "notes": "TradingView entry {{time}}"
}
```

### Alert 2: EXIT Signal

**Condition:** Your indicator triggers SELL

**Webhook URL:** `https://your-ngrok-url.ngrok.io/webhook`

**Message:**
```json
{
  "secret": "your_secret",
  "action": "EXIT",
  "ticker": "{{ticker}}",
  "direction": "PUT",
  "underlying_price": {{close}},
  "strike_offset": 3.5,
  "expiry_days": 0,
  "notes": "TradingView exit {{time}}"
}
```

## Pine Script Example

```pinescript
//@version=5
strategy("AutoScalper Webhook", overlay=true)

// Your strategy
fastMA = ta.sma(close, 10)
slowMA = ta.sma(close, 20)

// Entry condition
longCondition = ta.crossover(fastMA, slowMA)
if (longCondition)
    // Build ENTRY webhook
    secret = "your_secret"
    ticker = syminfo.ticker
    direction = "PUT"  // or "CALL"
    underlyingPrice = close
    optionPremium = 0.35  // Estimate or leave as 0 for market
    stopLoss = 0.18
    target = 0.70
    strikeOffset = 3.5
    expiryDays = 0

    webhookMsg = '{"secret":"' + secret + '",' +
                 '"action":"NEW",' +
                 '"ticker":"' + ticker + '",' +
                 '"direction":"' + direction + '",' +
                 '"underlying_price":' + str.tostring(underlyingPrice) + ',' +
                 '"option_premium":' + str.tostring(optionPremium) + ',' +
                 '"stop_loss":' + str.tostring(stopLoss) + ',' +
                 '"target":' + str.tostring(target) + ',' +
                 '"strike_offset":' + str.tostring(strikeOffset) + ',' +
                 '"expiry_days":' + str.tostring(expiryDays) + '}'

    alert(webhookMsg, alert.freq_once_per_bar)
    strategy.entry("Long", strategy.long)

// Exit condition
shortCondition = ta.crossunder(fastMA, slowMA)
if (shortCondition)
    // Build EXIT webhook
    webhookMsg = '{"secret":"' + secret + '",' +
                 '"action":"EXIT",' +
                 '"ticker":"' + ticker + '",' +
                 '"direction":"' + direction + '",' +
                 '"underlying_price":' + str.tostring(close) + ',' +
                 '"strike_offset":' + str.tostring(strikeOffset) + ',' +
                 '"expiry_days":' + str.tostring(expiryDays) + '}'

    alert(webhookMsg, alert.freq_once_per_bar)
    strategy.close("Long")
```

## Testing

### Test ENTRY Signal
```bash
curl -X POST http://localhost:8080/webhook \
  -H "Content-Type: application/json" \
  -d '{
    "secret": "your_secret",
    "action": "NEW",
    "ticker": "SPY",
    "direction": "PUT",
    "underlying_price": 682.50,
    "option_premium": 0.35,
    "stop_loss": 0.18,
    "target": 0.70,
    "strike_offset": 3.5,
    "expiry_days": 0
  }'
```

**Expected output:**
```
Calculated strike: $680.00 (underlying $682.50, offset $3.50)
Calculated expiry: 2025-12-24 (0 days from today)
✓ Signal processed: SPY 680P
```

### Test EXIT Signal
```bash
curl -X POST http://localhost:8080/webhook \
  -H "Content-Type: application/json" \
  -d '{
    "secret": "your_secret",
    "action": "EXIT",
    "ticker": "SPY",
    "direction": "PUT",
    "underlying_price": 682.50,
    "strike_offset": 3.5,
    "expiry_days": 0
  }'
```

## Strike Offset Guidelines

| Strategy | Offset | Strike Distance | Use Case |
|----------|--------|-----------------|----------|
| Aggressive | 2.0-3.0 | Closer to ATM | Higher premium, more delta |
| Moderate | 3.5-4.5 | Mid-range | Balanced risk/reward |
| Conservative | 5.0-6.0 | Further OTM | Lower cost, lotto play |

**For SPY at $682:**
- Offset 2.0 → SPY 680P (closer to ATM, ~$0.50 premium)
- Offset 3.5 → SPY 680P ($0.35 premium)
- Offset 5.0 → SPY 675P (far OTM, $0.15 premium)

## Expiry Options

| expiry_days | Description | Use Case |
|-------------|-------------|----------|
| 0 | Same day (0DTE) | Day trading, scalping |
| 1 | Next day | Hold overnight |
| 7 | Next week | Swing trades |
| 14+ | 2+ weeks | Position trades |

## Workflow

1. **TradingView sends signal:**
   ```json
   {"ticker": "SPY", "direction": "PUT", "underlying_price": 682.50, ...}
   ```

2. **AutoScalper calculates:**
   - Strike: 682.50 - 3.5 = 679.0 → rounds to **680.0**
   - Expiry: Today = **2025-12-24**
   - Contract: **SPY 680P 2025-12-24**

3. **AutoScalper executes:**
   - Buy SPY 680P @ $0.35
   - Place OCO brackets:
     - Stop: $0.18
     - Target: $0.70

4. **TradingView sends EXIT:**
   ```json
   {"action": "EXIT", "ticker": "SPY", "direction": "PUT", ...}
   ```

5. **AutoScalper closes:**
   - Calculates same strike (680.0) and expiry
   - Closes SPY 680P position
   - Cancels remaining brackets

## Quick Start

1. Set `MODE=INDICATOR` in `.env`
2. Set `TRADINGVIEW_WEBHOOK_SECRET` to strong random value
3. Start bot: `python -m src.orchestrator.main`
4. Expose with ngrok: `ngrok http 8080`
5. Create TradingView alerts with JSON above
6. Test with curl commands

**That's it!** TradingView sends underlying price, AutoScalper handles the rest. 🎯
