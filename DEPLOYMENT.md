# Deploying AutoScalper to DigitalOcean

## Overview

You have two main options for hosting:
1. **DigitalOcean Droplet** (recommended) - Full VM control
2. **DigitalOcean App Platform** - Managed service (limited for this use case)

**Recommended: Use a Droplet** because you need persistent connections to both Discord and IBKR.

## IBKR Connection Options

### Option 1: Run IBKR Gateway on the Same Server (Recommended)

**Pros:**
- Lowest latency
- Full control
- Works with Droplet

**Cons:**
- Need GUI for initial setup
- Slightly more complex

### Option 2: IBKR Cloud Gateway

**Pros:**
- No local setup needed
- Easier to maintain

**Cons:**
- Not yet widely available
- May have additional costs

### Option 3: Connect to Home IBKR (Not Recommended)

**Pros:**
- Use your existing TWS

**Cons:**
- ❌ Requires VPN or SSH tunnel
- ❌ Home internet dependency
- ❌ Security risks
- ❌ Higher latency

**We'll use Option 1: IBKR Gateway on the Droplet**

## Step-by-Step Deployment

### 1. Create DigitalOcean Droplet

1. Go to https://cloud.digitalocean.com/
2. Click "Create" → "Droplets"
3. **Choose settings:**
   - **Image**: Ubuntu 22.04 LTS
   - **Plan**: Basic
   - **CPU options**: Regular - $12/month (2 GB RAM minimum)
   - **Datacenter**: Choose closest to you (US East recommended)
   - **Authentication**: SSH keys (recommended) or Password
   - **Hostname**: `autoscalper-bot`

4. Click "Create Droplet"
5. Wait for droplet to be created (1-2 minutes)
6. Copy the IP address

### 2. Connect to Your Droplet

```bash
# SSH into your droplet
ssh root@YOUR_DROPLET_IP

# Update system
apt update && apt upgrade -y
```

### 3. Install Dependencies

```bash
# Install Python 3.12
apt install -y python3.12 python3.12-venv python3-pip git

# Install required packages for IBKR Gateway (Java)
apt install -y default-jre

# Install X virtual framebuffer (for headless GUI)
apt install -y xvfb x11vnc

# Install screen for process management
apt install -y screen
```

### 4. Set Up IBKR Gateway on the Server

```bash
# Download IBKR Gateway
cd /opt
wget https://download2.interactivebrokers.com/installers/ibgateway/latest-standalone/ibgateway-latest-standalone-linux-x64.sh

# Make executable
chmod +x ibgateway-latest-standalone-linux-x64.sh

# Install (runs in silent mode)
./ibgateway-latest-standalone-linux-x64.sh -q

# The gateway will be installed to: ~/Jts/ibgateway/
```

### 5. Configure IBKR Gateway

```bash
# Create Gateway config directory
mkdir -p ~/Jts/ibgateway/1019/

# Create jts.ini configuration file
cat > ~/Jts/ibgateway/1019/jts.ini << 'EOF'
[IBGateway]
ApiPort=4001
TrustedIPs=127.0.0.1
ReadOnlyApi=no
EOF
```

**Note:** Port 4001 is for paper trading. For live trading, you'd use 4000.

### 6. Clone Your Bot Code

```bash
# Create app directory
mkdir -p /opt/autoscalper
cd /opt/autoscalper

# Clone or upload your code
# Option A: If using Git
git clone https://github.com/yourusername/AutoScalper.git .

# Option B: Upload from local machine
# On your local machine, run:
# scp -r /path/to/AutoScalper root@YOUR_DROPLET_IP:/opt/autoscalper/
```

### 7. Set Up Python Environment

```bash
cd /opt/autoscalper

# Create virtual environment
python3.12 -m venv venv

# Activate it
source venv/bin/activate

# Install dependencies
pip install -r requirements.txt
```

### 8. Configure Environment Variables

```bash
# Create .env file
nano .env
```

