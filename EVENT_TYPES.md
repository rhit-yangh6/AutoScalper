# Event Types Reference

This document explains all event types that can be parsed from Discord trading alerts and how the bot handles them.

---

## Overview

When a Discord message is received, the LLM parser analyzes it and assigns one of **12 event types**. Each event type triggers different behavior in the bot.

### Event Categories

- **Actionable Events**: Trigger order execution (NEW, ADD, TRIM, EXIT, SL, TP, MOVE_STOP)
- **Informational Events**: Logged but no orders placed (PLAN, TARGETS, RISK_NOTE, CANCEL, IGNORE)

---

## Event Types

### 1. NEW - Initial Trade Entry

**Purpose**: Opens a new position

**When Used**:
- Trader announces they've entered a new trade
- Must include underlying (SPY/QQQ), strike price, and direction (CALL/PUT)

**What Happens**:
1. Creates new trade session
2. Validates no other active session exists (one position at a time)
3. Enters position with `INITIAL_CONTRACTS` (default: 1 contract)
4. Creates bracket orders (stop-loss and take-profit)
5. Session state: PENDING → OPEN

**Discord Examples**:
```
"SPY 685C @ 0.50"
"bought QQQ 600P at 1.25"
"in SPY 12/20 690 calls @ 0.43"
"entered SPY 685C, paid 0.51"
```

**Requirements**:
- ✅ Underlying (SPY or QQQ)
- ✅ Strike price (e.g., 685)
- ✅ Direction (CALL or PUT)
- ✅ Entry price (optional, can use market price)
- ⚠️ Must NOT have another active session

**Bot Actions**:
```
1. Risk Gate Validation
   - Check kill switch not active
   - Check within trading hours
   - Check no existing position

2. Calculate Position Size
   - Uses INITIAL_CONTRACTS (fixed, not risk-based)
   - Default: 1 contract

3. Execute Entry Order
   - Paper mode: Market order (delayed data)
   - Live mode: Limit order with 5¢ flexibility

4. Create Bracket Orders
   - Stop-loss order below entry
   - Take-profit order(s) above entry
   - Stores percentage offsets for future ADD operations
```

---

### 2. PLAN - Intent Statement

**Purpose**: Announces future intentions (not actionable)

**When Used**:
- Trader mentions they might do something later
- Permission statements
- Conditional plans

**What Happens**:
1. Event is logged
2. No orders executed
3. Session may be created if this is first mention of a trade

**Discord Examples**:
```
"may add if it dips to 0.40"
"will scale in if we get support"
"watching for entry around 0.50"
"might take profit at 0.80"
```

**Bot Actions**:
- ✅ Logged to session history
- ❌ No order execution
- ℹ️ Informational only

---

### 3. ADD - Scale Into Position

**Purpose**: Adds more contracts to existing position (averages in)

**When Used**:
- Trader adds to their current position
- Must have active OPEN session

**What Happens**:
1. Validates session is OPEN
2. Checks ADD limit not exceeded (`MAX_ADDS_PER_TRADE`)
3. Calculates remaining capacity (`MAX_CONTRACTS - current_quantity`)
4. Submits BUY order for additional contracts
5. Recalculates weighted average entry price
6. Updates bracket orders with new average and quantity
7. Session remains OPEN

**Discord Examples**:
```
"added 1 more @ 0.35"
"adding at 0.40"
"scaled in @ 0.45"
"bought more, avg now 0.48"
```

**Requirements**:
- ✅ Must have OPEN session
- ✅ Must not exceed `MAX_ADDS_PER_TRADE` (default: 1 ADD allowed)
- ✅ Must have remaining capacity under `MAX_CONTRACTS`

**Bot Actions**:
```
1. Calculate ADD Quantity
   - Current: 1 contract @ $0.50
   - Max allowed: 2 contracts (MAX_CONTRACTS)
   - Remaining capacity: 1 contract
   - ADD: 1 contract @ $0.45

2. Execute ADD Order
   - Paper mode: Market order
   - Live mode: Limit order with 5¢ flexibility

3. Update Session
   - New average: (1 × $0.50 + 1 × $0.45) / 2 = $0.475
   - New quantity: 2 contracts
   - Increment num_adds counter

4. Update Brackets
   - Cancel old brackets
   - Calculate new stop/target based on new average
   - Keep same percentage offsets
   - Example: If stop was -10% from $0.50 ($0.45),
             new stop is -10% from $0.475 ($0.4275)
   - Create new brackets for 2 contracts
```

---

### 4. TARGETS - Profit Target Levels

