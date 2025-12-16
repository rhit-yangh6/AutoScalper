# Docker Setup for IB Gateway

This setup runs IB Gateway in a Docker container with automatic login and restart capabilities.

## Architecture

```
┌─────────────────────────────────────┐
│  Docker Container: ibgateway        │
│  ┌──────────────────────────────┐   │
│  │  IB Gateway                  │   │
│  │  + IB Controller (IBC)       │   │
│  │  = Auto-login on restart     │   │
│  └──────────────────────────────┘   │
│  Ports: 4002 (paper), 4001 (live)   │
└─────────────────────────────────────┘
           ↓ API Connection
┌─────────────────────────────────────┐
│  Your Trading Bot (AutoScalper)     │
│  Host: ibgateway (or localhost)     │
│  Port: 4002                         │
└─────────────────────────────────────┘
```

## Prerequisites

1. **Docker & Docker Compose** installed
2. **Interactive Brokers account** (paper or live)
3. **API access enabled** in IB account settings

## Setup Instructions

### 1. Configure Credentials

Add your IB credentials to `.env`:

```bash
# Copy example and edit
cp .env.example .env
nano .env
```

Add:
```
IB_USERNAME=your_ib_username
IB_PASSWORD=your_ib_password
VNC_PASSWORD=ibgateway  # Optional, for remote viewing
```

### 2. Create Settings Directory

```bash
mkdir -p docker/ibgateway/settings
```

This directory will persist Gateway settings across restarts.

### 3. Start IB Gateway Container

```bash
# Start in detached mode
docker-compose up -d ibgateway

# View logs
docker-compose logs -f ibgateway
```

**First startup takes 60-90 seconds** while Gateway initializes.

### 4. Verify Gateway is Running

```bash
# Check container status
docker-compose ps

# Should show:
# NAME        STATUS         PORTS
# ibgateway   Up (healthy)   0.0.0.0:4002->4002/tcp
```

### 5. Update Bot Configuration

If running bot **outside Docker** (on host machine):

```bash
# .env
IBKR_HOST=127.0.0.1  # or localhost
IBKR_PORT=4002       # Paper trading
```

If running bot **inside Docker** (uncomment bot service in docker-compose.yml):

```bash
# .env
IBKR_HOST=ibgateway  # Container name
IBKR_PORT=4002
```

### 6. Start Your Bot

```bash
# If running on host
python -m src.orchestrator.main

# If running in Docker
docker-compose up -d bot
```

## Port Reference

| Port | Purpose                  | Mode  |
|------|--------------------------|-------|
| 4002 | Gateway API (Paper)      | Paper |
| 4001 | Gateway API (Live)       | Live  |
| 5900 | VNC (Remote UI viewing)  | Both  |

## Remote Viewing (Optional)

Connect to Gateway UI using VNC:

```bash
# macOS: use built-in Screen Sharing
open vnc://localhost:5900

# Linux: use any VNC client
vncviewer localhost:5900

# Password: value of VNC_PASSWORD from .env
```

Useful for debugging or manual configuration.

## Credentials Security

**Important Security Notes:**

1. **Never commit `.env` to git** - it's in `.gitignore`
2. **Use paper trading** for testing
3. **Restrict API permissions** in IB account settings:
   - Settings → API → Read-Only (if not trading manually)
   - Settings → API → Allow orders only from this IP

4. **Rotate passwords** regularly

## Switching Paper ↔ Live

Edit `docker-compose.yml`:

```yaml
environment:
  TRADING_MODE: paper  # Change to "live" for production
```

Then update bot's `.env`:

```bash
PAPER_MODE=false  # For live trading
IBKR_PORT=4001    # Live port
```

Restart:
```bash
docker-compose restart ibgateway
```

## Troubleshooting

### Gateway won't start

```bash
# Check logs
docker-compose logs ibgateway

# Common issues:
# 1. Invalid credentials → Check IB_USERNAME/IB_PASSWORD
# 2. Account locked → Login to IB website first
# 3. 2FA required → See "2FA Setup" below
```

