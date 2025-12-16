# IBKR Gateway + Bot Docker Setup

Minimal setup following ChatGPT's guide for IBKR Gateway on Linux.

## Prerequisites

- Docker and Docker Compose installed
- IBKR account credentials
- API access enabled in IBKR account

## Setup

### 1. Configure Credentials

Edit `.env` file with your credentials:

```bash
IB_USERNAME=your_ibkr_username
IB_PASSWORD=your_ibkr_password
VNC_PASSWORD=changeme
```

### 2. Start Gateway

```bash
# Start Gateway only
docker compose up -d ib-gateway

# Watch logs (wait for "Login completed")
docker logs -f ib-gateway
```

Wait 2-3 minutes for Gateway to initialize.

### 3. Test Connection

```bash
# Test paper trading port
nc -vz 127.0.0.1 4002

# Should show: Connection succeeded
```

### 4. Start Bot

```bash
# Build and start bot
docker compose build bot
docker compose up -d bot

# Watch logs
docker logs -f autoscalper
```

## Connection Ports

- **4002** - Paper trading (default)
- **4001** - Live trading
- **5900** - VNC (optional, for viewing Gateway UI)

## Troubleshooting

### Connection Refused

```bash
# Check Gateway is running
docker ps | grep ib-gateway

# Check ports are listening
ss -lntp | grep -E '4001|4002'
```

### Connection Timeout

Gateway might still be initializing. Wait 2 more minutes:

```bash
sleep 120
nc -vz 127.0.0.1 4002
```

### API Not Enabled

If port is open but connection fails, enable API in Gateway:

1. Connect via VNC: `open vnc://localhost:5900` (password: changeme)
2. Go to API Settings
3. Enable "Enable ActiveX and Socket Clients"
4. Restart Gateway: `docker compose restart ib-gateway`

## Commands

```bash
# View all logs
docker compose logs -f

# View Gateway logs only
docker logs -f ib-gateway

# View bot logs only
docker logs -f autoscalper

# Restart everything
docker compose restart

# Stop everything
docker compose down

# Clean restart
docker compose down
docker system prune -f
docker compose up -d
```

## Success Criteria

✅ `nc -vz 127.0.0.1 4002` succeeds
✅ Bot logs show "Connected to IBKR at 127.0.0.1:4002"
✅ No connection errors in logs

## Security Notes

- Never commit `.env` to git (already in `.gitignore`)
- Use strong VNC password if exposing port 5900
- Test with paper trading first
- Verify account ID matches paper/live mode
