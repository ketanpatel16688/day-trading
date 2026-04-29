import json
import csv
import datetime
import logging
from pathlib import Path
from typing import Dict, List, Optional

class TradingJournal:
    def __init__(self, log_file: str = "logs/journal.log"):
        self.log_file = Path(log_file)
        self.log_file.parent.mkdir(parents=True, exist_ok=True)
        self.logger = logging.getLogger("journal")
        # Ensure journal logger is set up
        if not self.logger.handlers:
            handler = logging.FileHandler(self.log_file, encoding="utf-8")
            formatter = logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s")
            handler.setFormatter(formatter)
            self.logger.addHandler(handler)
            self.logger.setLevel(logging.INFO)

        # In-memory for quick P&L calc, but persist to file
        self.trades: List[Dict] = []
        self._load_trades()
        self._setup_csv_files()

    def _get_current_week_csv(self) -> Path:
        now = datetime.datetime.now()
        iso_year, iso_week, _ = now.isocalendar()
        csv_filename = f"trading_journal_{iso_year}_W{iso_week:02d}.csv"
        return self.log_file.parent / csv_filename

    def _setup_csv_files(self):
        self.csv_file = self._get_current_week_csv()
        self._ensure_csv_header()

    def _ensure_csv_header(self):
        if not self.csv_file.exists():
            with open(self.csv_file, "w", newline="", encoding="utf-8") as f:
                writer = csv.DictWriter(f, fieldnames=self._get_csv_headers())
                writer.writeheader()
            self.logger.info(f"Created new weekly CSV: {self.csv_file.name}")
        else:
            new_csv = self._get_current_week_csv()
            if new_csv != self.csv_file:
                self.csv_file = new_csv
                self._ensure_csv_header()

    @staticmethod
    def _get_csv_headers() -> List[str]:
        return [
            "trade_id",
            "timestamp_entry",
            "timestamp_exit",
            "ticker",
            "order_type",
            "quantity",
            "entry_price",
            "exit_price",
            "pnl",
            "pnl_percent",
            "duration_minutes",
            "status",
            "order_id_entry",
            "order_id_exit",
            "notes"
        ]

    def _load_trades(self):
        if self.log_file.exists():
            with open(self.log_file, "r", encoding="utf-8") as f:
                for line in f:
                    try:
                        entry = json.loads(line.strip())
                        self.trades.append(entry)
                    except json.JSONDecodeError:
                        pass  # Skip bad lines

    def _log_trade(self, entry: Dict):
        self.trades.append(entry)
        self.logger.info(json.dumps(entry))

    def _write_to_csv(self, trade_record: Dict):
        self._ensure_csv_header()
        try:
            with open(self.csv_file, "a", newline="", encoding="utf-8") as f:
                writer = csv.DictWriter(f, fieldnames=self._get_csv_headers())
                # Only write fields that exist in headers
                row = {k: trade_record.get(k, "") for k in self._get_csv_headers()}
                writer.writerow(row)
        except Exception as e:
            self.logger.error(f"Failed to write CSV: {e}")

    def record_trade(self, ticker: str, action: str, quantity: float, order_id: int, price: Optional[float] = None, order_type: str = "webalert", notes: str = ""):
        trade_id = f"{ticker}_{order_id}_{datetime.datetime.now().strftime('%Y%m%d%H%M%S')}"
        timestamp = datetime.datetime.now().isoformat()

        entry = {
            "trade_id": trade_id,
            "timestamp_entry": timestamp,
            "ticker": ticker.upper(),
            "action": action.upper(),
            "quantity": quantity,
            "order_id": order_id,
            "entry_price": price,
            "order_type": order_type,
            "notes": notes,
            "status": "OPEN"
        }
        self._log_trade(entry)

        csv_record = {
            "trade_id": trade_id,
            "timestamp_entry": timestamp,
            "ticker": ticker.upper(),
            "order_type": order_type,
            "quantity": quantity,
            "entry_price": price or "",
            "status": "OPEN",
            "order_id_entry": order_id,
            "notes": notes
        }
        self._write_to_csv(csv_record)

    def record_close(self, ticker: str, quantity: float, order_id: int, trade_id: Optional[str] = None, entry_price: Optional[float] = None, exit_price: Optional[float] = None, pnl: Optional[float] = None):
        timestamp = datetime.datetime.now().isoformat()
        pnl_percent = ""
        duration_minutes = ""

        # Calculate P&L if both prices are available
        if entry_price is not None and exit_price is not None:
            if pnl is None:
                pnl = (exit_price - entry_price) * quantity
            pnl_percent = round((pnl / (entry_price * quantity)) * 100, 2) if entry_price != 0 else 0

        # Find matching open trade for duration calculation
        if trade_id:
            for trade in self.trades:
                if trade.get("trade_id") == trade_id and trade.get("status") == "OPEN":
                    entry_time = datetime.datetime.fromisoformat(trade.get("timestamp_entry", timestamp))
                    exit_time = datetime.datetime.fromisoformat(timestamp)
                    duration_minutes = int((exit_time - entry_time).total_seconds() / 60)
                    trade["status"] = "CLOSED"
                    break

        entry = {
            "timestamp_exit": timestamp,
            "ticker": ticker.upper(),
            "action": "CLOSE",
            "quantity": quantity,
            "order_id": order_id,
            "entry_price": entry_price,
            "exit_price": exit_price,
            "pnl": pnl,
            "trade_id": trade_id
        }
        self._log_trade(entry)

        csv_record = {
            "trade_id": trade_id or f"{ticker}_{order_id}",
            "timestamp_exit": timestamp,
            "ticker": ticker.upper(),
            "quantity": quantity,
            "entry_price": entry_price or "",
            "exit_price": exit_price or "",
            "pnl": round(pnl, 2) if pnl is not None else "",
            "pnl_percent": pnl_percent,
            "duration_minutes": duration_minutes or "",
            "status": "CLOSED",
            "order_id_exit": order_id
        }
        self._write_to_csv(csv_record)

    def get_trades_for_ticker(self, ticker: str) -> List[Dict]:
        return [t for t in self.trades if t.get("ticker") == ticker.upper()]

    def get_closed_trades_from_csv(self, all_weeks: bool = False) -> List[Dict]:
        closed_trades = []
        csv_files = []

        if all_weeks:
            logs_dir = self.log_file.parent
            csv_files = sorted(logs_dir.glob("trading_journal_*.csv"), reverse=True)
        else:
            csv_files = [self.csv_file] if self.csv_file.exists() else []

        for csv_file in csv_files:
            if csv_file.exists():
                try:
                    with open(csv_file, "r", encoding="utf-8") as f:
                        reader = csv.DictReader(f)
                        for row in reader:
                            if row.get("status") == "CLOSED":
                                closed_trades.append(row)
                except Exception as e:
                    self.logger.error(f"Failed to read CSV {csv_file}: {e}")

        return closed_trades

    def get_weekly_csv_files(self) -> List[Path]:
        logs_dir = self.log_file.parent
        return sorted(logs_dir.glob("trading_journal_*.csv"), reverse=True)

    def export_csv(self, output_file: Optional[str] = None) -> str:
        output = output_file or str(self.csv_file)
        self.logger.info(f"Trading journal CSV available at: {output}")
        return output

    def calculate_pnl_for_ticker(self, ticker: str) -> float:
        trades = self.get_trades_for_ticker(ticker)
        total_pnl = 0.0
        position = 0.0
        avg_cost = 0.0
        for trade in trades:
            action = trade.get("action")
            qty = trade.get("quantity", 0)
            price = trade.get("entry_price") or trade.get("price")
            if action == "BUY":
                if position == 0:
                    avg_cost = price or 0
                else:
                    avg_cost = (position * avg_cost + qty * (price or 0)) / (position + qty)
                position += qty
            elif action == "SELL" or action == "CLOSE":
                if position > 0 and price:
                    pnl = (price - avg_cost) * min(qty, position)
                    total_pnl += pnl
                    position -= qty
                    if position <= 0:
                        position = 0
                        avg_cost = 0
        return total_pnl

    def get_total_pnl(self) -> float:
        tickers = set(t.get("ticker") for t in self.trades)
        return sum(self.calculate_pnl_for_ticker(t) for t in tickers if t)

    def get_open_positions(self) -> Dict[str, float]:
        positions = {}
        for trade in self.trades:
            ticker = trade.get("ticker")
            action = trade.get("action")
            qty = trade.get("quantity", 0)
            if action == "BUY":
                positions[ticker] = positions.get(ticker, 0) + qty
            elif action == "SELL" or action == "CLOSE":
                positions[ticker] = positions.get(ticker, 0) - qty
        # Remove zero positions
        return {k: v for k, v in positions.items() if v != 0}

    def get_journal_stats(self, all_weeks: bool = False) -> Dict:
        closed_trades = self.get_closed_trades_from_csv(all_weeks=all_weeks)
        total_trades = len(closed_trades)
        if total_trades == 0:
            return {"total_trades": 0, "winning_trades": 0, "losing_trades": 0, "total_pnl": 0, "win_rate": 0, "avg_pnl": 0}

        winning_trades = sum(1 for t in closed_trades if t.get("pnl") and float(t.get("pnl", 0)) > 0)
        losing_trades = total_trades - winning_trades
        total_pnl = sum(float(t.get("pnl", 0)) for t in closed_trades if t.get("pnl"))
        win_rate = round((winning_trades / total_trades) * 100, 2) if total_trades > 0 else 0
        avg_pnl = round(total_pnl / total_trades, 2) if total_trades > 0 else 0

        return {
            "total_trades": total_trades,
            "winning_trades": winning_trades,
            "losing_trades": losing_trades,
            "total_pnl": round(total_pnl, 2),
            "win_rate": win_rate,
            "avg_pnl": avg_pnl
        }

# Global instance
_journal = None

def get_journal() -> TradingJournal:
    global _journal
    if _journal is None:
        _journal = TradingJournal()
    return _journal