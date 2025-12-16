#!/bin/bash
# Clean Docker startup script for AutoScalper

set -e

echo "========================================="
echo "  AutoScalper Docker Setup"
echo "========================================="
echo ""

cd /opt/autoscalper

# Step 1: Start Gateway
echo "Step 1: Starting IB Gateway..."
docker compose -f docker-compose.clean.yml up -d ibgateway

echo ""
echo "Waiting for Gateway to initialize (this takes 2-3 minutes)..."
echo "Progress:"

for i in {1..180}; do
    echo -n "."
    sleep 1
    if [ $((i % 30)) -eq 0 ]; then
        echo " ${i}s"
    fi
done
echo ""

# Step 2: Check Gateway logs
echo ""
echo "Step 2: Checking Gateway status..."
docker compose -f docker-compose.clean.yml logs ibgateway | tail -30

# Step 3: Test connection
echo ""
echo "Step 3: Testing API connection..."

python3 << 'EOF'
from ib_insync import IB
import sys

ib = IB()
try:
    print("Attempting connection to 127.0.0.1:4002...")
    ib.connect('127.0.0.1', 4002, clientId=999, timeout=30)
    print("✅ SUCCESS! Gateway API is ready")
    print(f"Server version: {ib.client.serverVersion()}")
    ib.disconnect()
    sys.exit(0)
except Exception as e:
    print(f"❌ FAILED: {e}")
    print("\nGateway is not ready yet. Possible issues:")
    print("1. Gateway still initializing (wait 2 more minutes)")
    print("2. Wrong credentials in .env")
    print("3. 2FA required (check IBKR Mobile app)")
    sys.exit(1)
EOF

if [ $? -eq 0 ]; then
    echo ""
    echo "Step 4: Starting trading bot..."
    docker compose -f docker-compose.clean.yml up -d bot

    echo ""
    echo "========================================="
    echo "  ✅ Both containers running!"
    echo "========================================="
    echo ""
    echo "Monitor logs:"
    echo "  docker compose -f docker-compose.clean.yml logs -f"
    echo ""
    echo "Check status:"
    echo "  docker compose -f docker-compose.clean.yml ps"
    echo ""
else
    echo ""
    echo "❌ Gateway API not ready. Not starting bot."
    echo ""
    echo "To retry after waiting:"
    echo "  bash docker-start.sh"
    echo ""
    echo "To view Gateway logs:"
    echo "  docker compose -f docker-compose.clean.yml logs ibgateway"
fi