### Bot can't connect

```bash
# Test connection from host
nc -zv localhost 4002

# If fails:
# 1. Check container is running: docker-compose ps
# 2. Check port mapping: docker-compose ps (should show 0.0.0.0:4002)
# 3. Check Gateway logs: docker-compose logs ibgateway
```

### Gateway restarts but doesn't auto-login

Check credentials in `.env` and restart:

```bash
docker-compose down
docker-compose up -d
```

### 2FA Setup

If your account has 2FA enabled:

1. **IB Key (IBKR Mobile)** - Recommended:
   - Gateway will wait for mobile app approval
   - Approve login on IBKR Mobile app when prompted
   - IBC will retry if timeout occurs

2. **Security Card**:
   - Not recommended for Docker - requires manual input
   - Disable for API trading accounts

## Maintenance

### View Gateway Status

```bash
# Container status
docker-compose ps

# Real-time logs
docker-compose logs -f ibgateway

# Resource usage
docker stats ibgateway
```

### Restart Gateway

```bash
# Graceful restart
docker-compose restart ibgateway

# Full restart (clears state)
docker-compose down
docker-compose up -d
```

### Update Gateway Image

```bash
# Pull latest image
docker-compose pull ibgateway

# Restart with new image
docker-compose up -d ibgateway
```

### Backup Settings

```bash
# Backup Gateway configuration
tar -czf ibgateway-backup.tar.gz docker/ibgateway/settings/

# Restore
tar -xzf ibgateway-backup.tar.gz
```

## Auto-Restart Behavior

The container is configured with `restart: unless-stopped`, meaning:

- ✅ Restarts on crash
- ✅ Restarts on Docker daemon restart
- ✅ Restarts on host reboot
- ✅ Auto-login on every restart
- ❌ Won't restart if manually stopped (`docker-compose stop`)

Combined with your bot's auto-reconnection logic, this provides full resilience:

1. **Gateway crashes** → Docker restarts container → IBC auto-logins → Bot reconnects
2. **Network issue** → Bot's reconnection logic handles it
3. **Host reboot** → Docker starts container → IBC auto-logins → Bot reconnects

## Production Deployment

For production on a VPS/server:

```bash
# 1. Install Docker
curl -fsSL https://get.docker.com | sh

# 2. Clone your repo
git clone <your-repo>
cd AutoScalper

# 3. Configure .env
nano .env

# 4. Start everything
docker-compose up -d

# 5. Enable logging
docker-compose logs -f > gateway.log 2>&1 &

# 6. Set up monitoring (optional)
# Use external monitoring service to ping your bot
```

## Advanced: Run Bot in Docker Too

Uncomment the `bot` service in `docker-compose.yml` to run everything in Docker:

```yaml
services:
  ibgateway:
    # ... existing config ...

  bot:
    build: .
    container_name: autoscalper
    restart: unless-stopped
    depends_on:
      - ibgateway
    environment:
      IBKR_HOST: ibgateway  # Use container name
      IBKR_PORT: 4002
    volumes:
      - ./logs:/app/logs
      - ./.env:/app/.env
```

Then create `Dockerfile`:

```dockerfile
FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

CMD ["python", "-m", "src.orchestrator.main"]
```

Start both:
```bash
docker-compose up -d
```

## References

- **IB Gateway Docker Image**: https://github.com/gnzsnz/ib-gateway-docker
- **IB Controller (IBC)**: https://github.com/IbcAlpha/IBC
- **IBKR API Docs**: https://interactivebrokers.github.io/tws-api/

## Support

If you encounter issues:

1. Check logs: `docker-compose logs ibgateway`
2. Verify credentials in `.env`
3. Test connection: `nc -zv localhost 4002`
4. Check IB account settings (API enabled, IP whitelisted)
5. Try VNC to view Gateway UI: `open vnc://localhost:5900`
