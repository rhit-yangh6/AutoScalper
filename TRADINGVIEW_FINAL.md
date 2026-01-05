# TradingView Integration - Final Simple Version

## The Simplest Possible Setup

TradingView sends **ONLY the signal**. AutoScalper calculates everything else.

---

## JSON Format

### ENTRY Signal

```json
{
  "secret": "your_secret_key",
  "action": "NEW",
  "ticker": "SPY",
  "direction": "PUT",
  "underlying_price": 682.50
}
```

That's it! AutoScalper will:
1. ✅ Calculate strike: `682.50 - 3.5 = 680.0` (PUT, 3.5 offset)
2. ✅ Calculate expiry: `Today` (0DTE)
3. ✅ Fetch option premium from IBKR: Real-time market quote
4. ✅ Calculate stop loss: 50% below entry (from config)
5. ✅ Calculate target: 30% above entry (from config)
6. ✅ Place OCO brackets automatically

### EXIT Signal

```json
{
  "secret": "your_secret_key",
  "action": "EXIT",
  "ticker": "SPY",
  "direction": "PUT",
  "underlying_price": 682.50
}
```

AutoScalper will:
1. Calculate strike: `680.0`
2. Find matching position: `SPY 680P`
3. Close entire position
4. Cancel remaining brackets

---

## Optional Fields

Want more control? Add optional fields:

```json
{
  "secret": "your_secret_key",
  "action": "NEW",
  "ticker": "SPY",
  "direction": "PUT",
  "underlying_price": 682.50,
  "strike_offset": 4.0,
  "expiry_days": 0,
  "quantity": 2,
  "risk_level": "HIGH",
  "notes": "Momentum breakout"
}
```

| Field | Default | Description |
|-------|---------|-------------|
| `strike_offset` | `3.5` | Dollars away from underlying |
| `expiry_days` | `0` | 0=today (0DTE), 1=tomorrow, etc. |
| `quantity` | `1` | Contracts (overridden by risk gate) |
| `risk_level` | `"EXTREME"` | LOW/MEDIUM/HIGH/EXTREME |
| `notes` | `""` | Optional description |

---

## TradingView Alert Setup

### Alert 1: Entry

**Condition:** Your indicator triggers BUY

**Webhook URL:** `https://your-ngrok-url.ngrok.io/webhook`

**Message:**
```json
{
  "secret": "your_secret",
  "action": "NEW",
  "ticker": "{{ticker}}",
  "direction": "PUT",
  "underlying_price": {{close}}
}
```

### Alert 2: Exit

**Condition:** Your indicator triggers SELL

**Webhook URL:** `https://your-ngrok-url.ngrok.io/webhook`

**Message:**
```json
{
  "secret": "your_secret",
  "action": "EXIT",
  "ticker": "{{ticker}}",
  "direction": "PUT",
  "underlying_price": {{close}}
}
```

---

## Pine Script Example

```pinescript
//@version=5
strategy("AutoScalper", overlay=true)

// Strategy logic
fastMA = ta.sma(close, 10)
slowMA = ta.sma(close, 20)

// Shared config
secret = "your_secret"
ticker = syminfo.ticker
direction = "PUT"  // or "CALL"

// Entry
if ta.crossover(fastMA, slowMA)
    msg = '{"secret":"' + secret + '",' +
          '"action":"NEW",' +
          '"ticker":"' + ticker + '",' +
          '"direction":"' + direction + '",' +
          '"underlying_price":' + str.tostring(close) + '}'
    alert(msg, alert.freq_once_per_bar)
    strategy.entry("Long", strategy.long)

// Exit
if ta.crossunder(fastMA, slowMA)
    msg = '{"secret":"' + secret + '",' +
          '"action":"EXIT",' +
          '"ticker":"' + ticker + '",' +
          '"direction":"' + direction + '",' +
          '"underlying_price":' + str.tostring(close) + '}'
    alert(msg, alert.freq_once_per_bar)
    strategy.close("Long")
```

---

## What AutoScalper Does

### On ENTRY Signal

1. **Receives:** `{"ticker": "SPY", "direction": "PUT", "underlying_price": 682.50}`

2. **Calculates Strike:**
   - PUT: `682.50 - 3.5 = 679.0` → rounds to **680.0**
   - CALL: `682.50 + 3.5 = 686.0` → rounds to **685.0**

3. **Calculates Expiry:**
   - `expiry_days=0` → **Today** (0DTE)
   - `expiry_days=7` → **Next week**

4. **Fetches Option Premium from IBKR:**
   - Requests real-time market data for SPY 680P
   - Uses bid/ask spread to set limit order
   - Or uses market order if configured

5. **Auto-Calculates Brackets:**
   - Stop Loss: Entry × (1 - AUTO_STOP_LOSS_PERCENT)
     - Example: $0.35 × 0.50 = **$0.18**
   - Target: Entry × (1 + RISK_REWARD_RATIO)
     - Example: $0.35 × 1.60 = **$0.56**

