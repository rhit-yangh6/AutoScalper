# Deploy Bot to DigitalOcean Server

## Quick Deployment (Recommended)

### Step 1: Transfer deployment script to server

From your **local machine**, run:

```bash
scp deploy_to_server.sh root@YOUR_SERVER_IP:/root/
```

### Step 2: Run deployment script on server

SSH into your server:

```bash
ssh root@YOUR_SERVER_IP
```

Then run the deployment script:

```bash
cd /root
bash deploy_to_server.sh
```

This script will:
- ✓ Install Python 3.12 and dependencies
- ✓ Clone your GitHub repo to `/opt/autoscalper`
- ✓ Set up virtual environment
- ✓ Install all Python packages
- ✓ Create `.env` template file
- ✓ Create startup scripts
- ✓ Set up systemd service

### Step 3: Configure your API keys

Edit the `.env` file with your actual keys:

```bash
nano /opt/autoscalper/.env
```

**Required changes:**
- `ANTHROPIC_API_KEY` - Your Claude API key
- `DISCORD_USER_TOKEN` - Your Discord user token
- `DISCORD_CHANNEL_IDS` - Discord channel IDs to monitor (comma-separated)
- `DISCORD_MONITORED_USERS` - Discord usernames to track (comma-separated)

**Optional changes:**
- Adjust risk parameters if needed
- Change trading hours (currently in UTC)
- Modify account balance

Save with `Ctrl+X`, then `Y`, then `Enter`.

### Step 4: Verify IBKR Gateway is running

```bash
netstat -tulpn | grep 4001
```

You should see:
```
tcp  0  0  127.0.0.1:4001  0.0.0.0:*  LISTEN  [PID]/java
```

If not running, start it:
```bash
bash ~/start_gateway.sh
```

### Step 5: Test the bot manually

Before running as a service, test it manually to catch any errors:

```bash
cd /opt/autoscalper
source venv/bin/activate
python -m src.orchestrator.main
```

**What you should see:**
```
Connected to IBKR at 127.0.0.1:4001
Discord WebSocket connecting...
WebSocket connected
Listening for messages in channels: [123456789]
Monitoring users: ['trader1', 'trader2']
```

If you see errors, check:
- `.env` file has correct values
- IBKR Gateway is running on port 4001
- Discord token is valid
- Anthropic API key is valid

Press `Ctrl+C` to stop.

### Step 6: Run as systemd service (production mode)

Once the manual test works, enable the service:

```bash
# Enable service to start on boot
systemctl enable autoscalper.service

# Start the service
systemctl start autoscalper.service

# Check status
systemctl status autoscalper.service
```

### Step 7: Monitor the bot

View live logs:

```bash
journalctl -u autoscalper.service -f
```

View recent logs:

```bash
journalctl -u autoscalper.service -n 100
```

## Useful Commands

### Service Management

```bash
# Start bot
systemctl start autoscalper.service

# Stop bot
systemctl stop autoscalper.service

# Restart bot
systemctl restart autoscalper.service

# Check status
systemctl status autoscalper.service

# View logs
journalctl -u autoscalper.service -f
```

### Update Bot Code

When you push changes to GitHub:

```bash
cd /opt/autoscalper
git pull
systemctl restart autoscalper.service
```

### Check IBKR Connection

```bash
# Check Gateway is running
ps aux | grep ibgateway

# Check port 4001 is listening
netstat -tulpn | grep 4001

# Test connection
telnet localhost 4001
```

### Emergency Stop

```bash
# Stop bot immediately
systemctl stop autoscalper.service

# Or kill all Python processes (use with caution)
killall python3
```

## Troubleshooting

### Bot won't start

Check logs:
```bash
journalctl -u autoscalper.service -n 50
```

Common issues:
- `.env` file missing or invalid
- IBKR Gateway not running
- Invalid API keys
- Python dependencies not installed

### Can't connect to IBKR

```bash
# Restart Gateway
killall -9 java
bash ~/start_gateway.sh

# Wait 30 seconds, then check
netstat -tulpn | grep 4001
```

### Discord connection issues

- Verify token is valid (test with a simple Discord API call)
- Check channel IDs are correct
- Ensure monitored usernames match exactly (case-sensitive)

### High API costs

Monitor Anthropic usage at: https://console.anthropic.com/

To reduce costs:
- Use fewer monitored channels
- Filter by specific users only
- The LLM is only called for messages from monitored users

## Security Checklist

- ✓ `.env` file has permissions 600 (only root can read)
- ✓ Firewall only allows SSH (port 22)
- ✓ IBKR Gateway only listens on localhost (127.0.0.1)
- ✓ Never commit `.env` to git
- ✓ Paper trading mode enabled initially

## Next Steps

1. **Monitor for 24-48 hours** - Watch logs and verify trades are parsed correctly
2. **Test with real Discord messages** - Send test signals from monitored users
3. **Verify IBKR orders** - Check TWS/Gateway to confirm orders are placed correctly
4. **Review paper trading results** - Analyze performance before considering live trading
5. **Set up alerts** - Configure email/SMS notifications for critical events

---

**Important**: Keep `PAPER_MODE=true` until you've thoroughly tested the system!