Add your configuration:
```bash
# API Keys
ANTHROPIC_API_KEY=sk-ant-api03-your_key_here
DISCORD_USER_TOKEN=your_discord_token_here
DISCORD_CHANNEL_IDS=123456789
DISCORD_MONITORED_USERS=trader1,trader2

# IBKR Gateway Configuration
IBKR_HOST=127.0.0.1
IBKR_PORT=4001  # 4001 for Gateway paper trading
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

# Mode
PAPER_MODE=true
```

Save with `Ctrl+X`, then `Y`, then `Enter`.

### 9. Create Start Scripts

**Start IBKR Gateway:**
```bash
cat > /opt/autoscalper/start_gateway.sh << 'EOF'
#!/bin/bash
# Start IBKR Gateway with virtual display

# Start Xvfb (virtual display)
Xvfb :1 -screen 0 1024x768x24 &
export DISPLAY=:1

# Wait a moment
sleep 2

# Start IBKR Gateway
cd ~/Jts/ibgateway/1019
./ibgateway &

# Wait for gateway to start
echo "Waiting for IBKR Gateway to start..."
sleep 30

echo "IBKR Gateway should be running. Check logs if issues."
EOF

chmod +x /opt/autoscalper/start_gateway.sh
```

**Start Trading Bot:**
```bash
cat > /opt/autoscalper/start_bot.sh << 'EOF'
#!/bin/bash
cd /opt/autoscalper
source venv/bin/activate
python -m src.orchestrator.main
EOF

chmod +x /opt/autoscalper/start_bot.sh
```

### 10. Run Everything with Screen

Screen lets you keep processes running when you disconnect.

```bash
# Start IBKR Gateway in a screen session
screen -dmS gateway /opt/autoscalper/start_gateway.sh

# Wait for Gateway to fully start
sleep 60

# Start the bot in another screen session
screen -dmS bot /opt/autoscalper/start_bot.sh

# View running screens
screen -ls

# Attach to bot screen to see output
screen -r bot

# Detach: Press Ctrl+A, then D
# Reattach anytime: screen -r bot
```

### 11. Initial IBKR Gateway Login

**Problem:** Gateway needs interactive login first time.

**Solution:** Use VNC to access the virtual display:

```bash
# Start VNC server
x11vnc -display :1 -forever -nopw -listen localhost -xkb &

# Create SSH tunnel from your local machine
# On your LOCAL machine:
ssh -L 5900:localhost:5900 root@YOUR_DROPLET_IP

# Use VNC viewer to connect to localhost:5900
# Login to IBKR Gateway with your credentials
```

