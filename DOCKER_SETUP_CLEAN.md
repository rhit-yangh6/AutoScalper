# Clean Docker Setup - Step by Step

This is a simplified setup that avoids all the networking complexity.

## Architecture

```
┌──────────────────────────┐
│  IB Gateway Container    │
│  Port 4002 → Host:4002   │
└──────────────────────────┘
           ↑
           │ localhost:4002
           │
┌──────────────────────────┐
│  Bot Container           │
│  (host network mode)     │
│  Connects to 127.0.0.1   │
└──────────────────────────┘
```

## Setup Steps

### 1. Upload Files to Droplet

```bash
# On your LOCAL machine
cd /Users/hanyuyang/Documents/Python/AutoScalper

scp docker-compose.clean.yml root@your-droplet-ip:/opt/autoscalper/
scp docker-start.sh root@your-droplet-ip:/opt/autoscalper/
scp test-gateway.sh root@your-droplet-ip:/opt/autoscalper/
```

### 2. Verify .env Configuration

```bash
# SSH into droplet
ssh root@your-droplet-ip
cd /opt/autoscalper

# Check .env has all required values
cat .env | grep -E "IB_USERNAME|IB_PASSWORD|TELEGRAM|DISCORD|ANTHROPIC"
```

Make sure:
- ✅ IB_USERNAME and IB_PASSWORD are correct
- ✅ TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID are set
- ✅ DISCORD_USER_TOKEN is set
- ✅ ANTHROPIC_API_KEY is set

### 3. Start Gateway Only (First)

```bash
# Make scripts executable
chmod +x docker-start.sh test-gateway.sh

# Start just Gateway
docker compose -f docker-compose.clean.yml up -d ibgateway

# Watch Gateway startup logs
docker compose -f docker-compose.clean.yml logs -f ibgateway
```

**Wait for these messages:**
1. `Login attempt: 1`
2. `Click button: Paper Log In`
3. `Login has completed`
4. `Configuration tasks completed`

Press Ctrl+C to stop watching logs.

### 4. Wait 3 Minutes After Login

Gateway needs time after login for API to initialize:

```bash
# Wait 3 minutes
echo "Waiting 180 seconds for API..."
sleep 180
```

### 5. Test Gateway Connection

```bash
# Test if Gateway API is responding
bash test-gateway.sh
```

**Expected output:**
```
✅ Connected successfully!
   Server version: 176
   Accounts: DU...
✅ Gateway is ready for trading bot!
```

**If you see timeout or connection refused:**
- Wait 2 more minutes: `sleep 120 && bash test-gateway.sh`
- Check Gateway logs: `docker compose -f docker-compose.clean.yml logs ibgateway | tail -50`
- Verify credentials in .env
- Check for 2FA approval needed on IBKR Mobile app

### 6. Start the Bot

Once Gateway test succeeds:

```bash
# Build and start bot
docker compose -f docker-compose.clean.yml build bot
docker compose -f docker-compose.clean.yml up -d bot

# Watch bot logs
docker compose -f docker-compose.clean.yml logs -f bot
```

**Expected output:**
```
Connecting to IBKR...
Connection attempt 1/10...
Connected to IBKR at 127.0.0.1:4002
Order monitoring active (bracket fills will be detected)
Starting Discord listener...
Starting daily summary scheduler...
```

## Automatic Startup Script

Or use the automated script that does all steps:

```bash
# Runs all steps automatically
bash docker-start.sh
```

This script:
1. Starts Gateway
2. Waits 3 minutes
3. Tests connection
4. Starts bot only if test succeeds

## Daily Operations

### View Logs

```bash
# Both containers
docker compose -f docker-compose.clean.yml logs -f

# Just Gateway
docker compose -f docker-compose.clean.yml logs -f ibgateway

# Just bot
docker compose -f docker-compose.clean.yml logs -f bot

# Last 50 lines
docker compose -f docker-compose.clean.yml logs --tail=50
```

### Check Status

```bash
docker compose -f docker-compose.clean.yml ps
```

### Restart Bot Only

```bash
docker compose -f docker-compose.clean.yml restart bot
```

### Restart Everything

```bash
docker compose -f docker-compose.clean.yml restart
```

### Stop Everything

```bash
docker compose -f docker-compose.clean.yml down
```

## Troubleshooting

### Gateway test fails with timeout

**Problem:** Gateway API not responding

**Solution:**
```bash
# Wait longer
sleep 180
bash test-gateway.sh

# Check if Gateway logged in successfully
docker compose -f docker-compose.clean.yml logs ibgateway | grep "Login has completed"

# If no login message, check credentials
cat .env | grep IB_USERNAME
cat .env | grep IB_PASSWORD
```

### Bot can't connect

**Problem:** Bot shows connection errors

**Solution:**
```bash
# First verify Gateway works
bash test-gateway.sh

# If Gateway test works but bot doesn't, check bot's environment
docker compose -f docker-compose.clean.yml exec bot printenv | grep IBKR

# Should show:
# IBKR_HOST=127.0.0.1
# IBKR_PORT=4002
```

### Gateway keeps restarting

**Problem:** Wrong credentials or account locked

**Solution:**
```bash
# Check Gateway logs for error
docker compose -f docker-compose.clean.yml logs ibgateway | grep -i "error\|fail\|invalid"

# Common issues:
# - Wrong username/password in .env
# - Account locked (login to IB website first)
# - 2FA required (approve on IBKR Mobile app)
```

### Port already in use

**Problem:** Port 4002 already bound

**Solution:**
```bash
# Find what's using the port
lsof -i :4002

# Kill it
kill -9 <PID>

# Or stop old Gateway
docker stop ibgateway
docker rm ibgateway
```

## Clean Restart

If everything is broken, start fresh:

```bash
# Stop all containers
docker compose -f docker-compose.clean.yml down

# Remove all Docker data
docker system prune -a --volumes -f

# Start from Step 3 again
docker compose -f docker-compose.clean.yml up -d ibgateway
```

## Success Checklist

After setup, you should have:
- ✅ Gateway container running and healthy
- ✅ `test-gateway.sh` shows successful connection
- ✅ Bot container running
- ✅ Bot logs show "Connected to IBKR at 127.0.0.1:4002"
- ✅ No errors in logs

## Next Steps

Once both containers are running:
1. Test with a Discord message (if monitoring channels)
2. Verify Telegram notifications work
3. Check daily summary sends at end of trading hours
4. Monitor for first few days

## Support

If you still have issues:
1. Run `bash test-gateway.sh` and share output
2. Share Gateway logs: `docker compose -f docker-compose.clean.yml logs ibgateway | tail -100`
3. Share bot logs: `docker compose -f docker-compose.clean.yml logs bot | tail -50`
