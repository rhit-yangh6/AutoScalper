"""
Daily snapshot manager for tracking account balance at market open.

Creates daily snapshots of account balance at trading_hours_start to enable
accurate daily P&L tracking even when the bot restarts during the day.
"""

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional


class DailySnapshotManager:
    """
    Manages daily account balance snapshots.

    Snapshots are taken at trading_hours_start (market open) and stored in
    logs/YYYY-MM-DD/daily_snapshot.json. This enables the daily summary to
    calculate accurate P&L and daily change even after bot restarts.

    Features:
    - Takes snapshot at configured trading_hours_start time
    - Gets balance from IBKR (both paper and live modes)
    - Falls back to config balance if IBKR unavailable
    - Prevents duplicate snapshots on the same day
    - Handles late starts (bot started after market open)
    """

    def __init__(self, base_dir: str = "logs"):
        """
        Initialize snapshot manager.

        Args:
            base_dir: Base directory for logs (default: "logs")
        """
        self.base_dir = Path(base_dir)

    def _get_day_dir(self, date_str: str) -> Path:
        """
        Get directory path for a specific date.

        Args:
            date_str: Date in YYYY-MM-DD format

        Returns:
            Path to the day's log directory
        """
        return self.base_dir / date_str

    def _get_snapshot_path(self, date_str: str) -> Path:
        """
        Get snapshot file path for a specific date.

        Args:
            date_str: Date in YYYY-MM-DD format

        Returns:
            Path to the snapshot file
        """
        return self._get_day_dir(date_str) / "daily_snapshot.json"

    async def take_snapshot(
        self,
        executor,
        paper_mode: bool,
        account_balance_config: float,
        trading_hours_start: str
    ) -> Optional[dict]:
        """
        Take daily snapshot if one doesn't exist for today.

        Args:
            executor: ExecutionEngine instance
            paper_mode: Whether running in paper trading mode
            account_balance_config: Configured account balance (fallback)
            trading_hours_start: Trading hours start time (HH:MM format)

        Returns:
            Snapshot dict if created, None if already exists
        """
        # Get today's date
        now = datetime.now(timezone.utc)
        date_str = now.date().isoformat()

        # Check if snapshot already exists
        snapshot_path = self._get_snapshot_path(date_str)
        if snapshot_path.exists():
            print(f"Snapshot already exists for {date_str}, skipping")
            return None

        # Ensure day directory exists
        day_dir = self._get_day_dir(date_str)
        day_dir.mkdir(parents=True, exist_ok=True)

        # Try to get balance from IBKR
        account_balance = None
        balance_source = "CONFIG_FALLBACK"
        ibkr_connected = False

        try:
            if hasattr(executor, 'connected') and executor.connected:
                ibkr_connected = True
                account_balance = await executor.get_account_balance()

                if account_balance is not None:
                    if paper_mode:
                        balance_source = "IBKR_PAPER"
                    else:
                        balance_source = "IBKR_LIVE"
                    print(f"✓ Retrieved balance from IBKR ({balance_source}): ${account_balance:,.2f}")
                else:
                    print("⚠️ IBKR connected but balance retrieval returned None")
            else:
                print("⚠️ IBKR not connected")
        except Exception as e:
            print(f"⚠️ Failed to get balance from IBKR: {e}")

        # Fallback to config balance if IBKR failed
        if account_balance is None:
            account_balance = account_balance_config
            balance_source = "CONFIG_FALLBACK"
            print(f"Using config balance: ${account_balance:,.2f}")

        # Create snapshot data
        snapshot = {
            "snapshot_version": "1.0",
            "date": date_str,
            "timestamp": now.isoformat(),
            "trading_hours_start": trading_hours_start,
            "account_balance": account_balance,
            "mode": "PAPER" if paper_mode else "LIVE",
            "ibkr_connected": ibkr_connected,
            "balance_source": balance_source,
            "notes": "Daily snapshot at trading hours start"
        }

        # Write to file (atomic write via temp file)
        temp_path = snapshot_path.with_suffix('.tmp')
        try:
            with open(temp_path, 'w') as f:
                json.dump(snapshot, f, indent=2)

            # Atomic rename
            temp_path.rename(snapshot_path)

            print(f"✓ Snapshot saved: ${account_balance:,.2f} (source: {balance_source})")
            return snapshot

        except Exception as e:
            print(f"✗ Failed to write snapshot file: {e}")
            # Clean up temp file if it exists
            if temp_path.exists():
                temp_path.unlink()
            return None

    def get_snapshot_for_date(self, date_str: str) -> Optional[dict]:
        """
        Read snapshot for a specific date.

        Args:
            date_str: Date in YYYY-MM-DD format

        Returns:
            Snapshot dict or None if not found/invalid
        """
        snapshot_path = self._get_snapshot_path(date_str)

        if not snapshot_path.exists():
            return None

        try:
            with open(snapshot_path, 'r') as f:
                snapshot = json.load(f)
            return snapshot
        except json.JSONDecodeError as e:
            print(f"⚠️ Snapshot file corrupted for {date_str}: {e}")
            return None
        except Exception as e:
            print(f"⚠️ Failed to read snapshot for {date_str}: {e}")
            return None

    def get_today_snapshot(self) -> Optional[dict]:
        """
        Get snapshot for today.

        Returns:
            Today's snapshot dict or None if not found
        """
        today = datetime.now(timezone.utc).date().isoformat()
        return self.get_snapshot_for_date(today)
