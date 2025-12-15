# IBKR Gateway Troubleshooting on DigitalOcean

## Common Issues & Solutions

### Gateway Crashes Immediately

The Gateway needs a virtual display (Xvfb) and proper configuration.

## Step-by-Step Fix

### 1. Check if Xvfb is Running

```bash
# Check if Xvfb is running
ps aux | grep Xvfb

# If not, start it
Xvfb :1 -screen 0 1024x768x24 > /dev/null 2>&1 &
```

### 2. Verify Display Environment

```bash
export DISPLAY=:1

# Test display works
xdpyinfo -display :1

# Should show display info, not an error
```

### 3. Find Gateway Installation

```bash
# Find where Gateway is installed
find ~ -name "ibgateway" -type d

# Common locations:
# ~/Jts/ibgateway/
# ~/ibgateway/
# /opt/ibgateway/

# Check version
ls ~/Jts/
```

### 4. Create Proper Startup Script

Replace the old script with this improved version:

```bash
cat > ~/start_gateway.sh << 'EOF'
#!/bin/bash

# Improved IBKR Gateway Startup Script

# Kill any existing instances
killall -9 java 2>/dev/null
killall -9 Xvfb 2>/dev/null
sleep 2

# Start Xvfb virtual display
echo "Starting virtual display..."
Xvfb :1 -screen 0 1024x768x24 > /tmp/xvfb.log 2>&1 &
XVFB_PID=$!
export DISPLAY=:1

# Wait for display to be ready
sleep 3

# Verify display is working
if ! xdpyinfo -display :1 > /dev/null 2>&1; then
    echo "ERROR: Display :1 not available"
    cat /tmp/xvfb.log
    exit 1
fi
echo "✓ Display ready"

# Find Gateway directory
GATEWAY_VERSION=$(ls -1 ~/Jts/ 2>/dev/null | grep -E '^[0-9]+$' | sort -n | tail -1)
if [ -z "$GATEWAY_VERSION" ]; then
    echo "ERROR: Gateway not found in ~/Jts/"
    exit 1
fi

GATEWAY_DIR=~/Jts/${GATEWAY_VERSION}
echo "Found Gateway version: $GATEWAY_VERSION"
echo "Gateway directory: $GATEWAY_DIR"

# Check if Gateway executable exists
if [ ! -f "$GATEWAY_DIR/ibgateway" ]; then
    echo "ERROR: ibgateway executable not found in $GATEWAY_DIR"
    ls -la "$GATEWAY_DIR"
    exit 1
fi

# Create or update jts.ini
echo "Configuring Gateway..."
cat > "$GATEWAY_DIR/jts.ini" << 'INIEOF'
[IBGateway]
ApiPort=4001
TrustedIPs=127.0.0.1
ReadOnlyApi=no
INIEOF

# Start Gateway
echo "Starting IBKR Gateway..."
cd "$GATEWAY_DIR"
./ibgateway > /tmp/gateway.log 2>&1 &
GATEWAY_PID=$!

echo "Gateway started with PID: $GATEWAY_PID"
echo "Xvfb PID: $XVFB_PID"

# Wait and check if it's still running
sleep 10

if ! ps -p $GATEWAY_PID > /dev/null 2>&1; then
    echo "ERROR: Gateway crashed!"
    echo "--- Gateway log ---"
    cat /tmp/gateway.log
    exit 1
fi

echo "✓ Gateway is running"
echo ""
echo "Check logs with:"
echo "  tail -f /tmp/gateway.log"
echo "  tail -f $GATEWAY_DIR/*.log"
echo ""
echo "Connect with VNC:"
echo "  x11vnc -display :1 -forever -nopw -listen localhost &"
echo "  ssh -L 5900:localhost:5900 root@YOUR_SERVER_IP"
EOF

chmod +x ~/start_gateway.sh
```

### 5. Run the Script Manually First (Debug Mode)

```bash
# Run directly (not in screen) to see errors
bash -x ~/start_gateway.sh
```

Watch for errors. Common issues:

**"Gateway not found":**
```bash
# Install Gateway if missing
cd ~
wget https://download2.interactivebrokers.com/installers/ibgateway/latest-standalone/ibgateway-latest-standalone-linux-x64.sh
chmod +x ibgateway-latest-standalone-linux-x64.sh
./ibgateway-latest-standalone-linux-x64.sh -q
```

**"Display not available":**
```bash
# Install Xvfb if missing
apt update
apt install -y xvfb x11-utils
```

**"Java not found":**
```bash
# Install Java
apt install -y default-jre
java -version
```

### 6. Once Working, Use Screen Properly

```bash
# Create a screen session and run inside it
screen -S gateway

# Inside screen, run:
bash ~/start_gateway.sh

# Detach with: Ctrl+A then D
# Reattach with: screen -r gateway
```

### 7. Check Gateway Logs

```bash
# View live logs
tail -f /tmp/gateway.log

# Check Gateway internal logs
GATEWAY_VERSION=$(ls -1 ~/Jts/ | grep -E '^[0-9]+$' | sort -n | tail -1)
tail -f ~/Jts/${GATEWAY_VERSION}/*.log
```

## Alternative: Use tmux Instead of screen

```bash
# Install tmux (more reliable)
apt install -y tmux

# Start Gateway in tmux
tmux new-session -d -s gateway 'bash ~/start_gateway.sh'

# Attach to see output
tmux attach -t gateway

# Detach: Ctrl+B then D
# List sessions: tmux ls
# Kill session: tmux kill-session -t gateway
```