6. **Places Orders:**
   - Entry: BUY 1 SPY 680P @ $0.35
   - OCO Bracket: Stop $0.18 | Target $0.56

### On EXIT Signal

1. **Receives:** `{"ticker": "SPY", "direction": "PUT", "underlying_price": 682.50}`
2. **Calculates Strike:** `680.0`
3. **Finds Position:** SPY 680P
4. **Closes:** Market sell entire position
5. **Cancels:** All remaining bracket orders

---

## Configuration (.env)

These control auto-calculation:

```bash
# Strike offset (dollars away from underlying)
# Default: 3.5
STRIKE_OFFSET=3.5

# Auto stop loss (% below entry)
# Default: 50% (0DTE options are volatile!)
AUTO_STOP_LOSS_PERCENT=50.0

# Risk/reward ratio for target
# Default: 0.6 (60% gain target)
# 0.6 = 60% gain, 1.0 = 100% gain, 2.0 = 200% gain
RISK_REWARD_RATIO=0.6
```

**Examples with different configs:**

Entry premium: **$0.35**

| Config | Stop Loss | Target | R:R |
|--------|-----------|--------|-----|
| `AUTO_STOP_LOSS_PERCENT=50` | $0.18 (50% loss) | $0.56 (60% gain) | 1:1.2 |
| `AUTO_STOP_LOSS_PERCENT=25` | $0.26 (25% loss) | $0.70 (100% gain) | 1:4 |
| `AUTO_STOP_LOSS_PERCENT=75` | $0.09 (75% loss) | $0.49 (40% gain) | 1:0.5 |

---

## Test It

```bash
# 1. Start bot in INDICATOR mode
MODE=INDICATOR python -m src.orchestrator.main

# 2. Test ENTRY
curl -X POST http://localhost:8080/webhook \
  -H "Content-Type: application/json" \
  -d '{
    "secret": "test",
    "action": "NEW",
    "ticker": "SPY",
    "direction": "PUT",
    "underlying_price": 682.50
  }'

# Expected output:
# Calculated strike: $680.00 (underlying $682.50, offset $3.50)
# Calculated expiry: 2025-12-24 (0 days from today)
# Fetching option premium from IBKR...
# ✓ Entry filled at $0.35
# ✓ Brackets placed: Stop $0.18 | Target $0.56

# 3. Test EXIT
curl -X POST http://localhost:8080/webhook \
  -H "Content-Type: application/json" \
  -d '{
    "secret": "test",
    "action": "EXIT",
    "ticker": "SPY",
    "direction": "PUT",
    "underlying_price": 682.50
  }'

# Expected output:
# Found position: SPY 680P
# ✓ Position closed at $0.42
# P&L: +$7.00 (+20%)
```

---

## Complete Workflow

```
┌─────────────────────────────────────────────────┐
│ TradingView Indicator Triggers                  │
└─────────────────┬───────────────────────────────┘
                  ↓
            Sends Webhook:
      {"ticker": "SPY", "direction": "PUT",
       "underlying_price": 682.50}
                  ↓
┌─────────────────────────────────────────────────┐
│ AutoScalper Receives Signal                     │
├─────────────────────────────────────────────────┤
│ 1. Calculate strike: 682.50 - 3.5 = 680.0      │
│ 2. Calculate expiry: Today (0DTE)               │
│ 3. Fetch premium from IBKR: $0.35              │
│ 4. Calculate stop: $0.35 × 0.5 = $0.18         │
│ 5. Calculate target: $0.35 × 1.6 = $0.56       │
└─────────────────┬───────────────────────────────┘
                  ↓
┌─────────────────────────────────────────────────┐
│ Execute on IBKR                                  │
├─────────────────────────────────────────────────┤
│ BUY 1 SPY 680P @ $0.35                          │
│ OCO Brackets:                                    │
│   Stop: SELL @ $0.18 (-50%)                     │
│   Target: SELL @ $0.56 (+60%)                   │
└─────────────────┬───────────────────────────────┘
                  ↓
            Telegram Alert:
      "✅ Entered SPY 680P @ $0.35
       Stop: $0.18 | Target: $0.56"
```

---

## Summary

**TradingView sends:**
- Ticker, direction, underlying price ← **That's all!**

**AutoScalper handles:**
- ✅ Strike calculation
- ✅ Expiry calculation
- ✅ Option premium (live IBKR data)
- ✅ Stop loss calculation
- ✅ Target calculation
- ✅ OCO bracket placement
- ✅ Position tracking
- ✅ Risk management

**Your config controls:**
- Strike offset (default 3.5)
- Stop loss % (default 50%)
- Target R/R (default 0.6 = 60% gain)

🎯 **The simplest possible integration!**
