# LLM-Assisted 0DTE Options Auto-Trading

A safe, deterministic auto-trading system for 0DTE options that uses LLMs for alert parsing and context awareness, while keeping all execution decisions rule-based.

## Core Principles

- Indicators decide entries; LLM never decides entries or exits
- LLM is used only for parsing alerts, labeling events, and adding conservative constraints
- All execution is deterministic and rule-based
- LLM can only reduce risk, never increase it
- Any ambiguity, parsing failure, or rule violation results in NO TRADE

## Setup

```bash
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate
pip install -r requirements.txt
```

## Configuration

1. Copy `config/config.example.yaml` to `config/config.yaml`
2. Set up your `.env` file with API keys:
   ```
   ANTHROPIC_API_KEY=your_key_here
   IBKR_PORT=7497  # 7497 for paper, 7496 for live
   ```

## Project Structure

- `src/models/` - Core data models (Event, TradeSession, enums)
- `src/discord_listener/` - Discord bot for monitoring alerts
- `src/llm_parser/` - LLM-based alert parsing
- `src/risk_gate/` - Risk validation and fail-safes
- `src/execution/` - IBKR order execution
- `src/orchestrator/` - Main coordination logic

## Usage

### 1. Set up environment

```bash
cp .env.example .env
# Edit .env with your API keys and configuration
```

Required configuration:
- `ANTHROPIC_API_KEY` - See **GET_ANTHROPIC_API_KEY.md**
- `DISCORD_USER_TOKEN` - See **GET_DISCORD_TOKEN.md**
- `DISCORD_CHANNEL_IDS` - Right-click Discord channel → Copy ID (comma-separated)
- `IBKR_PORT` - 7497 for paper trading, 7496 for live (see **IBKR_SETUP.md**)
- `IBKR_CLIENT_ID` - Just pick 1 (or any number 1-9999)

### 2. Test the parser

```bash
python -m tests.test_parser
```

This will test if the LLM can correctly parse Discord trading messages.

### 3. Test the session manager

```bash
python -m tests.test_session_manager
```

This tests event correlation and session state management.

### 4. Run the system (Paper Trading)

**CRITICAL: ALWAYS start with paper trading**

```bash
python -m src.orchestrator.main
```

The system will:
1. Connect to Discord and monitor configured channels
2. Parse messages with LLM (Claude)
3. Correlate events to trade sessions
4. Validate with risk gate
5. Execute via IBKR (in paper mode)

### 5. Monitor the output

Watch for:
- `✓` Successful steps
- `✗` Failures and rejections
- `ACTION: NO TRADE` - Safety mechanisms triggered

### Safety Notes

- The system defaults to `PAPER_MODE=true`
- Kill switch available via `executor.activate_kill_switch()`
- Any parsing failure, risk violation, or ambiguity = NO TRADE
- All trades require bracket orders (entry + stop + target)

See proposal.json for detailed system design.
