# Trading Logs Documentation

AutoScalper creates comprehensive logs of all trading activity organized by trading sessions.

## Log Structure

All logs are stored in the `logs/` directory, organized by date:

```
logs/
├── 2025-12-15/
│   ├── session_093045_SPY_CALL.log         # Human-readable session log
│   ├── session_093045_SPY_CALL.json        # Structured session data
│   ├── session_141230_SPX_PUT.log
│   ├── session_141230_SPX_PUT.json
│   ├── all_messages.log                    # All Discord messages for the day
│   ├── all_orders.log                      # All orders for the day
│   └── errors.log                          # All errors for the day
├── 2025-12-16/
│   └── ...
```

## Session Logs

Each trading session gets its own set of log files when a NEW event is created.

### Session Log Filename Format

```
session_HHMMSS_SYMBOL_DIRECTION.log
```

Example: `session_093045_SPY_CALL.log`
- Started at 09:30:45 UTC
- Trading SPY CALL options

### Session Log Contents

Each session log contains:

1. **Header** - Session metadata
2. **Discord Messages** - All messages from the trader
3. **Parsed Events** - LLM interpretation of each message
4. **Order Submissions** - Details of each order sent to IBKR
5. **Order Results** - Fill status, prices, and order IDs
6. **Errors** - Any errors during the session
7. **Footer** - Final P&L and session summary (when closed)

### Example Session Log

```
================================================================================
TRADING SESSION: abc123-def456-ghi789
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
  Quantity: 1
  Risk Level: EXTREME

[14:30:48] [ORDER SUBMITTED: NEW]
  quantity: 1
  entry_price: 0.51
  stop_loss: 0.38
  targets: [0.89]
  underlying: SPY
  strike: 685.0
  expiry: 2025-12-15
  direction: CALL

[14:30:52] [ORDER RESULT: NEW] ✓ FILLED
  Order ID: 12345
  Filled Price: $0.51
  Message: Entry filled at $0.51 | Bracket active: Stop=$0.38 Target=$0.89
  Success: True

[DISCORD MESSAGE]
[14:35:12] trader1: hit target, out
  Message ID: 1234567891

[PARSED EVENT: TP]
  Confidence: 0.92
  Reasoning: Target hit announcement

[14:35:15] [ORDER SUBMITTED: TP]
  quantity: 1
  entry_price: 0.89
  underlying: SPY
  strike: 685.0
  expiry: 2025-12-15
  direction: CALL

[14:35:18] [ORDER RESULT: TP] ✓ FILLED
  Order ID: 12346
  Filled Price: $0.89
  Success: True

================================================================================
SESSION CLOSED: TARGET_HIT
Closed at: 2025-12-15 14:35:18 UTC
Final P&L: +$38.00
Total Events: 2
Total Quantity: 1
================================================================================
```

## Aggregated Logs

### all_messages.log

All Discord messages received during the day, regardless of whether they were actionable:

```
[09:30:45] trader1: bought spy 685 calls @ 0.51
[09:31:20] trader2: watching for reversal
[09:35:42] trader1: hit target, out
```

### all_orders.log

All orders submitted to IBKR during the day:

```
[09:30:48] [NEW] SUBMITTED
  quantity: 1
  entry_price: 0.51
  stop_loss: 0.38
  targets: [0.89]
  underlying: SPY
  strike: 685.0
  expiry: 2025-12-15
  direction: CALL

[09:30:52] [NEW] ✓ FILLED
  Order ID: 12345
  Filled Price: $0.51

[09:35:15] [TP] SUBMITTED
  quantity: 1
  entry_price: 0.89
  underlying: SPY
  strike: 685.0
  expiry: 2025-12-15
  direction: CALL

[09:35:18] [TP] ✓ FILLED
  Order ID: 12346
  Filled Price: $0.89
```

### errors.log

All errors that occurred during the day:

```
[10:15:23] [PARSING_ERROR] Invalid JSON response from LLM
[11:42:10] [EXECUTION_ERROR] Contract not found: SPX 6850C (tried expiries: 2025-12-15, 20251215)
[14:20:05] [CRITICAL_ERROR] Connection lost to IBKR Gateway
```

## JSON Logs

Each session also has a structured JSON log for programmatic access:

### session_*.json Format

```json
{
  "session_id": "abc123-def456-ghi789",
  "entries": [
    {
      "type": "discord_message",
      "timestamp": "2025-12-15T14:30:45.123Z",
      "author": "trader1",
      "message": "bought spy 685 calls @ 0.51",
      "message_id": "1234567890"
    },
    {
      "type": "parsed_event",
      "timestamp": "2025-12-15T14:30:45.456Z",
      "event_type": "NEW",
      "entry_price": 0.51,
      "stop_loss": 0.38,
      "targets": [0.89],
      "quantity": 1,
      "risk_level": "EXTREME",
      "risk_notes": null,
      "parsing_confidence": 0.95,
      "llm_reasoning": "Clear entry signal with SPY 685 CALLS"
    },
    {
      "type": "order_submitted",
      "timestamp": "2025-12-15T14:30:48.789Z",
      "event_type": "NEW",
      "order_details": {
        "quantity": 1,
        "entry_price": 0.51,
        "stop_loss": 0.38,
        "targets": [0.89],
        "underlying": "SPY",
        "strike": 685.0,
        "expiry": "2025-12-15",
        "direction": "CALL"
      }
    },
    {
      "type": "order_result",
      "timestamp": "2025-12-15T14:30:52.123Z",
      "event_type": "NEW",
      "status": "FILLED",
      "success": true,
      "order_id": 12345,
      "filled_price": 0.51,
      "message": "Entry filled at $0.51 | Bracket active: Stop=$0.38 Target=$0.89"
    },
    {
      "type": "session_closed",
      "timestamp": "2025-12-15T14:35:18.456Z",
      "reason": "TARGET_HIT",
      "final_pnl": 38.0,
      "total_events": 2,
      "total_quantity": 1
    }
  ]
}
```

