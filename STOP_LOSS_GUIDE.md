# Stop Loss Guide for Options Trading

## Understanding Options Volatility

Options (especially 0DTE) are **FAR more volatile** than stocks:
- **Stocks:** Daily moves of 1-3% are normal
- **Options:** Intraday swings of 30-50% are common

**Why so volatile?**
- Leverage effect (options magnify underlying moves)
- Time decay (theta) causes rapid value changes
- Gamma risk (delta changes quickly near expiry)
- Low liquidity can cause wide swings

---

## Current Default Setting

```bash
AUTO_STOP_LOSS_PERCENT=50.0  # Stop at 50% below entry
```

### Example Trade Comparison:

| Entry Price | Old Stop (25%) | New Stop (50%) | Old Target | New Target |
|------------|---------------|---------------|-----------|-----------|
| $1.00 | $0.75 ❌ | $0.50 ✅ | $1.50 | $2.00 |
| $2.00 | $1.50 ❌ | $1.00 ✅ | $3.00 | $4.00 |
| $0.50 | $0.38 ❌ | $0.25 ✅ | $0.75 | $1.00 |

**❌ 25% Stop:** Gets hit on normal intraday noise
**✅ 50% Stop:** Allows room for volatility, still protects capital

---

## Why 50% for Options?

### Real Example - SPY $600 Call @ $1.00 entry

**With 25% stop ($0.75):**
```
9:30 AM  Entry: $1.00
9:45 AM  Dips to $0.80 (normal volatility)
9:50 AM  Dips to $0.74 → STOPPED OUT ❌
10:00 AM Rallies to $1.50 (target hit, but you're out)
```
**Result:** -$25 loss, missed 50% gain

**With 50% stop ($0.50):**
```
9:30 AM  Entry: $1.00
9:45 AM  Dips to $0.80 (normal volatility)
9:50 AM  Dips to $0.74 (still safe)
10:00 AM Rallies to $2.00 → TARGET HIT ✅
```
**Result:** +$100 gain, survived volatility

---

## Recommended Settings by Strategy

### Conservative (Recommended for 0DTE):
```bash
AUTO_STOP_LOSS_PERCENT=50.0
RISK_REWARD_RATIO=2.0
```
- Entry: $1.00 → Stop: $0.50 → Target: $2.00
- Win rate needed: ~35% to be profitable
- Survives normal volatility

### Balanced:
```bash
AUTO_STOP_LOSS_PERCENT=40.0
RISK_REWARD_RATIO=2.0
```
- Entry: $1.00 → Stop: $0.60 → Target: $1.80
- Win rate needed: ~40% to be profitable
- Moderate room for swings

### Tight (NOT recommended for 0DTE):
```bash
AUTO_STOP_LOSS_PERCENT=25.0
RISK_REWARD_RATIO=2.0
```
- Entry: $1.00 → Stop: $0.75 → Target: $1.50
- Win rate needed: ~50% to be profitable
- Gets stopped out too easily on 0DTE

---

## Important Notes

### 1. **Discord Alerts Override Auto Stops**
If your Discord trader provides stop loss levels, those are used instead:
```
Entry: $1.00
Stop: $0.30  ← Trader's explicit stop (70% wide!)
Target: $2.50
```
Auto stops only apply when trader **doesn't specify** stop loss.

### 2. **0DTE vs Weekly vs Monthly**
Different expiries need different stops:

| Expiry Type | Recommended Stop | Reason |
|-------------|-----------------|--------|
| 0DTE | 50-60% | Extremely volatile, needs room |
| 1-7 DTE | 40-50% | High volatility, some time value |
| 30+ DTE | 30-40% | Lower volatility, more time value |

### 3. **Risk Management Still Applies**
Wider stops don't mean risking more money!
- Position sizing adjusts automatically
- `RISK_PER_TRADE_PERCENT=0.5` still limits max loss
- Wider stop = smaller position size

**Example:**
- Account: $10,000
- Risk per trade: 0.5% = $50 max loss
- Entry: $1.00, Stop: $0.50 (50% stop)
- Max contracts: $50 / $0.50 = **1 contract**

vs.

- Entry: $1.00, Stop: $0.75 (25% stop)
- Max contracts: $50 / $0.25 = **2 contracts**

**Same $50 risk, different position sizes!**

---

## How to Change Your Settings

### On Your Server:
```bash
ssh root@your-server
cd /opt/autoscalper
nano .env

# Change this line:
AUTO_STOP_LOSS_PERCENT=50.0

# Save and restart:
sudo systemctl restart autoscalper
```

### Testing Your Settings:
```bash
# Watch the logs
sudo journalctl -u autoscalper -f

# Look for auto-calculated stops:
[4/5] Calculating position size and risk parameters...
✓ Position size: 1 contracts
  Auto-calculated Stop Loss: $0.50    ← Should be 50% below entry
  Auto-calculated Target: $2.00
  Risk/Reward: 1:2.00
```

---

## Common Questions

### Q: Won't a 50% stop mean losing more money?
**A:** No! Position sizing adjusts. You risk the same dollar amount ($50), just with fewer contracts.

### Q: What if the trader's stop is tighter than 50%?
**A:** Trader's explicit stops are always used. Auto stops are only fallback.

### Q: Should I use even wider stops?
**A:** For 0DTE, 50% is a good balance. Going wider (60-70%) is okay but requires higher win rate.

### Q: What about stop-market vs stop-limit?
**A:** We use **limit orders for everything** (including stops) to avoid slippage. Bracket orders handle OCO logic.

---

## Bracket Order Behavior

When entry fills, bracket activates:
```
Entry: BUY 1 @ $1.00 (filled)
├─ Stop Loss: SELL 1 @ $0.50 (pending)
└─ Target: SELL 1 @ $2.00 (pending)
```

**OCO (One Cancels Other):**
- If stop fills → Target cancelled automatically
- If target fills → Stop cancelled automatically ✅
- If EXIT alert comes → Both cancelled, then new EXIT order placed

**No manual cancellation needed for TP/SL!**

---

## Summary

✅ **Changed default to 50% stop** for options volatility
✅ **Bracket OCO handles TP/SL cancellation** automatically
✅ **EXIT orders cancel existing brackets** before placing
✅ **Position sizing keeps dollar risk constant**

**Bottom line:** Wider stops for options = fewer stopped-out trades = better performance!
