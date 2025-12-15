#!/usr/bin/env python3
"""
Utility script to check IBKR account status.

Shows:
- Account balance
- Current positions
- Open orders

Usage:
    python check_ibkr_status.py
"""

import asyncio
import os
from dotenv import load_dotenv
from src.execution import ExecutionEngine


async def main():
    # Load environment
    load_dotenv()

    # Get IBKR connection details
    host = os.getenv("IBKR_HOST", "127.0.0.1")
    port = int(os.getenv("IBKR_PORT", "7497"))  # 7497 = paper, 7496 = live
    client_id = int(os.getenv("IBKR_CLIENT_ID", "1"))

    print(f"Connecting to IBKR at {host}:{port}...")
    print(f"Mode: {'PAPER' if port == 7497 else 'LIVE'}")

    # Create executor
    executor = ExecutionEngine(host=host, port=port, client_id=client_id)

    # Connect
    connected = await executor.connect()
    if not connected:
        print("❌ Failed to connect to IBKR")
        print("\nMake sure:")
        print("  1. TWS or IB Gateway is running")
        print("  2. API connections are enabled in TWS/Gateway settings")
        print("  3. The port matches your TWS/Gateway configuration")
        return

    print("✅ Connected to IBKR\n")

    # Display account status
    await executor.display_account_status()

    # Disconnect
    await executor.disconnect()
    print("Disconnected from IBKR")


if __name__ == "__main__":
    asyncio.run(main())
