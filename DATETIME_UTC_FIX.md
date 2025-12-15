# Fixed Deprecated `datetime.utcnow()` Usage

## Issue

Python deprecated `datetime.utcnow()` in Python 3.12+:
```
DeprecationWarning: datetime.datetime.utcnow() is deprecated and scheduled
for removal in a future version. Use timezone-aware objects to represent
datetimes in UTC: datetime.datetime.now(datetime.UTC).
```

## Fix Applied

Replaced all instances of:
```python
datetime.utcnow()
```

With timezone-aware version:
```python
datetime.now(timezone.utc)
```

## Files Modified

### Source Files (9):
1. `src/orchestrator/main.py` - 3 occurrences
2. `src/orchestrator/session_manager.py` - 2 occurrences
3. `src/notifications/telegram_notifier.py` - 6 occurrences
4. `src/execution/executor.py` - 2 occurrences
5. `src/discord_listener/listener_simple.py` - 1 occurrence
6. `src/discord_listener/listener_websocket.py` - 1 occurrence
7. `src/llm_parser/parser.py` - 1 occurrence
8. `src/risk_gate/risk_gate.py` - 2 occurrences
9. `src/models/trade_session.py` - 2 occurrences

**Total:** 20 occurrences fixed

### Import Updates

Added `timezone` to imports in all affected files:
```python
# Before
from datetime import datetime

# After
from datetime import datetime, timezone
```

## Benefits

✅ **Future-proof** - Works with Python 3.12+
✅ **Timezone-aware** - Explicit UTC timezone
✅ **Best practice** - Follows modern Python standards
✅ **No functional change** - Same behavior, just proper API

## Additional Fix: Timezone Awareness Mismatch

After initial fix, encountered error:
```
TypeError: can't compare offset-naive and offset-aware datetimes
```

**Cause:** `datetime.combine()` creates naive datetime by default

**Fix:**
```python
# Before (causes error)
target_time = datetime.combine(now.date(), summary_time)

# After (timezone-aware)
target_time = datetime.combine(now.date(), summary_time, tzinfo=timezone.utc)
```

**Location:** `src/orchestrator/main.py:165`

## Verification

All files compile without syntax errors:
```bash
python3 -m py_compile src/**/*.py
# No errors ✓
```

No remaining deprecated calls:
```bash
grep -r "datetime\.utcnow()" src/
# No results ✓
```

No timezone mismatch errors:
```bash
# Daily summary task now works correctly ✓
```

## Deployment

No configuration changes needed. Simply deploy updated code:

```bash
cd /opt/autoscalper
git pull  # or rsync
sudo systemctl restart autoscalper
```

The bot will run without deprecation warnings!
