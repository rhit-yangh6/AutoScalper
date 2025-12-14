# Quick Start Guide

## Prerequisites

1. **Python 3.10+** installed
2. **Anthropic API key** - See GET_ANTHROPIC_API_KEY.md for detailed instructions
3. **Discord user token** - See GET_DISCORD_TOKEN.md for detailed instructions
4. **Interactive Brokers TWS or Gateway** running (paper trading account)

## Step-by-Step Setup

### 1. Install dependencies

```bash
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate
pip install -r requirements.txt
```

### 2. Get Your Discord User Token

See **GET_DISCORD_TOKEN.md** for detailed instructions.

Quick method:
1. Open Discord in browser (discord.com/app)
2. Press F12 → Network tab
3. Refresh page (F5)
4. Click any discord.com/api request
5. Find "authorization:" header
6. Copy the token value

**Security Note**: Never share your token! It gives full access to your Discord account.

### 3. Get Discord Channel ID

1. Enable Developer Mode in Discord (Settings → Advanced → Developer Mode)
2. Right-click the channel you want to monitor
3. Click "Copy ID"

### 4. Configure Environment

```bash
cp .env.example .env
```

Edit `.env`:

```bash
ANTHROPIC_API_KEY=sk-ant-...
DISCORD_USER_TOKEN=your_user_token_here
DISCORD_CHANNEL_IDS=123456789
DISCORD_MONITORED_USERS=trader_username
ACCOUNT_BALANCE=10000
PAPER_MODE=true
```

### 5. Start IBKR TWS

See **IBKR_SETUP.md** for complete instructions.

Quick setup:
1. Open TWS and log in to **paper trading** account
2. File → Global Configuration → API → Settings
3. Enable "Enable ActiveX and Socket Clients"
4. Add `127.0.0.1` to trusted IPs
5. Set Socket port to `7497` (paper trading)
6. Click OK and restart TWS

Note: `IBKR_CLIENT_ID` is just a number you pick (use `1`)

### 6. Test Components

Test the parser:
```bash
python -m tests.test_parser
```

Test the session manager:
```bash
python -m tests.test_session_manager
```

### 7. Run the System

```bash
python -m src.orchestrator.main
```

You should see:
```
============================================================
STARTING AUTOSCALPER
============================================================
Mode: PAPER TRADING
Risk per trade: 0.5%
Daily max loss: 2.0%
Max contracts: 1
============================================================

Connecting to IBKR...
Connected to IBKR at 127.0.0.1:7497
Starting Discord listener...
Discord client logged in as YourUsername#1234
Monitoring 1 channel(s)
```

### 8. Test with a Message

Post a test message in your Discord channel:

```
bought SPY 685C @ 0.43, targeting 686, stop at 0.38
```

You should see the full processing pipeline in the console.

## Troubleshooting

### "Failed to connect to IBKR"
- Make sure TWS is running
- Check that API settings are enabled
- Verify port is 7497 (paper) or 7496 (live)
- Ensure 127.0.0.1 is in trusted IPs

### "Discord client error"
- Verify user token is correct (see GET_DISCORD_TOKEN.md)
- Check that you're a member of the server/channel
- Try getting a fresh token (change password to invalidate old tokens)
- Make sure you're using discord.py-self, not discord.py

### "Parsing failed"
- Check ANTHROPIC_API_KEY is valid
- Ensure you have API credits
- Review the error message for specific issues

### "Risk gate rejection"
- This is expected! The risk gate is very conservative
- Check the failed_checks output to see why
- Adjust risk parameters in .env if needed (but keep conservative)

## Next Steps

1. **Monitor Paper Trading**: Let it run on paper for at least a week
2. **Review Logs**: Check all trades, rejections, and errors
3. **Validate Parsing**: Ensure LLM correctly interprets all message types
4. **Test Edge Cases**: Try malformed messages, rapid updates, etc.
5. **Tune Risk Parameters**: Adjust based on observed behavior

## Safety Reminders

- **NEVER** go live without extensive paper trading
- **ALWAYS** start with minimum position sizes
- **MONITOR** the system actively, especially initially
- **TEST** the kill switch: `orchestrator.executor.activate_kill_switch("test")`
- **UNDERSTAND** that this is experimental software - trade at your own risk

## Support

For issues, check:
1. This guide
2. README.md
3. proposal.json (system design)
4. Source code comments