## VNC Setup for First Login

Gateway needs interactive login the first time:

```bash
# On server - start VNC
x11vnc -display :1 -forever -nopw -listen localhost -xkb > /tmp/vnc.log 2>&1 &

# On your LOCAL machine - create SSH tunnel
ssh -L 5900:localhost:5900 root@YOUR_SERVER_IP

# Connect VNC viewer to: localhost:5900
# Use macOS built-in: open vnc://localhost:5900
# Or use TightVNC, RealVNC, etc.
```

**In VNC:**
1. Login with IBKR credentials
2. Check "Save credentials" or "Auto-login"
3. Enable "Auto-restart"
4. Close VNC once logged in

Gateway will now auto-login on future starts.

## Verify Gateway is Working

```bash
# Check if Gateway is listening on port 4001
netstat -tulpn | grep 4001
# Should show: tcp ... 127.0.0.1:4001 ... LISTEN

# Or use:
ss -tulpn | grep 4001

# Test connection
telnet localhost 4001
# Should connect (Ctrl+C to exit)
```

## Common Error Messages

### "Connection refused" on port 4001
**Problem:** Gateway not started or crashed
**Solution:** Check logs, restart Gateway

### "Display :1 cannot be opened"
**Problem:** Xvfb not running
**Solution:**
```bash
killall Xvfb
Xvfb :1 -screen 0 1024x768x24 &
export DISPLAY=:1
```

### Gateway shows but then disappears
**Problem:** Likely crashing due to missing config or first-time login
**Solution:** Use VNC to complete first-time setup

### "No route to host" when connecting
**Problem:** Firewall or network issue
**Solution:**
```bash
# Gateway should only listen on localhost
# Check:
netstat -tulpn | grep 4001
# Should show: 127.0.0.1:4001 NOT 0.0.0.0:4001
```

## Full Diagnostic Script

```bash
cat > ~/diagnose_gateway.sh << 'EOF'
#!/bin/bash
echo "=== IBKR Gateway Diagnostic ==="
echo ""

echo "1. Checking Java..."
java -version 2>&1 | head -1
echo ""

echo "2. Checking Xvfb..."
if ps aux | grep -v grep | grep Xvfb > /dev/null; then
    echo "✓ Xvfb is running"
    ps aux | grep -v grep | grep Xvfb
else
    echo "✗ Xvfb NOT running"
fi
echo ""

echo "3. Checking Display :1..."
export DISPLAY=:1
if xdpyinfo -display :1 > /dev/null 2>&1; then
    echo "✓ Display :1 is available"
else
    echo "✗ Display :1 NOT available"
fi
echo ""

echo "4. Checking Gateway installation..."
GATEWAY_VERSION=$(ls -1 ~/Jts/ 2>/dev/null | grep -E '^[0-9]+$' | sort -n | tail -1)
if [ -n "$GATEWAY_VERSION" ]; then
    echo "✓ Gateway found: version $GATEWAY_VERSION"
    echo "  Path: ~/Jts/${GATEWAY_VERSION}"
    ls -la ~/Jts/${GATEWAY_VERSION}/ | head -10
else
    echo "✗ Gateway NOT found in ~/Jts/"
fi
echo ""

echo "5. Checking Gateway process..."
if ps aux | grep -v grep | grep ibgateway > /dev/null; then
    echo "✓ Gateway process running"
    ps aux | grep -v grep | grep ibgateway
else
    echo "✗ Gateway process NOT running"
fi
echo ""

echo "6. Checking port 4001..."
if netstat -tulpn 2>/dev/null | grep 4001 > /dev/null || ss -tulpn 2>/dev/null | grep 4001 > /dev/null; then
    echo "✓ Port 4001 is listening"
    netstat -tulpn 2>/dev/null | grep 4001 || ss -tulpn | grep 4001
else
    echo "✗ Port 4001 NOT listening"
fi
echo ""

echo "7. Recent logs..."
if [ -f /tmp/gateway.log ]; then
    echo "Gateway log (last 20 lines):"
    tail -20 /tmp/gateway.log
fi
echo ""

echo "=== End Diagnostic ==="
EOF

chmod +x ~/diagnose_gateway.sh
```

Run it:
```bash
bash ~/diagnose_gateway.sh
```

## Still Not Working?

Try **containerized Gateway** with Docker:

```bash
# Install Docker
curl -fsSL https://get.docker.com -o get-docker.sh
sh get-docker.sh

# Use IBC (IB Controller) Docker image
docker run -d \
  --name ibgateway \
  -p 127.0.0.1:4001:4001 \
  -e TWS_USERID=YOUR_USERNAME \
  -e TWS_PASSWORD=YOUR_PASSWORD \
  -e TRADING_MODE=paper \
  -e VNC_SERVER_PASSWORD=abc123 \
  ghcr.io/unusualalpha/ib-gateway:latest

# Connect to VNC for setup
# Then bot can connect to localhost:4001
```

This is often more reliable than manual Gateway setup.

## Quick Recovery Commands

```bash
# Full restart
killall -9 java Xvfb 2>/dev/null
sleep 2
bash ~/start_gateway.sh

# Check status
bash ~/diagnose_gateway.sh

# View logs
tail -f /tmp/gateway.log
```
