#!/bin/bash
# Check what's using IB Gateway ports

echo "Checking port 4001 (Live trading):"
lsof -i :4001 || echo "Port 4001 is free"

echo ""
echo "Checking port 4002 (Paper trading):"
lsof -i :4002 || echo "Port 4002 is free"

echo ""
echo "Checking port 5900 (VNC):"
lsof -i :5900 || echo "Port 5900 is free"

echo ""
echo "All Java processes (IB Gateway typically runs as Java):"
ps aux | grep -i java | grep -v grep