## Order Status Symbols

The logs use visual symbols to quickly identify order status:

- ✓ **FILLED** - Order successfully filled
- ✗ **CANCELLED** - Order was cancelled
- ⚠ **REJECTED** - Order rejected by IBKR
- ⏳ **PENDING** - Order awaiting action
- → **SUBMITTED** - Order submitted to IBKR

## Paper Trading Logs

When running in paper mode (`PAPER_MODE=true`), all orders are simulated:

```
[14:30:48] [ORDER SUBMITTED: NEW]
  quantity: 1
  entry_price: 0.51
  stop_loss: 0.38
  targets: [0.89]
  mode: PAPER

[14:30:48] [ORDER RESULT: NEW] ✓ FILLED
  Filled Price: $0.51
  Message: Simulated fill (paper mode)
  Success: True
```

Orders are logged the same way, but marked as "PAPER" and automatically filled.

## Reviewing Logs

### Daily Summary

To review all trading activity for a day:

```bash
# View all messages
cat logs/2025-12-15/all_messages.log

# View all orders
cat logs/2025-12-15/all_orders.log

# View errors
cat logs/2025-12-15/errors.log
```

### Specific Session

To review a specific trading session:

```bash
# Human-readable log
cat logs/2025-12-15/session_093045_SPY_CALL.log

# Structured JSON
cat logs/2025-12-15/session_093045_SPY_CALL.json | jq
```

### Live Monitoring

To watch logs in real-time while the bot is running:

```bash
# Watch all orders
tail -f logs/$(date +%Y-%m-%d)/all_orders.log

# Watch a specific session (find the latest session)
tail -f logs/$(date +%Y-%m-%d)/session_*.log | tail -1

# Watch errors
tail -f logs/$(date +%Y-%m-%d)/errors.log
```

### Analyzing Performance

Use the JSON logs to analyze performance:

```bash
# Count filled orders for the day
cat logs/2025-12-15/session_*.json | jq '[.entries[] | select(.type=="order_result" and .status=="FILLED")] | length'

# Calculate total P&L
cat logs/2025-12-15/session_*.json | jq '[.entries[] | select(.type=="session_closed") | .final_pnl] | add'

# Find all rejected orders
cat logs/2025-12-15/session_*.json | jq '.entries[] | select(.type=="order_result" and .status=="REJECTED")'
```

## Log Rotation

Logs are automatically organized by date. Each day gets its own directory.

To archive old logs:

```bash
# Archive logs older than 30 days
find logs/ -type d -mtime +30 -exec tar -czf {}.tar.gz {} \; -exec rm -rf {} \;

# Or simply delete old logs
find logs/ -type d -mtime +30 -exec rm -rf {} \;
```

## Disk Space Management

Each session log is typically 5-50 KB depending on activity.

Estimated daily log size:
- Low activity (1-3 trades): ~50-150 KB/day
- Medium activity (5-10 trades): ~250-500 KB/day
- High activity (20+ trades): ~1-2 MB/day

A month of trading:
- Low activity: ~1.5-4.5 MB
- Medium activity: ~7.5-15 MB
- High activity: ~30-60 MB

Logs are very lightweight and don't require aggressive rotation unless you're running for years.

## Privacy & Security

**Important**: Logs contain trading activity and could reveal your strategy.

### Recommendations:

1. **Don't commit logs to git**
   - Already in `.gitignore`
   - Logs are local-only

2. **Secure log files**
   ```bash
   chmod 600 logs/**/*.log
   chmod 600 logs/**/*.json
   ```

3. **Encrypt when archiving**
   ```bash
   tar -czf - logs/2025-12-15/ | gpg -c > logs-2025-12-15.tar.gz.gpg
   ```

4. **Delete locally after upload**
   ```bash
   # After backing up to secure storage
   rm -rf logs/2025-12-*
   ```

## Troubleshooting

### No logs being created

Check that the logs directory exists and is writable:

```bash
ls -la logs/
# Should show current date directory

# If missing, create it:
mkdir -p logs
```

### Session logs not updating

Logs are written in real-time as events occur. If not updating:

1. Check bot is running: `ps aux | grep python`
2. Check for errors in console output
3. Check `logs/YYYY-MM-DD/errors.log`

### JSON logs empty

JSON logs are written when:
- Session closes
- Bot shuts down (flush_all)
- Explicitly flushed

To force flush:
```python
from src.logging import get_logger
logger = get_logger()
logger.flush_all()
```

---

**Logs are your audit trail. Review them daily to ensure the bot is behaving as expected.**