**Purpose**: Sets or updates profit targets (informational)

**When Used**:
- Trader announces price targets
- Can be option premium or underlying stock price

**What Happens**:
1. Targets are parsed and stored in session
2. Target type detected (PREMIUM vs UNDERLYING)
3. No immediate order execution
4. Used for bracket orders if NEW event follows

**Discord Examples**:
```
"targeting 0.65, 0.80"           → PREMIUM targets
"target 1.00"                    → PREMIUM target
"SPY to 687, 688"                → UNDERLYING targets
"QQQ 600 is my target"           → UNDERLYING target
```

**Target Type Detection**:
- **PREMIUM**: Target < 100 (option premium, e.g., $0.65, $6.00)
- **UNDERLYING**: Target > 100 (stock price, e.g., SPY 687, QQQ 600)

**Bot Actions**:
- ✅ Stored in session.targets
- ✅ Used when creating bracket orders
- ❌ No order execution until NEW/ADD
- ℹ️ If UNDERLYING target, will be converted to estimated premium

---

### 5. TRIM - Partial Exit

**Purpose**: Closes part of position (takes partial profit)

**When Used**:
- Trader exits portion of position
- Reduces risk while keeping exposure

**What Happens**:
1. Validates session is OPEN
2. Parses trim quantity (explicit or percentage)
3. Submits SELL order for partial quantity
4. Updates session quantity and realized P&L
5. **If quantity reaches 0**: Auto-closes session
6. **If quantity remains**: Updates brackets for remaining position
7. Session may stay OPEN or close depending on result

**Discord Examples**:
```
"took off half @ 0.65"           → 50% trim
"trimmed 5 contracts at 0.70"    → Explicit quantity
"out of half"                    → 50% trim
"took profit on 3"               → Explicit quantity
```

**Bot Actions**:
```
Scenario 1: Partial Trim (Position Remains)
   Current: 2 contracts @ $0.50 avg
   TRIM: 1 contract @ $0.65

   1. Execute MARKET sell for 1 contract
   2. Calculate P&L: ($0.65 - $0.50) × 1 × 100 = +$15
   3. Update session:
      - total_quantity: 2 → 1
      - realized_pnl: +$15
   4. Update brackets for 1 remaining contract
   5. Session stays OPEN

Scenario 2: Full Trim (Position Closed)
   Current: 1 contract @ $0.50
   TRIM: 1 contract @ $0.70

   1. Execute MARKET sell for 1 contract
   2. Calculate P&L: ($0.70 - $0.50) × 1 × 100 = +$20
   3. Update session:
      - total_quantity: 1 → 0
      - realized_pnl: +$20
      - state: OPEN → CLOSED
      - exit_reason: "TRIM_TO_ZERO"
   4. Cancel all brackets
   5. Session CLOSED
```

---

### 6. MOVE_STOP - Update Stop Loss

**Purpose**: Tightens stop loss to lock in profits

**When Used**:
- Trader moves stop closer to current price
- Risk management adjustment

**What Happens**:
1. ⚠️ **NOT YET IMPLEMENTED**
2. Will cancel old stop order
3. Will create new stop order at updated price

**Discord Examples**:
```
"stop now at 0.55"
"moving stop to breakeven"
"stop to 0.60"
"trailing stop to entry"
```

**Current Status**:
- ❌ Returns "not yet implemented"
- 🔜 Planned for future release

---

### 7. TP - Take Profit Hit

**Purpose**: Announces target was hit (manual exit)

**When Used**:
- Trader manually closed at target
- Target bracket order filled
- Position closed with profit

**What Happens**:
1. Validates session is OPEN
2. Executes full exit with MARKET order
3. Calculates P&L
4. Closes session with exit_reason = "TARGET_HIT"
5. Cancels remaining brackets

**Discord Examples**:
```
"target hit, out at 0.80"
"TP @ 0.75"
"took profit at 0.85"
"out for profit"
```

**Bot Actions**:
```
1. Full Position Exit
   - Submit MARKET sell for all contracts
   - Wait for fill

2. Calculate P&L
   - Current: 2 contracts @ $0.50 avg
   - Exit: $0.80
   - P&L: ($0.80 - $0.50) × 2 × 100 = +$60

3. Close Session
   - state: OPEN → CLOSED
   - exit_reason: "TARGET_HIT"
   - exit_price: $0.80
   - realized_pnl: +$60

4. Cancel Brackets
   - Cancel stop-loss order
   - No more orders active
```

---

### 8. SL - Stop Loss Hit

