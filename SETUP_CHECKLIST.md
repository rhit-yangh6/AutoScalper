# Complete Setup Checklist

Follow this checklist to get AutoScalper up and running.

## 1. Environment Setup

- [x] Python 3.10+ installed
  ```bash
  python --version  # Should show 3.10 or higher
  ```

- [x] Virtual environment created
  ```bash
  python -m venv venv
  source venv/bin/activate  # On Windows: venv\Scripts\activate
  ```

- [x] Dependencies installed
  ```bash
  pip install -r requirements.txt
  ```

## 2. Anthropic API Key

- [x] Account created at https://console.anthropic.com/
- [x] Email verified
- [x] Payment method added
- [x] Spending limit set ($50/month recommended)
- [x] API key created
- [x] API key copied (starts with `sk-ant-api03-...`)

See **GET_ANTHROPIC_API_KEY.md** for detailed instructions.

## 3. Discord Configuration

- [x] Discord account logged in
- [x] User token extracted (see GET_DISCORD_TOKEN.md)
- [x] Developer Mode enabled (Settings → Advanced → Developer Mode)
- [ ] Channel IDs copied (right-click channel → Copy ID)
- [ ] Trader usernames noted (optional, for filtering)

See **GET_DISCORD_TOKEN.md** for detailed instructions.

## 4. Interactive Brokers Setup

See **IBKR_SETUP.md** for detailed instructions.

- [x] TWS or Gateway installed
- [x] Paper trading account created
- [x] TWS/Gateway running
- [ ] API settings enabled:
  - [ ] File → Global Configuration → API → Settings
  - [ ] "Enable ActiveX and Socket Clients" checked
  - [ ] `127.0.0.1` added to trusted IPs
  - [ ] Socket port set to `7497` (paper trading)
- [ ] TWS/Gateway restarted
- [ ] Client ID chosen (use `1` in .env)

## 5. Configuration Files

- [x] `.env` file created
  ```bash
  cp .env.example .env
  ```

- [x] `.env` file populated with:
  - [ ] `ANTHROPIC_API_KEY=sk-ant-api03-...`
  - [ ] `DISCORD_USER_TOKEN=MTA1ODc2...`
  - [ ] `DISCORD_CHANNEL_IDS=123456789,987654321`
  - [ ] `DISCORD_MONITORED_USERS=trader1,trader2` (optional)
  - [ ] `ACCOUNT_BALANCE=10000` (your paper account size)
  - [ ] `PAPER_MODE=true` (CRITICAL - always start with paper)

## 6. Test Components

- [ ] Test LLM parser
  ```bash
  python -m tests.test_parser
  ```
  Expected: Messages parsed successfully, event types identified

- [ ] Test session manager
  ```bash
  python -m tests.test_session_manager
  ```
  Expected: Events correlated to sessions, state transitions working

## 7. Pre-Flight Checks

- [ ] TWS/Gateway is running and logged in
- [ ] Paper trading mode confirmed (check TWS title bar)
- [ ] Discord account accessible
- [ ] Monitored channels visible in Discord
- [ ] All API keys valid (no typos)
- [ ] `.env` file in correct directory
- [ ] Virtual environment activated

## 8. First Run

- [ ] Start the system
  ```bash
  python -m src.orchestrator.main
  ```

- [ ] Verify startup messages:
  ```
  ============================================================
  STARTING AUTOSCALPER
  ============================================================
  Mode: PAPER TRADING  ← CRITICAL: Should say PAPER
  Risk per trade: 0.5%
  Daily max loss: 2.0%
  Max contracts: 1
  ============================================================

  Connecting to IBKR...
  Connected to IBKR at 127.0.0.1:7497  ← Check port 7497 (paper)
  Starting Discord listener...
  Discord client logged in as YourUsername#1234
  Monitoring 1 channel(s)
  ```

- [ ] No error messages appear
- [ ] Discord connection successful
- [ ] IBKR connection successful

## 9. Test Trade Flow

- [ ] Post test message in Discord:
  ```
  bought SPY 685C @ 0.43, targeting 686, stop at 0.38
  ```

- [ ] Verify processing pipeline:
  - [ ] `[1/5] Parsing message with LLM...` → ✓ Parsed as NEW
  - [ ] `[2/5] Correlating to trade session...` → ✓ Linked to session
  - [ ] `[3/5] Validating with risk gate...` → ✓ APPROVE or ✗ REJECT (with reason)
  - [ ] `[4/5] Calculating position size...` → ✓ Position size: X contracts
  - [ ] `[5/5] Executing order...` → [PAPER MODE] Would execute

- [ ] Check for safety triggers:
  - [ ] Risk gate rejections show clear reasons
  - [ ] Paper mode prevents real execution
  - [ ] Failed parsing = NO TRADE

## 10. Monitor for Issues

Run for 1-2 hours and check:

- [ ] All messages from monitored users are captured
- [ ] Parsing succeeds for valid trade messages
- [ ] Parsing gracefully fails for non-trade messages
- [ ] Risk gate blocks inappropriate trades
- [ ] Session correlation works correctly
- [ ] No crashes or unexpected errors

## 11. Paper Trading Period

Before even considering live trading:

- [ ] Run on paper for minimum 1 week
- [ ] Manually verify every trade decision
- [ ] Check all edge cases:
  - [ ] Malformed messages
  - [ ] Rapid message updates
  - [ ] Multiple simultaneous trades
  - [ ] Market closed hours
  - [ ] Invalid tickers/strikes
- [ ] Review all risk gate rejections
- [ ] Confirm bracket orders work correctly
- [ ] Test kill switch: `orchestrator.executor.activate_kill_switch("test")`

## 12. Production Readiness (If Going Live)

**CRITICAL**: Only proceed if you've completed extensive paper trading.

- [ ] Paper trading successful for 1+ week
- [ ] No unexpected behavior observed
- [ ] All risk parameters tuned correctly
- [ ] Account balance sufficient ($10k+ for SPY, $25k+ for SPX)
- [ ] Kill switch tested and working
- [ ] Monitoring/alerting set up
- [ ] Started with micro size (1 contract max)
- [ ] `PAPER_MODE=false` changed consciously

## Troubleshooting Checklist

If something isn't working:

- [ ] Check all API keys are correct (no spaces, complete)
- [ ] Verify TWS/Gateway is running on correct port
- [ ] Confirm Discord token is valid (try getting fresh token)
- [ ] Check .env file is in the right directory
- [ ] Ensure virtual environment is activated
- [ ] Review error messages carefully
- [ ] Check internet connection
- [ ] Verify API credits/billing (Anthropic)
- [ ] Look for rate limiting issues

## Getting Help

1. Review error messages in console
2. Check relevant documentation:
   - GET_ANTHROPIC_API_KEY.md
   - GET_DISCORD_TOKEN.md
   - QUICKSTART.md
   - README.md
3. Review source code comments
4. Check proposal.json for system design

## Safety Reminder

- ⚠️ This is experimental software
- ⚠️ Trade at your own risk
- ⚠️ Start small (1 contract)
- ⚠️ Monitor actively
- ⚠️ Use stop losses
- ⚠️ Paper trade extensively first

---

Once you've completed this checklist, you're ready to run AutoScalper safely!
