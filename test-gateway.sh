#!/bin/bash
# Test if Gateway API is ready

echo "Testing Gateway API connection..."
echo ""

python3 << 'EOF'
from ib_insync import IB

ib = IB()
try:
    print("Connecting to 127.0.0.1:4002 (30 second timeout)...")
    ib.connect('127.0.0.1', 4002, clientId=999, timeout=30)

    print("✅ Connected successfully!")
    print(f"   Server version: {ib.client.serverVersion()}")
    print(f"   Connection time: {ib.client.connTime()}")

    # Get account info
    accounts = ib.managedAccounts()
    if accounts:
        print(f"   Accounts: {', '.join(accounts)}")

    ib.disconnect()
    print("\n✅ Gateway is ready for trading bot!")

except TimeoutError:
    print("❌ Timeout - Gateway not responding")
    print("   Gateway might still be initializing. Wait 2 more minutes.")

except ConnectionRefusedError:
    print("❌ Connection refused")
    print("   Gateway is not accepting connections on port 4002")

except Exception as e:
    print(f"❌ Error: {e}")
    import traceback
    traceback.print_exc()
EOF