**Purpose**: Announces stop was hit (manual exit at loss)

**When Used**:
- Trader manually closed at stop
- Stop bracket order filled
- Position closed with loss

**What Happens**:
1. Validates session is OPEN
2. Executes full exit with MARKET order
3. Calculates P&L
4. Closes session with exit_reason = "STOP_HIT"
5. Marks stop as invalidated (prevents future ADDs)
6. Cancels remaining brackets

**Discord Examples**:
```
"stopped out at 0.40"
"stop hit"
"SL @ 0.35"
"took the L at 0.38"
```

**Bot Actions**:
```
1. Full Position Exit
   - Submit MARKET sell for all contracts
   - Wait for fill

2. Calculate P&L
   - Current: 2 contracts @ $0.50 avg
   - Exit: $0.38
   - P&L: ($0.38 - $0.50) × 2 × 100 = -$24

3. Close Session
   - state: OPEN → CLOSED
   - exit_reason: "STOP_HIT"
   - exit_price: $0.38
   - realized_pnl: -$24
   - stop_invalidated: true

4. Update Risk Gate
   - Increment loss_streak
   - Add to daily_pnl
   - Check kill switch conditions
```

---

### 9. EXIT - Manual Full Exit

**Purpose**: Closes entire position (neutral exit)

**When Used**:
- Trader manually closes full position
- Exit for reasons other than TP/SL
- Risk management exit

**What Happens**:
1. Validates session is OPEN
2. Executes full exit with MARKET order
3. Calculates P&L
4. Closes session with exit_reason = "MANUAL_EXIT"
5. Cancels remaining brackets

**Discord Examples**:
```
"closed entire position at 0.60"
"out at 0.55"
"exited all @ 0.58"
"flat now"
"closed for breakeven"
```

**Bot Actions**:
- Same as TP/SL but with exit_reason = "MANUAL_EXIT"
- Does NOT mark stop as invalidated
- Neutral exit (may be profit or loss)

---

### 10. CANCEL - Invalidate Trade

**Purpose**: Cancels trade before entry or invalidates existing position

**When Used**:
- Trader decides not to take the trade
- Scratches the idea before entry
- Changes mind

**What Happens**:
1. If session is PENDING: Changes state to CANCELLED
2. If session is OPEN: Executes full exit and closes session
3. No future events will correlate to this session

**Discord Examples**:
```
"scratch that"
"nevermind, not taking it"
"cancel SPY trade"
"pass on this one"
```

**Bot Actions**:
```
Scenario 1: Before Entry (PENDING session)
   - state: PENDING → CANCELLED
   - No orders to cancel

Scenario 2: After Entry (OPEN session)
   - Execute full exit
   - state: OPEN → CLOSED
   - exit_reason: "CANCELLED"
   - Cancel all brackets
```

---

### 11. RISK_NOTE - Risk Commentary

**Purpose**: Contextual risk information (informational)

**When Used**:
- Trader provides risk warnings
- Market conditions commentary
- Trade caution notes

**What Happens**:
1. Risk note is stored in session
2. May update session.risk_level
3. No order execution
4. Available for future reference

**Discord Examples**:
```
"high theta risk here"
"watch out for volatility"
"size light, this is risky"
"FOMC today, be careful"
```

**Bot Actions**:
- ✅ Stored in session.risk_notes
- ✅ May influence position sizing on NEW events
- ❌ No order execution
- ℹ️ Informational only

---

### 12. IGNORE - Irrelevant Message

**Purpose**: Filters out non-trading chatter

**When Used**:
- General conversation
- Incomplete trade information
- Vague statements without actionable details
- Market commentary without clear entry signal

**What Happens**:
1. Event is logged but not processed
2. No session created
3. No orders executed
4. Message effectively filtered out

**Discord Examples**:
```
"good morning"
"market looking bullish"
"SPY around 0.50"                    → No entry signal
"I am in at 0.50"                    → Missing strike
"might do something later"           → Too vague
"looking at QQQ"                     → No trade details
"UP 50%!"                            → Celebration, not NEW
```

**Bot Actions**:
- ✅ Logged to Discord message history
- ❌ No session created
- ❌ No orders executed
- ℹ️ Filtered as chatter

---

## Event Flow Examples

### Example 1: Complete Trade (Profit Exit)

