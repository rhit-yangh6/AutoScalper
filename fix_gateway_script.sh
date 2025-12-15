#!/bin/bash
# Run this on your server to check Gateway structure and create proper startup script

echo "Checking Gateway installation..."
ls -la ~/Jts/
ls -la ~/Jts/ibgateway/

echo ""
echo "Creating improved startup script..."

cat > ~/start_gateway.sh << 'EOF'
#!/bin/bash

# IBKR Gateway Startup Script - Fixed for direct ibgateway folder

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

# Find Gateway directory - handle both ~/Jts/ibgateway and ~/Jts/[version]
if [ -d ~/Jts/ibgateway ]; then
    # Check if there's a version subdirectory
    GATEWAY_VERSION=$(ls -1 ~/Jts/ibgateway/ 2>/dev/null | grep -E '^[0-9]+$' | sort -n | tail -1)

    if [ -n "$GATEWAY_VERSION" ]; then
        GATEWAY_DIR=~/Jts/ibgateway/${GATEWAY_VERSION}
        echo "Found Gateway version: $GATEWAY_VERSION"
    else
        # No version subdir, use ibgateway directly
        GATEWAY_DIR=~/Jts/ibgateway
        echo "Using Gateway directory: ~/Jts/ibgateway"
    fi
else
    # Try old-style numeric version in ~/Jts/
    GATEWAY_VERSION=$(ls -1 ~/Jts/ 2>/dev/null | grep -E '^[0-9]+$' | sort -n | tail -1)
    if [ -z "$GATEWAY_VERSION" ]; then
        echo "ERROR: Gateway not found"
        exit 1
    fi
    GATEWAY_DIR=~/Jts/${GATEWAY_VERSION}
    echo "Found Gateway version: $GATEWAY_VERSION"
fi

echo "Gateway directory: $GATEWAY_DIR"

# Find the actual executable
GATEWAY_EXEC=""
for exec_name in ibgateway ibgateway.sh gw; do
    if [ -f "$GATEWAY_DIR/$exec_name" ]; then
        GATEWAY_EXEC="$GATEWAY_DIR/$exec_name"
        break
    fi
done

if [ -z "$GATEWAY_EXEC" ]; then
    echo "ERROR: Gateway executable not found in $GATEWAY_DIR"
    echo "Directory contents:"
    ls -la "$GATEWAY_DIR"
    exit 1
fi

echo "Gateway executable: $GATEWAY_EXEC"

# Create or update jts.ini
echo "Configuring Gateway..."
mkdir -p "$GATEWAY_DIR"
cat > "$GATEWAY_DIR/jts.ini" << 'INIEOF'
[IBGateway]
ApiPort=4001
TrustedIPs=127.0.0.1
ReadOnlyApi=no
INIEOF

# Start Gateway
echo "Starting IBKR Gateway..."
cd "$GATEWAY_DIR"
"$GATEWAY_EXEC" > /tmp/gateway.log 2>&1 &
GATEWAY_PID=$!

echo "Gateway started with PID: $GATEWAY_PID"
echo "Xvfb PID: $XVFB_PID"

# Wait and check if it's still running
sleep 10

if ! ps -p $GATEWAY_PID > /dev/null 2>&1; then
    echo "ERROR: Gateway crashed!"
    echo "--- Gateway log ---"
    cat /tmp/gateway.log
    echo "--- Directory contents ---"
    ls -la "$GATEWAY_DIR"
    exit 1
fi

echo "✓ Gateway is running"
echo ""
echo "Check logs with:"
echo "  tail -f /tmp/gateway.log"
echo "  tail -f $GATEWAY_DIR/*.log"
echo ""
echo "Connect with VNC for first-time login:"
echo "  x11vnc -display :1 -forever -nopw -listen localhost &"
echo "  Then on your local machine:"
echo "  ssh -L 5900:localhost:5900 root@YOUR_SERVER_IP"
echo "  Open VNC viewer to: localhost:5900"
EOF

chmod +x ~/start_gateway.sh

echo "✓ Script created at ~/start_gateway.sh"
