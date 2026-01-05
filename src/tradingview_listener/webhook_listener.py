"""
TradingView Webhook Listener

Receives trading signals from TradingView via webhook HTTP server.
Parses structured JSON payloads (no LLM needed).
"""

import asyncio
import hmac
import hashlib
import json
from datetime import datetime, timezone, timedelta
from typing import Callable, Optional
from aiohttp import web

from src.models.event import Event
from src.models.enums import EventType, Direction, RiskLevel


class TradingViewListener:
    """
    Webhook listener for TradingView alerts.

    Expected TradingView Alert JSON format:
    {
        "secret": "your_webhook_secret",
        "action": "NEW",  // NEW or EXIT
        "ticker": "SPY",
        "direction": "PUT",  // PUT or CALL
        "underlying_price": 682.50,  // Current price of SPY (from TradingView)
        "strike_offset": 3.5,  // Optional: Dollars away from current price (default: 3.5)
        "expiry_days": 0,  // Optional: 0 = same day (0DTE), 1 = next day, etc.
        "quantity": 1,  // Optional: default 1
        "risk_level": "EXTREME",  // Optional: LOW, MEDIUM, HIGH, EXTREME
        "notes": "0DTE trade"  // Optional
    }

    AutoScalper AUTO-CALCULATES everything:
    - Strike: underlying_price ± strike_offset, rounded to nearest $5
    - Expiry: Today + expiry_days (default 0 for 0DTE)
    - Option Premium: Fetched from IBKR market data (real-time quote)
    - Stop Loss: Auto-calculated from AUTO_STOP_LOSS_PERCENT config
    - Target: Auto-calculated from RISK_REWARD_RATIO config
    """

    def __init__(
        self,
        port: int,
        webhook_secret: str,
        on_signal: Callable[[Event], None],
    ):
        """
        Initialize TradingView webhook listener.

        Args:
            port: Port to run webhook server on
            webhook_secret: Secret key for webhook authentication
            on_signal: Callback function when valid signal received
        """
        self.port = port
        self.webhook_secret = webhook_secret
        self.on_signal = on_signal
        self.app = web.Application()
        self.runner: Optional[web.AppRunner] = None
        self.running = False

        # Setup routes
        self.app.router.add_post('/webhook', self._handle_webhook)
        self.app.router.add_get('/health', self._handle_health)

    async def start(self):
        """Start the webhook server."""
        print(f"Starting TradingView webhook listener on port {self.port}...")

        self.runner = web.AppRunner(self.app)
        await self.runner.setup()

        site = web.TCPSite(self.runner, '0.0.0.0', self.port)
        await site.start()

        self.running = True
        print(f"✓ TradingView webhook listening on http://0.0.0.0:{self.port}/webhook")
        print(f"  Health check: http://0.0.0.0:{self.port}/health")
        print(f"  Webhook secret configured: {self.webhook_secret[:8]}...")

    async def stop(self):
        """Stop the webhook server."""
        self.running = False
        if self.runner:
            await self.runner.cleanup()
        print("TradingView webhook listener stopped")

    async def _handle_health(self, request: web.Request) -> web.Response:
        """Health check endpoint."""
        return web.json_response({
            "status": "healthy",
            "service": "TradingView Webhook Listener",
            "timestamp": datetime.now(timezone.utc).isoformat()
        })

    async def _handle_webhook(self, request: web.Request) -> web.Response:
        """
        Handle incoming webhook from TradingView.

        Returns:
            HTTP 200 if signal processed
            HTTP 401 if authentication failed
            HTTP 400 if invalid payload
        """
        try:
            # Parse JSON payload
            try:
                payload = await request.json()
            except json.JSONDecodeError:
                print("❌ Invalid JSON payload")
                return web.json_response(
                    {"error": "Invalid JSON"},
                    status=400
                )

            # Authenticate webhook
            webhook_secret = payload.get('secret')
            if webhook_secret != self.webhook_secret:
                print(f"❌ Webhook authentication failed")
                return web.json_response(
                    {"error": "Invalid secret"},
                    status=401
                )

            # Parse and validate signal
            event = self._parse_tradingview_signal(payload)

            if not event:
                print(f"❌ Failed to parse signal: {payload}")
                return web.json_response(
                    {"error": "Invalid signal format"},
                    status=400
                )

            # Log received signal
            print(f"\n{'='*60}")
            print(f"[TRADINGVIEW SIGNAL]")
            print(f"Action: {event.event_type.value}")
            print(f"Ticker: {event.underlying} {event.strike}{event.direction.value[0]} {event.expiry}")
            print(f"Entry: ${event.entry_price:.2f}")
            if event.stop_loss:
                print(f"Stop: ${event.stop_loss:.2f}")
            if event.target_price:
                print(f"Target: ${event.target_price:.2f}")
            print(f"{'='*60}\n")

            # Send to orchestrator
            if self.on_signal:
                await self.on_signal(event)

            return web.json_response({
                "status": "success",
                "event_type": event.event_type.value,
                "ticker": f"{event.underlying} {event.strike}{event.direction.value[0]}"
            })

        except Exception as e:
            print(f"❌ Error processing webhook: {e}")
            return web.json_response(
                {"error": str(e)},
                status=500
            )

    def _parse_tradingview_signal(self, payload: dict) -> Optional[Event]:
        """
        Parse TradingView webhook payload into Event object.

        Auto-calculates strike and expiry based on underlying price.

        Args:
            payload: JSON payload from TradingView

        Returns:
            Event object or None if parsing fails
        """
        try:
            # Required fields
            action = payload.get('action')
            ticker = payload.get('ticker')
            direction = payload.get('direction')
            underlying_price = payload.get('underlying_price')

            if not all([action, ticker, direction, underlying_price]):
                print(f"❌ Missing required fields: action, ticker, direction, underlying_price")
                return None

            # Parse event type
            try:
                event_type = EventType[action.upper()]
            except KeyError:
                print(f"❌ Invalid action: {action}. Must be NEW or EXIT")
                return None

            # Parse direction
            try:
                option_direction = Direction[direction.upper()]
            except KeyError:
                print(f"❌ Invalid direction: {direction}. Must be PUT or CALL")
                return None

            underlying_price = float(underlying_price)

            # Calculate strike price (3-4 dollars away from current, rounded to nearest $5)
            strike_offset = float(payload.get('strike_offset', 3.5))  # Default 3.5 dollars
            strike = self._calculate_strike(underlying_price, option_direction, strike_offset)

            # Calculate expiry date
            expiry_days = int(payload.get('expiry_days', 0))  # Default 0DTE
            expiry = self._calculate_expiry(expiry_days)

            print(f"  Calculated strike: ${strike:.2f} (underlying ${underlying_price:.2f}, offset ${strike_offset:.2f})")
            print(f"  Calculated expiry: {expiry} ({expiry_days} days from today)")

            # Parse risk level (optional)
            risk_level_str = payload.get('risk_level', 'EXTREME')  # Default EXTREME for options
            try:
                risk_level = RiskLevel[risk_level_str.upper()]
            except KeyError:
                risk_level = RiskLevel.EXTREME

            # Build Event
            # Note: entry_price, stop_loss, and target_price are left as 0/None
            # The execution engine will:
            # - Fetch real-time option premium from IBKR
            # - Auto-calculate stop loss from AUTO_STOP_LOSS_PERCENT
            # - Auto-calculate target from RISK_REWARD_RATIO
            event = Event(
                event_type=event_type,
                underlying=ticker.upper(),
                strike=strike,
                direction=option_direction,
                expiry=expiry,
                entry_price=0,  # Will be fetched from IBKR market data
                stop_loss=None,  # Will be auto-calculated
                target_price=None,  # Will be auto-calculated
                quantity=int(payload.get('quantity', 1)),
                risk_level=risk_level,
                risk_notes=payload.get('notes', ''),
                confidence=1.0,  # Structured data = 100% confidence
                reasoning=f"TradingView signal: {action} {ticker} {strike:.0f}{direction[0]} (underlying ${underlying_price:.2f})",
                message_id=f"tv_{datetime.now(timezone.utc).timestamp()}",
                timestamp=datetime.now(timezone.utc),
                raw_text=json.dumps(payload, indent=2)
            )

            return event

        except Exception as e:
            print(f"❌ Error parsing TradingView signal: {e}")
            import traceback
            traceback.print_exc()
            return None

    def _calculate_strike(self, underlying_price: float, direction: Direction, offset: float) -> float:
        """
        Calculate option strike price based on underlying price and direction.

        Args:
            underlying_price: Current price of underlying (e.g., SPY at 682.50)
            direction: CALL or PUT
            offset: Dollars away from current price (e.g., 3.5)

        Returns:
            Strike price rounded to nearest $5 (standard for index options)

        Examples:
            underlying_price=682.50, direction=PUT, offset=3.5
            → 682.50 - 3.5 = 679.0 → rounds to 680.0

            underlying_price=682.50, direction=CALL, offset=3.5
            → 682.50 + 3.5 = 686.0 → rounds to 685.0
        """
        if direction == Direction.PUT:
            # For puts, strike below current price
            raw_strike = underlying_price - offset
        else:
            # For calls, strike above current price
            raw_strike = underlying_price + offset

        # Round to nearest $5 (standard for SPY/QQQ)
        # For smaller tickers, you might want $1 or $2.50 increments
        strike = round(raw_strike / 5) * 5

        return float(strike)

    def _calculate_expiry(self, days_offset: int = 0) -> str:
        """
        Calculate option expiry date.

        Args:
            days_offset: Days from today (0 = today for 0DTE, 1 = tomorrow, etc.)

        Returns:
            Expiry date in YYYY-MM-DD format

        Examples:
            days_offset=0 → "2025-12-24" (today, 0DTE)
            days_offset=7 → "2025-12-31" (next week)
        """
        expiry_date = datetime.now(timezone.utc).date() + timedelta(days=days_offset)
        return expiry_date.strftime('%Y-%m-%d')
