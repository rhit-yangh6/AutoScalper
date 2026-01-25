"""
TradingView Webhook Listener

Receives MNQ futures trading signals from TradingView via webhook HTTP server.
TradingView provides buy/sell signals. No bracket orders - positions are naked.
"""

import asyncio
import json
from datetime import datetime, timezone
from typing import Callable, Optional
from aiohttp import web

from src.models.event import Event
from src.models.enums import EventType, PositionSide, RiskLevel


# MNQ tick size
MNQ_TICK_SIZE = 0.25


def round_to_tick(price: float, tick_size: float = MNQ_TICK_SIZE) -> float:
    """Round price to nearest tick size."""
    return round(price / tick_size) * tick_size


class TradingViewListener:
    """
    Webhook listener for TradingView alerts.

    Expected TradingView Alert JSON format:
    {
        "secret": "your_webhook_secret",
        "action": "NEW",           // NEW, ADD, EXIT, CLOSE_ALL
        "symbol": "MNQ",           // Futures symbol (optional, default MNQ)
        "side": "LONG",            // LONG or SHORT (required for NEW/ADD)
        "quantity": 1              // Contracts (optional, default 1)
    }

    Positions are naked - no stop loss or take profit orders.
    TradingView sends EXIT signals when it's time to close.
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
            "service": "TradingView Webhook Listener (MNQ Futures)",
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
            if event.position_side:
                print(f"{event.event_type.value}: {event.symbol} {event.position_side.value} x{event.quantity}")
            else:
                print(f"{event.event_type.value}: {event.symbol}")
            print(f"{'='*60}\n")

            # Send to orchestrator
            if self.on_signal:
                await self.on_signal(event)

            return web.json_response({
                "status": "success",
                "event_type": event.event_type.value,
                "symbol": event.symbol,
                "side": event.position_side.value if event.position_side else None
            })

        except Exception as e:
            print(f"❌ Error processing webhook: {e}")
            import traceback
            traceback.print_exc()
            return web.json_response(
                {"error": str(e)},
                status=500
            )

    def _parse_tradingview_signal(self, payload: dict) -> Optional[Event]:
        """
        Parse TradingView webhook payload into Event object.

        TradingView tells us when to buy/sell. Positions are naked (no brackets).

        Args:
            payload: JSON payload from TradingView

        Returns:
            Event object or None if parsing fails
        """
        try:
            # Required field: action
            action = payload.get('action')
            if not action:
                print(f"❌ Missing required field: action")
                return None

            # Parse event type
            try:
                event_type = EventType[action.upper()]
            except KeyError:
                print(f"❌ Invalid action: {action}. Must be NEW, ADD, EXIT, or CLOSE_ALL")
                return None

            # Get symbol (default MNQ)
            symbol = payload.get('symbol', 'MNQ').upper()

            # For NEW and ADD events, require side only
            position_side = None
            quantity = int(payload.get('quantity', 1))

            if event_type in [EventType.NEW, EventType.ADD]:
                # Required field: side
                side = payload.get('side')

                if not side:
                    print(f"❌ Missing required field for {action}: side")
                    return None

                # Parse position side
                try:
                    position_side = PositionSide[side.upper()]
                except KeyError:
                    print(f"❌ Invalid side: {side}. Must be LONG or SHORT")
                    return None

                print(f"  Signal: {action} {symbol} {side} x{quantity}")

            # Parse risk level (optional)
            risk_level_str = payload.get('risk_level', 'MEDIUM')
            try:
                risk_level = RiskLevel[risk_level_str.upper()]
            except KeyError:
                risk_level = RiskLevel.MEDIUM

            # Build Event
            event = Event(
                event_type=event_type,
                symbol=symbol,
                position_side=position_side,
                entry_price=0.0,  # Will be set from actual fill
                quantity=quantity,
                risk_level=risk_level,
                risk_notes=payload.get('notes', ''),
                message_id=f"tv_{datetime.now(timezone.utc).timestamp()}",
                timestamp=datetime.now(timezone.utc),
                author="TradingView",
                raw_message=json.dumps(payload, indent=2)
            )

            return event

        except Exception as e:
            print(f"❌ Error parsing TradingView signal: {e}")
            import traceback
            traceback.print_exc()
            return None
