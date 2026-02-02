"""
Balance Logger

Logs account balance after each trade close for tracking P&L over time.
"""

import csv
import os
from datetime import datetime, timezone
from typing import Optional
import io


class BalanceLogger:
    """
    Logs balance to CSV file after each trade close.

    CSV format: timestamp, balance, side, exit_price, pnl
    """

    def __init__(self, log_dir: str = "logs"):
        self.log_dir = log_dir
        self.log_file = os.path.join(log_dir, "balance_history.csv")

        # Create directory if needed
        os.makedirs(log_dir, exist_ok=True)

        # Create file with headers if it doesn't exist
        if not os.path.exists(self.log_file):
            with open(self.log_file, 'w', newline='') as f:
                writer = csv.writer(f)
                writer.writerow(['timestamp', 'balance', 'side', 'exit_price', 'pnl'])

    def log_balance(
        self,
        balance: float,
        side: Optional[str] = None,
        exit_price: Optional[float] = None,
        pnl: Optional[float] = None
    ):
        """Log balance after a trade close."""
        timestamp = datetime.now(timezone.utc).isoformat()

        with open(self.log_file, 'a', newline='') as f:
            writer = csv.writer(f)
            writer.writerow([
                timestamp,
                f"{balance:.2f}",
                side or "",
                f"{exit_price:.2f}" if exit_price else "",
                f"{pnl:.2f}" if pnl else ""
            ])

        print(f"  Balance logged: ${balance:,.2f}")

    def get_balance_history(self) -> list[dict]:
        """Read balance history from CSV."""
        history = []

        if not os.path.exists(self.log_file):
            return history

        with open(self.log_file, 'r') as f:
            reader = csv.DictReader(f)
            for row in reader:
                try:
                    history.append({
                        'timestamp': datetime.fromisoformat(row['timestamp']),
                        'balance': float(row['balance']),
                        'side': row.get('side', ''),
                        'exit_price': float(row['exit_price']) if row.get('exit_price') else None,
                        'pnl': float(row['pnl']) if row.get('pnl') else None
                    })
                except (ValueError, KeyError):
                    continue

        return history

    def generate_plot(self) -> Optional[bytes]:
        """
        Generate a balance plot image showing last 90 trades.

        X-axis is trade number (evenly spaced), with timestamps as labels.
        Returns PNG image as bytes, or None if no data or matplotlib unavailable.
        """
        try:
            import matplotlib
            matplotlib.use('Agg')  # Non-interactive backend
            import matplotlib.pyplot as plt
            import pytz
        except ImportError:
            print("matplotlib not installed - cannot generate plot")
            return None

        history = self.get_balance_history()

        if len(history) < 2:
            return None

        # Limit to last 90 trades
        history = history[-90:]

        # Convert timestamps to LA timezone
        la_tz = pytz.timezone('America/Los_Angeles')
        timestamps = [h['timestamp'].astimezone(la_tz) for h in history]
        balances = [h['balance'] for h in history]

        # Use trade numbers for x-axis (evenly spaced)
        trade_nums = list(range(1, len(balances) + 1))

        # Create plot
        fig, ax = plt.subplots(figsize=(12, 6))

        # Plot balance line by trade number
        ax.plot(trade_nums, balances, 'b-', linewidth=2, marker='o', markersize=4)

        # Set y-axis limits based on data range with padding
        min_bal = min(balances)
        max_bal = max(balances)
        padding = (max_bal - min_bal) * 0.1 if max_bal != min_bal else max_bal * 0.05
        ax.set_ylim(min_bal - padding, max_bal + padding)

        # Fill under line with gradient effect (use min as baseline)
        ax.fill_between(trade_nums, balances, min_bal - padding, alpha=0.3)

        # Formatting
        ax.set_title(f'Balance History (Last {len(balances)} Trades)', fontsize=14, fontweight='bold')
        ax.set_xlabel('Trade #', fontsize=12)
        ax.set_ylabel('Balance ($)', fontsize=12)

        # Format y-axis as currency
        ax.yaxis.set_major_formatter(plt.FuncFormatter(lambda x, p: f'${x:,.0f}'))

        # Set x-axis ticks with time labels
        # Show ~10 evenly spaced labels to avoid crowding
        num_labels = min(10, len(trade_nums))
        step = max(1, len(trade_nums) // num_labels)
        tick_positions = trade_nums[::step]
        tick_labels = [timestamps[i].strftime('%m/%d %H:%M') for i in range(0, len(timestamps), step)]

        # Always include the last trade
        if tick_positions[-1] != trade_nums[-1]:
            tick_positions.append(trade_nums[-1])
            tick_labels.append(timestamps[-1].strftime('%m/%d %H:%M'))

        ax.set_xticks(tick_positions)
        ax.set_xticklabels(tick_labels, rotation=45, ha='right', fontsize=8)

        # Add grid
        ax.grid(True, alpha=0.3)

        # Add start/end annotations
        start_bal = balances[0]
        end_bal = balances[-1]
        change = end_bal - start_bal
        change_pct = (change / start_bal) * 100 if start_bal > 0 else 0

        color = 'green' if change >= 0 else 'red'
        ax.annotate(
            f'P&L: ${change:+,.2f} ({change_pct:+.1f}%)',
            xy=(0.02, 0.98),
            xycoords='axes fraction',
            fontsize=12,
            fontweight='bold',
            color=color,
            verticalalignment='top'
        )

        # Tight layout
        plt.tight_layout()

        # Save to bytes
        buf = io.BytesIO()
        plt.savefig(buf, format='png', dpi=150)
        buf.seek(0)
        plt.close(fig)

        return buf.getvalue()


# Global instance
_balance_logger: Optional[BalanceLogger] = None


def init_balance_logger(log_dir: str = "logs") -> BalanceLogger:
    """Initialize global balance logger."""
    global _balance_logger
    _balance_logger = BalanceLogger(log_dir=log_dir)
    return _balance_logger


def get_balance_logger() -> Optional[BalanceLogger]:
    """Get global balance logger instance."""
    return _balance_logger
