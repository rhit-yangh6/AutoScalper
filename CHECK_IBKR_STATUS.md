# How to Check IBKR Holdings and Open Orders

There are several ways to check your current positions and open orders in Interactive Brokers.

## Method 1: Quick Status Check Script (Recommended)

Run the utility script to see your current account status:

```bash
cd /Users/hanyuyang/Documents/Python/AutoScalper
python check_ibkr_status.py
```

This will show:
- 💰 Account Balance
- 📊 Current Positions (holdings)
- 📋 Open Orders (pending orders)

**Example Output:**
```
============================================================
IBKR ACCOUNT STATUS
============================================================

💰 Account Balance: $10,523.45

📊 Current Positions (2):
  • SPY 600C 12/13/24: 5 contracts @ avg $2.45
  • SPX 5950P 12/13/24: 2 contracts @ avg $15.30

📋 Open Orders (1):
  • BUY 3 SPY 605C @ $3.20 - Submitted

============================================================
```

## Method 2: Via IBKR TWS/Gateway Interface

1. **Open TWS or IB Gateway** (the application you're using to connect)

2. **View Portfolio:**
   - In TWS: Go to "Account" → "Portfolio"
   - Shows all open positions with P&L

3. **View Open Orders:**
   - In TWS: Go to "Trading" → "Order Management"
   - Shows all pending orders with status

## Method 3: Via IBKR Web Portal

1. Go to https://www.interactivebrokers.com
2. Log in to your account
3. Navigate to:
   - **Portfolio** → See all positions
   - **Orders** → See all open/pending orders
   - **Account** → See account balance

## Method 4: Programmatically in Python

If you want to integrate status checking into your own scripts:

```python
import asyncio
from src.execution import ExecutionEngine

async def check_status():
    executor = ExecutionEngine(
        host="127.0.0.1",
        port=7497,  # 7497 = paper, 7496 = live
        client_id=1
    )

    await executor.connect()

    # Get positions
    positions = await executor.get_positions()
    for pos in positions:
        print(f"{pos.contract.localSymbol}: {pos.position} @ ${pos.avgCost}")

    # Get open orders
    orders = await executor.get_open_orders()
    for trade in orders:
        print(f"{trade.order.action} {trade.order.totalQuantity} @ ${trade.order.lmtPrice}")

    await executor.disconnect()

asyncio.run(check_status())
```

## Common Issues

### "Failed to connect to IBKR"
- Make sure TWS or IB Gateway is running
- Check that API connections are enabled:
  - TWS: File → Global Configuration → API → Settings
  - Enable "Enable ActiveX and Socket Clients"
  - Add your IP to trusted IPs (127.0.0.1 for local)

### "No positions" but you have holdings
- Wait a few seconds after connection for data to populate
- Check you're connected to the right account (paper vs live)
- Verify the correct port: 7497 (paper) or 7496 (live)

### Wrong account balance
- Make sure you're connecting to the right port
- Paper account: port 7497
- Live account: port 7496 (be careful!)

## Port Reference

| Port | Account Type | Description |
|------|-------------|-------------|
| 7497 | Paper Trading | Simulated trading with fake money |
| 7496 | Live Trading | **REAL MONEY - BE CAREFUL** |

Check your `.env` file for `IBKR_PORT` to see which you're using.