```
1. NEW Event
   Discord: "SPY 685C @ 0.50"
   Bot: Enter 1 contract @ $0.50, create brackets
   Session: PENDING → OPEN
   Position: 1 contract @ $0.50

2. ADD Event
   Discord: "adding @ 0.45"
   Bot: Add 1 contract @ $0.45, update brackets
   Session: OPEN (remains)
   Position: 2 contracts @ $0.475 avg

3. TRIM Event
   Discord: "took off half @ 0.70"
   Bot: Sell 1 contract @ $0.70 (+$25 realized)
   Session: OPEN (remains)
   Position: 1 contract @ $0.475 avg

4. TP Event
   Discord: "target hit @ 0.80"
   Bot: Sell 1 contract @ $0.80 (+$32.50 realized)
   Session: OPEN → CLOSED
   Position: 0 contracts
   Total P&L: +$57.50
```

---

### Example 2: Stop Loss Trade

```
1. NEW Event
   Discord: "QQQ 600P @ 1.20"
   Bot: Enter 1 contract @ $1.20, create brackets
   Session: OPEN
   Position: 1 contract @ $1.20

2. SL Event
   Discord: "stopped out at 0.85"
   Bot: Sell 1 contract @ $0.85
   Session: OPEN → CLOSED
   Position: 0 contracts
   Total P&L: -$35.00
```

---

### Example 3: Cancelled Before Entry

```
1. PLAN Event
   Discord: "watching SPY 685C around 0.50"
   Bot: Create PENDING session
   Session: PENDING
   Position: None

2. CANCEL Event
   Discord: "scratch that, not taking it"
   Bot: Mark session as cancelled
   Session: PENDING → CANCELLED
   Position: None (never entered)
```

---

## Session State Transitions

```
PENDING → OPEN       (NEW event executed)
PENDING → CANCELLED  (CANCEL before entry)

OPEN → OPEN         (ADD, TRIM partial, TARGETS, RISK_NOTE)
OPEN → CLOSED       (EXIT, TP, SL, TRIM to zero, CANCEL)
```

---

## Risk Gate Validation

Before executing actionable events, the risk gate checks:

1. **Kill Switch**: Not active
2. **Trading Hours**: Within configured window (default: 13:30-20:00 UTC)
3. **Daily Loss Limit**: Not exceeded (`DAILY_MAX_LOSS_PERCENT`)
4. **Loss Streak**: Not exceeded (`MAX_LOSS_STREAK`)
5. **Position Limits**:
   - NEW: No other active session
   - ADD: Not exceeding `MAX_ADDS_PER_TRADE` or `MAX_CONTRACTS`
6. **Stop Invalidation**: Stop not already hit (for ADD events)

---

## Configuration Impact

### Position Sizing

```env
INITIAL_CONTRACTS=1      # Always start with this many (NEW)
MAX_CONTRACTS=2          # Maximum total allowed (NEW + ADDs)
MAX_ADDS_PER_TRADE=1     # How many ADD operations allowed
```

**Example**:
- NEW: Opens with 1 contract
- ADD: Can add 1 more (total: 2)
- 2nd ADD: Rejected (max adds exceeded)

---

## Summary Table

| Event Type | Actionable | Requires Position | Changes Position | Changes Session State |
|------------|-----------|-------------------|------------------|----------------------|
| NEW        | ✅ Yes     | ❌ No              | ✅ Opens          | PENDING → OPEN       |
| PLAN       | ❌ No      | ❌ No              | ❌ No             | - (informational)    |
| ADD        | ✅ Yes     | ✅ Yes             | ✅ Increases      | - (stays OPEN)       |
| TARGETS    | ❌ No      | ❌ No              | ❌ No             | - (informational)    |
| TRIM       | ✅ Yes     | ✅ Yes             | ✅ Decreases      | May close if zero    |
| MOVE_STOP  | ⚠️ WIP     | ✅ Yes             | ❌ No             | - (brackets only)    |
| TP         | ✅ Yes     | ✅ Yes             | ✅ Closes all     | OPEN → CLOSED        |
| SL         | ✅ Yes     | ✅ Yes             | ✅ Closes all     | OPEN → CLOSED        |
| EXIT       | ✅ Yes     | ✅ Yes             | ✅ Closes all     | OPEN → CLOSED        |
| CANCEL     | ✅ Yes     | ❌ No              | ✅ Closes if open | → CANCELLED/CLOSED   |
| RISK_NOTE  | ❌ No      | ❌ No              | ❌ No             | - (informational)    |
| IGNORE     | ❌ No      | ❌ No              | ❌ No             | - (filtered)         |

---

## Related Documentation

- [README.md](README.md) - General setup and usage
- [.env.example](.env.example) - Configuration options
- Risk parameters and position sizing limits
- Bracket order behavior and recalculation
