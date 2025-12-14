# Interactive Brokers Setup Guide

## What is IBKR_CLIENT_ID?

`IBKR_CLIENT_ID` is just a **unique number you choose** (1-9999) to identify your client connection to TWS/Gateway.

- It's NOT an API key or secret
- It's NOT retrieved from IBKR
- You just pick a number (most people use `1`)
- Different client IDs allow multiple connections simultaneously

**Simple rule**: Use `1` unless you're running multiple bots.

## Step-by-Step TWS/Gateway Setup

### 1. Download and Install

**Interactive Brokers Trader Workstation (TWS)**:
- Download: https://www.interactivebrokers.com/en/trading/tws.php
- Choose your operating system (Windows/Mac/Linux)
- Install and run

**OR Interactive Brokers Gateway** (lighter weight, no GUI):
- Download: https://www.interactivebrokers.com/en/trading/ibgateway-stable.php
- Recommended for automated trading (less resource intensive)

### 2. Create Paper Trading Account

1. Go to https://www.interactivebrokers.com/
2. Log in to your IBKR account
3. Go to Account Management → Settings
4. Request Paper Trading Account (if you don't have one)
5. You'll receive paper trading credentials

**Paper Trading Credentials**:
- Username: Usually your real username + "paper" or similar
- Password: Separate password for paper account
- Account: Paper account number (starts with D or similar)

### 3. Configure TWS/Gateway for API Access

#### Enable API

1. Launch TWS/Gateway and log in to **paper trading**
2. Go to **File → Global Configuration → API → Settings**
3. Configure these settings:

   **Required Settings**:
   - ✅ Enable ActiveX and Socket Clients
   - ✅ Allow connections from localhost only
   - Socket Port: `7497` (for paper trading)
     - Note: `7496` is for LIVE trading
   - Master API Client ID: `0` (default)
   - Read-Only API: ❌ (unchecked - we need to place orders)

   **Trusted IPs**:
   - Add `127.0.0.1` to the list of trusted IPs

   **Optional but Recommended**:
   - ✅ Download open orders on connection
   - ✅ Let API account requests switch to pending orders

4. Click **OK**
5. **Restart TWS/Gateway** for changes to take effect

### 4. Verify Paper Trading Mode

**CRITICAL**: Always verify you're in paper trading mode!

**TWS**:
- Window title should show "Paper Trading" or "Demo"
- Top bar shows paper account number
- Usually displayed in orange/yellow color

**Gateway**:
- Login screen shows "PAPER TRADING" or "DEMO"
- Check account number (paper accounts usually start with D)

### 5. Configuration in AutoScalper

Edit your `.env` file:

```bash
# Interactive Brokers Configuration
IBKR_HOST=127.0.0.1              # Always localhost
IBKR_PORT=7497                   # 7497 = paper, 7496 = live
IBKR_CLIENT_ID=1                 # Just pick 1 (or any number 1-9999)
```

### 6. Test Connection

Create a test script:

```python
from ib_insync import IB

ib = IB()

try:
    # Connect (should match your .env settings)
    ib.connect('127.0.0.1', 7497, clientId=1)
    print("✓ Connected to IBKR successfully!")
    print(f"Account: {ib.managedAccounts()}")

    # Disconnect
    ib.disconnect()
    print("✓ Disconnected")
except Exception as e:
    print(f"✗ Connection failed: {e}")
```

Run it:
```bash
python test_connection.py
```

Expected output:
```
✓ Connected to IBKR successfully!
Account: ['DU123456']  # Your paper account number
✓ Disconnected
```

## Port Numbers Explained

| Port | Mode | Use |
|------|------|-----|
| 7497 | Paper Trading | **Use this for testing** |
| 7496 | Live Trading | Only use after extensive paper trading |
| 4001 | Gateway Paper | If using Gateway instead of TWS (paper) |
| 4000 | Gateway Live | If using Gateway instead of TWS (live) |

**For AutoScalper**: Use `7497` (TWS paper trading)

## Client ID Explained

The client ID is just a number to identify your connection:

- **1 connection**: Use `IBKR_CLIENT_ID=1`
- **Multiple connections**: Use different IDs (1, 2, 3, etc.)
  - Example: Bot #1 uses ID=1, Bot #2 uses ID=2
  - Example: Your bot uses ID=1, your monitoring script uses ID=2

**Most users**: Just use `1`

## Common Issues

### "Connection refused" or "Can't connect"

**Check**:
1. TWS/Gateway is running
2. You're logged in
3. API is enabled (File → Global Configuration → API → Settings)
4. Port is correct (`7497` for paper)
5. `127.0.0.1` is in trusted IPs
6. You restarted TWS after changing settings

### "Not connected" error

**Solution**:
```bash
# Make sure TWS is running first
# Then run your bot
python -m src.orchestrator.main
```

### "Socket port already in use"

**Causes**:
- Another program is using port 7497
- TWS is already running with API enabled
- Previous connection didn't close properly

**Solution**:
1. Close all TWS/Gateway instances
2. Wait 10 seconds
3. Restart TWS
4. Try connecting again

### "API client [ID] already connected"

**Cause**: Another connection is already using that client ID

**Solutions**:
1. Change `IBKR_CLIENT_ID` to a different number (e.g., 2, 3, 4)
2. Or close the other connection first

### Connection works but orders fail

**Check**:
1. "Read-Only API" is UNCHECKED in API settings
2. You're using a paper trading account
3. Account has sufficient (paper) funds
4. Market is open (or use extended hours orders)

## Testing Before Live Trading

### Minimum Paper Trading Period

✅ **Required before going live**:
- [ ] 1+ week of paper trading
- [ ] 50+ successful trades simulated
- [ ] All edge cases tested
- [ ] Risk controls validated
- [ ] No unexpected behavior

### Paper Trading Checklist

- [ ] All messages parsed correctly
- [ ] Positions open as expected
- [ ] Bracket orders (entry + stop + target) work
- [ ] Stops trigger correctly
- [ ] Targets hit and close properly
- [ ] Position sizing is correct
- [ ] Risk limits respected
- [ ] Kill switch works

### Switching to Live Trading

**ONLY after extensive paper trading**:

1. Update `.env`:
   ```bash
   IBKR_PORT=7496  # Change from 7497 to 7496
   PAPER_MODE=false  # Change from true to false
   ```

2. Log in to **LIVE** TWS/Gateway (not paper)

3. **Start with micro size**:
   ```bash
   MAX_CONTRACTS=1  # Start with 1 contract only
   ```

4. **Monitor actively** for first week

## Security Notes

### API Permissions

The API settings give the bot permission to:
- ✅ Read account data
- ✅ Read positions
- ✅ Place orders
- ✅ Cancel orders

**No additional security needed** - the bot can only access:
- Your local machine (127.0.0.1)
- Only when TWS/Gateway is running
- Only the logged-in account

### Stop the Bot

To immediately stop all trading:

1. **Kill switch** (in code):
   ```python
   orchestrator.executor.activate_kill_switch("manual stop")
   ```

2. **Kill the process**:
   ```bash
   Ctrl+C  # or kill the Python process
   ```

3. **Close TWS/Gateway** (nuclear option):
   - Closes API connection immediately
   - Existing orders remain active

4. **Manually close positions** in TWS:
   - Use TWS interface to close positions manually if needed

## Resources

- **IBKR API Docs**: https://interactivebrokers.github.io/tws-api/
- **ib_insync Docs**: https://ib-insync.readthedocs.io/
- **TWS User Guide**: https://www.interactivebrokers.com/en/software/tws/usersguidebook.pdf
- **Paper Trading**: https://www.interactivebrokers.com/en/trading/free-trading-account.php

## Quick Reference

### Common Settings

```bash
# Paper Trading (RECOMMENDED)
IBKR_HOST=127.0.0.1
IBKR_PORT=7497
IBKR_CLIENT_ID=1

# Live Trading (only after extensive paper trading)
IBKR_HOST=127.0.0.1
IBKR_PORT=7496
IBKR_CLIENT_ID=1
```

### TWS API Settings Location

**Windows**: File → Global Configuration → API → Settings
**Mac**: Configure → Settings → API → Settings
**Linux**: File → Global Configuration → API → Settings

### Essential Settings Summary

```
✅ Enable ActiveX and Socket Clients
✅ Socket Port: 7497 (paper) or 7496 (live)
✅ Trusted IPs: 127.0.0.1
❌ Read-Only API: UNCHECKED
```

---

**Key Takeaway**: `IBKR_CLIENT_ID` is just a number you pick (use `1`). The important settings are in TWS under API configuration!
