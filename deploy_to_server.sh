#!/bin/bash
# Deployment script for AutoScalper on DigitalOcean
# Run this script ON YOUR SERVER (not locally)

set -e  # Exit on error

echo "=========================================="
echo "AutoScalper Deployment Script"
echo "=========================================="
echo ""

# Configuration
APP_DIR="/opt/autoscalper"
REPO_URL="https://github.com/rhit-yangh6/AutoScalper.git"
PYTHON_CMD="python3.12"

# Check if we're root
if [ "$EUID" -ne 0 ]; then
    echo "Please run as root (use: sudo bash deploy_to_server.sh)"
    exit 1
fi

# Step 1: Install system dependencies
echo "1. Installing system dependencies..."
apt update
apt install -y python3.12 python3.12-venv python3-pip git

# Step 2: Clone or update repository
echo ""
echo "2. Setting up application directory..."
if [ -d "$APP_DIR" ]; then
    echo "Directory exists, pulling latest changes..."
    cd "$APP_DIR"
    git pull
else
    echo "Cloning repository..."
    git clone "$REPO_URL" "$APP_DIR"
    cd "$APP_DIR"
fi

# Step 3: Set up Python virtual environment
echo ""
echo "3. Setting up Python virtual environment..."
if [ ! -d "venv" ]; then
    $PYTHON_CMD -m venv venv
fi

# Activate virtual environment
source venv/bin/activate

# Step 4: Install Python dependencies
echo ""
echo "4. Installing Python dependencies..."
pip install --upgrade pip
pip install -r requirements.txt

# Step 5: Create .env file if it doesn't exist
echo ""
echo "5. Setting up configuration..."
if [ ! -f ".env" ]; then
    echo "Creating .env file from template..."
    cat > .env << 'EOF'
# API Keys - REPLACE THESE WITH YOUR ACTUAL KEYS
ANTHROPIC_API_KEY=sk-ant-api03-YOUR_KEY_HERE
DISCORD_USER_TOKEN=YOUR_DISCORD_TOKEN_HERE
DISCORD_CHANNEL_IDS=123456789
DISCORD_MONITORED_USERS=trader1,trader2

# IBKR Gateway Configuration
IBKR_HOST=127.0.0.1
IBKR_PORT=4001
IBKR_CLIENT_ID=1

# Risk Parameters
ACCOUNT_BALANCE=10000
RISK_PER_TRADE_PERCENT=0.5
DAILY_MAX_LOSS_PERCENT=2.0
MAX_CONTRACTS=1
MAX_ADDS_PER_TRADE=1

# Auto Stop Loss & Targets
AUTO_STOP_LOSS_PERCENT=25.0
RISK_REWARD_RATIO=2.0

# Trading Hours (UTC - adjust for ET)
TRADING_HOURS_START=13:30
TRADING_HOURS_END=20:00

# Mode (DRY_RUN=true means no IBKR connection, just simulated trades)
DRY_RUN=true
EOF
    chmod 600 .env
    echo "✓ Created .env file - YOU MUST EDIT THIS FILE WITH YOUR API KEYS!"
    echo "  Run: nano /opt/autoscalper/.env"
else
    echo "✓ .env file already exists"
fi

# Step 6: Create bot startup script
echo ""
echo "6. Creating startup scripts..."
cat > start_bot.sh << 'EOF'
#!/bin/bash
cd /opt/autoscalper
source venv/bin/activate
python -m src.orchestrator.main
EOF
chmod +x start_bot.sh

# Step 7: Create systemd service
echo ""
echo "7. Setting up systemd service..."
cat > /etc/systemd/system/autoscalper.service << 'EOF'
[Unit]
Description=AutoScalper Trading Bot
After=network.target
Wants=network-online.target

[Service]
Type=simple
User=root
WorkingDirectory=/opt/autoscalper
ExecStart=/opt/autoscalper/venv/bin/python -m src.orchestrator.main
Restart=always
RestartSec=10
Environment="PATH=/opt/autoscalper/venv/bin:/usr/local/bin:/usr/bin:/bin"

# Logging
StandardOutput=journal
StandardError=journal
SyslogIdentifier=autoscalper

[Install]
WantedBy=multi-user.target
EOF

# Reload systemd
systemctl daemon-reload

echo ""
echo "=========================================="
echo "✓ Deployment Complete!"
echo "=========================================="
echo ""
echo "NEXT STEPS:"
echo ""
echo "1. Edit the .env file with your API keys:"
echo "   nano /opt/autoscalper/.env"
echo ""
echo "2. Make sure IBKR Gateway is running:"
echo "   netstat -tulpn | grep 4001"
echo ""
echo "3. Test the bot manually first:"
echo "   cd /opt/autoscalper"
echo "   source venv/bin/activate"
echo "   python -m src.orchestrator.main"
echo ""
echo "4. Once working, enable as systemd service:"
echo "   systemctl enable autoscalper.service"
echo "   systemctl start autoscalper.service"
echo ""
echo "5. Monitor the bot:"
echo "   journalctl -u autoscalper.service -f"
echo ""
echo "=========================================="
