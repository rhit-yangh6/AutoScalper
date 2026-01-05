# TradingView Signals - Quick Reference

## Two Signal Types Only

### 1. ENTRY Signal (Open + Brackets)

```json
{
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
}
```

**Result:**
- Strike auto-calculated: 682.50 - 3.5 = **680.0** (PUT)
- Expiry: **Today** (0DTE)
- Opens **SPY 680P** @ $0.35
- Places OCO brackets: Stop $0.18 | Target $0.70

---

### 2. EXIT Signal (Close Everything)

```json
{
  "secret": "your_secret",
  "action": "EXIT",
  "ticker": "SPY",
  "direction": "PUT",
  "underlying_price": 682.50,
  "strike_offset": 3.5,
  "expiry_days": 0
}
```

**Result:**
- Calculates strike: **680.0**
- Finds matching position: **SPY 680P**
- Closes entire position
- Cancels all remaining brackets

---

## Field Cheat Sheet

| Field | Required | Type | Example | Notes |
|-------|----------|------|---------|-------|
| `secret` | ✅ Yes | string | `"abc123"` | Must match .env |
| `action` | ✅ Yes | string | `"NEW"` or `"EXIT"` | Signal type |
| `ticker` | ✅ Yes | string | `"SPY"` | Underlying symbol |
| `direction` | ✅ Yes | string | `"PUT"` or `"CALL"` | Option type |
| `underlying_price` | ✅ Yes | float | `682.50` | Current price (use `{{close}}`) |
| `option_premium` | NEW only | float | `0.35` | Entry price for option |
| `stop_loss` | NEW only | float | `0.18` | Stop loss price |
| `target` | NEW only | float | `0.70` | Target price |
| `strike_offset` | Optional | float | `3.5` | Dollars away (default: 3.5) |
| `expiry_days` | Optional | int | `0` | Days from today (default: 0) |

---

## Strike Calculation

### PUT Example
```
underlying_price = 682.50
strike_offset = 3.5
direction = PUT

Strike = 682.50 - 3.5 = 679.0 → rounds to 680.0
Result: SPY 680P
```

### CALL Example
```
underlying_price = 682.50
strike_offset = 4.0
direction = CALL

Strike = 682.50 + 4.0 = 686.5 → rounds to 685.0
Result: SPY 685C
```

**Rounding:** Always rounds to nearest $5 (SPY/QQQ standard)

---

## TradingView Variables

Use these in your alert message:

| Variable | Description | Example |
|----------|-------------|---------|
| `{{ticker}}` | Symbol | `"SPY"` |
| `{{close}}` | Current close price | `682.50` |
| `{{time}}` | Alert timestamp | `"2025-12-24 14:30"` |
| `{{interval}}` | Chart timeframe | `"5"` |

**Example:**
```json
{
  "ticker": "{{ticker}}",
  "underlying_price": {{close}},
  "notes": "Entry at {{time}} on {{interval}}min chart"
}
```

---

## Test Commands

### Test ENTRY
```bash
curl -X POST http://localhost:8080/webhook -H "Content-Type: application/json" -d '{"secret":"test","action":"NEW","ticker":"SPY","direction":"PUT","underlying_price":682.50,"option_premium":0.35,"stop_loss":0.18,"target":0.70}'
```

### Test EXIT
```bash
curl -X POST http://localhost:8080/webhook -H "Content-Type: application/json" -d '{"secret":"test","action":"EXIT","ticker":"SPY","direction":"PUT","underlying_price":682.50}'
```

---

## Common Offsets

| Offset | Distance | Premium | Use Case |
|--------|----------|---------|----------|
| 2.0 | Closer to ATM | Higher | Aggressive, more delta |
| 3.5 | **Default** | Medium | Balanced |
| 5.0 | Further OTM | Lower | Conservative, lotto |

**For SPY at $682:**
- 2.0 offset → 680P (~$0.50)
- 3.5 offset → 680P (~$0.35)
- 5.0 offset → 675P (~$0.15)

---

## Workflow Diagram

```
TradingView Signal
        ↓
Webhook POST to AutoScalper
        ↓
Calculate Strike & Expiry
        ↓
Risk Gate Validation
        ↓
Execute on IBKR
        ↓
Place OCO Brackets (if NEW)
        ↓
Telegram Notification
```

---

## Complete Example

### Your TradingView Alert

**Condition:** EMA crossover
**Webhook URL:** `https://abc123.ngrok.io/webhook`
**Message:**

```json
{
  "secret": "my_secret_123",
  "action": "NEW",
  "ticker": "{{ticker}}",
  "direction": "PUT",
  "underlying_price": {{close}},
  "option_premium": 0.35,
  "stop_loss": 0.18,
  "target": 0.70,
  "strike_offset": 3.5,
  "expiry_days": 0,
  "notes": "Entry {{time}}"
}
```

### What AutoScalper Does

1. Receives webhook
2. Calculates: `SPY 680P 2025-12-24`
3. Buys 1 contract @ $0.35
4. Places brackets: Stop $0.18, Target $0.70
5. Sends Telegram notification

### Later: EXIT Alert

**Condition:** EMA crossunder
**Message:**

```json
{
  "secret": "my_secret_123",
  "action": "EXIT",
  "ticker": "{{ticker}}",
  "direction": "PUT",
  "underlying_price": {{close}},
  "strike_offset": 3.5,
  "expiry_days": 0
}
```

### What AutoScalper Does

1. Calculates same strike: `SPY 680P`
2. Closes position immediately
3. Cancels remaining brackets
4. Sends Telegram notification

---

## That's It!

**Just 2 signals:**
- `NEW` = Open with brackets
- `EXIT` = Close everything

**AutoScalper handles:**
- ✅ Strike calculation
- ✅ Expiry calculation
- ✅ OCO bracket placement
- ✅ Position tracking
- ✅ Risk management

🎯 **Keep it simple!**