**VNC Viewer Options:**
- Mac: Built-in (Safari: vnc://localhost:5900)
- Windows: TightVNC, RealVNC
- Linux: Remmina, TigerVNC

**Once logged in:**
1. Check "Auto-restart" in Gateway
2. Enable "Read-Only API" = NO
3. Add 127.0.0.1 to trusted IPs
4. Gateway will remember credentials

### 12. Monitor Your Bot

```bash
# View bot output
screen -r bot

# View Gateway logs
tail -f ~/Jts/ibgateway/1019/ibgateway.log

# Check if processes are running
ps aux | grep python
ps aux | grep ibgateway

# View system resources
htop
```

## Systemd Service (Auto-Restart on Boot)

For production, use systemd to auto-start:

**Create Gateway Service:**
```bash
sudo nano /etc/systemd/system/ibkr-gateway.service
```

```ini
[Unit]
Description=IBKR Gateway
After=network.target

[Service]
Type=forking
User=root
WorkingDirectory=/opt/autoscalper
ExecStart=/opt/autoscalper/start_gateway.sh
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
```

**Create Bot Service:**
```bash
sudo nano /etc/systemd/system/autoscalper.service
```

```ini
[Unit]
Description=AutoScalper Trading Bot
After=network.target ibkr-gateway.service
Requires=ibkr-gateway.service

[Service]
Type=simple
User=root
WorkingDirectory=/opt/autoscalper
ExecStart=/opt/autoscalper/start_bot.sh
Restart=always
RestartSec=10
Environment="PATH=/opt/autoscalper/venv/bin:/usr/local/bin:/usr/bin:/bin"

[Install]
WantedBy=multi-user.target
```

**Enable and start:**
```bash
# Reload systemd
systemctl daemon-reload

# Enable services (start on boot)
systemctl enable ibkr-gateway.service
systemctl enable autoscalper.service

# Start services
systemctl start ibkr-gateway.service
sleep 60  # Wait for gateway
systemctl start autoscalper.service

# Check status
systemctl status ibkr-gateway.service
systemctl status autoscalper.service

# View logs
journalctl -u autoscalper.service -f
```

## Security Best Practices

### 1. Firewall Setup
```bash
# Install UFW
apt install -y ufw

# Allow SSH
ufw allow 22/tcp

# Enable firewall
ufw enable

# Check status
ufw status
```

### 2. Secure Your .env
```bash
# Ensure .env is not readable by others
chmod 600 /opt/autoscalper/.env
```

### 3. Regular Updates
```bash
# Create update script
cat > /opt/autoscalper/update.sh << 'EOF'
#!/bin/bash
cd /opt/autoscalper
git pull
source venv/bin/activate
pip install -r requirements.txt --upgrade
systemctl restart autoscalper.service
EOF

chmod +x /opt/autoscalper/update.sh
```

### 4. Monitoring & Alerts

**Simple uptime monitoring:**
```bash
# Create health check script
cat > /opt/autoscalper/healthcheck.sh << 'EOF'
#!/bin/bash
if ! systemctl is-active --quiet autoscalper.service; then
    echo "AutoScalper is down!" | mail -s "ALERT: AutoScalper Down" your@email.com
    systemctl restart autoscalper.service
fi
EOF

chmod +x /opt/autoscalper/healthcheck.sh

# Add to crontab (runs every 5 minutes)
crontab -e
# Add this line:
*/5 * * * * /opt/autoscalper/healthcheck.sh
```

## Cost Estimate

**DigitalOcean Droplet:**
- $12/month (2 GB RAM, 1 vCPU)
- $24/month (4 GB RAM, 2 vCPU) - recommended for stability

**Total Monthly Cost:**
- Droplet: $12-24
- Anthropic API: ~$7-45 (depending on usage)
- **Total: ~$20-70/month**

## Troubleshooting

### Gateway Won't Start
```bash
# Check Java is installed
java -version

# Check Gateway logs
tail -50 ~/Jts/ibgateway/1019/ibgateway.log

# Restart with debug
killall java
/opt/autoscalper/start_gateway.sh
```

### Bot Can't Connect to Gateway
```bash
# Check if Gateway is listening
netstat -tulpn | grep 4001

# Test connection
telnet localhost 4001

# Check bot logs
journalctl -u autoscalper.service -n 100
```

### Out of Memory
```bash
# Check memory usage
free -h

# If low, upgrade droplet or add swap
fallocate -l 2G /swapfile
chmod 600 /swapfile
mkswap /swapfile
swapon /swapfile
echo '/swapfile none swap sw 0 0' | tee -a /etc/fstab
```

## Quick Commands Reference

```bash
# Restart bot
systemctl restart autoscalper.service

# View bot logs
journalctl -u autoscalper.service -f

# Restart Gateway
systemctl restart ibkr-gateway.service

# Check everything
systemctl status autoscalper.service
systemctl status ibkr-gateway.service

# SSH into droplet
ssh root@YOUR_DROPLET_IP

# Attach to bot screen (if using screen)
screen -r bot
```

## Next Steps

1. ✅ Set up Droplet
2. ✅ Install IBKR Gateway
3. ✅ Deploy bot code
4. ✅ Configure with VNC for first login
5. ✅ Set up systemd services
6. ✅ Test in paper mode for 1+ week
7. ⚠️ Only then consider live trading (if desired)

## Important Notes

- **Keep paper trading** until you've tested extensively
- **Monitor daily** for the first week
- **Set spending limits** on Anthropic
- **Backup your .env** file securely
- **Never commit .env** to Git
- **Update regularly** but carefully (test changes locally first)

---

Need help? Check the logs first, then review the troubleshooting section.
