# Logging Feature Summary

## What Was Added

Comprehensive logging system for all Discord messages and IBKR orders, organized by trading sessions.

## New Files Created

1. **src/logging/trade_logger.py** - Core logging module
2. **src/logging/__init__.py** - Module exports
3. **LOGGING.md** - Complete logging documentation

## Updated Files

1. **src/orchestrator/main.py**
   - Integrated TradeLogger
   - Logs Discord messages
   - Logs parsed events
   - Logs order submissions
   - Logs order results (filled/rejected/cancelled)
   - Logs errors
   - Flushes logs on shutdown

## Log Files Created

When you run the bot, it will create:

```
logs/
└── YYYY-MM-DD/
    ├── session_HHMMSS_SYMBOL_DIRECTION.log  (human-readable)
    ├── session_HHMMSS_SYMBOL_DIRECTION.json (structured data)
    ├── all_messages.log                      (all Discord messages)
    ├── all_orders.log                        (all IBKR orders)
    └── errors.log                            (all errors)
```

## Features

### ✓ Session-Based Organization
Each trade (started by a NEW event) gets its own log file with all related messages and orders.

### ✓ Dual Format Logs
- **Text logs (.log)** - Human-readable, easy to review
- **JSON logs (.json)** - Structured data for analysis

### ✓ Order Status Tracking
Every order shows:
- Submission details (quantity, price, stops, targets)
- Result status (FILLED ✓, CANCELLED ✗, REJECTED ⚠)
- Order ID and fill price
- Timestamp

### ✓ Paper Trading Support
Paper mode orders are logged the same way, marked as "PAPER" and auto-filled.

### ✓ Complete Audit Trail
- All Discord messages (even non-actionable ones)
- All LLM parsing results
- All risk gate decisions
- All order executions
- All errors

## Quick Usage

### View Today's Activity

```bash
# All Discord messages
cat logs/$(date +%Y-%m-%d)/all_messages.log

# All orders
cat logs/$(date +%Y-%m-%d)/all_orders.log

# Errors
cat logs/$(date +%Y-%m-%d)/errors.log
```

### Live Monitoring

```bash
# Watch orders in real-time
tail -f logs/$(date +%Y-%m-%d)/all_orders.log
```

### Analyze Performance

```bash
# View specific session
cat logs/2025-12-15/session_093045_SPY_CALL.log

# Parse JSON for analysis
cat logs/2025-12-15/session_*.json | jq '.entries[] | select(.type=="order_result")'
```

## Example Session Log

```
================================================================================
TRADING SESSION: abc123
Started: 2025-12-15 14:30:45 UTC
Symbol: SPY CALL
Strike: 685.0 Expiry: 2025-12-15
================================================================================

[DISCORD MESSAGE]
[14:30:45] trader1: bought spy 685 calls @ 0.51
  Message ID: 1234567890

[PARSED EVENT: NEW]
  Confidence: 0.95
  Reasoning: Clear entry signal with SPY 685 CALLS
  Entry Price: $0.51
  Stop Loss: $0.38
  Targets: $0.89

[14:30:48] [ORDER SUBMITTED: NEW]
  quantity: 1
  entry_price: 0.51
  stop_loss: 0.38
  targets: [0.89]

[14:30:52] [ORDER RESULT: NEW] ✓ FILLED
  Order ID: 12345
  Filled Price: $0.51
  Success: True

================================================================================
SESSION CLOSED: TARGET_HIT
Final P&L: +$38.00
================================================================================
```

## Benefits

1. **Accountability** - Complete record of every decision
2. **Debugging** - Easy to trace issues
3. **Analysis** - Review what worked and what didn't
4. **Compliance** - Audit trail for your trading
5. **Learning** - See how messages were interpreted

## Configuration

Logs are stored in `logs/` by default. To change:

```python
# In main.py config:
config = {
    ...
    "log_dir": "/custom/path/to/logs"
}
```

## Privacy

- Logs are **local only** (already in .gitignore)
- Not uploaded to git
- Contain your trading activity
- Keep them secure

## Next Steps

1. Run the bot: `python -m src.orchestrator.main`
2. Send a test Discord message
3. Check `logs/YYYY-MM-DD/all_messages.log`
4. Review the session log that was created

See **LOGGING.md** for complete documentation.

---

**The bot now logs everything. Review logs daily to ensure proper operation!**
