import json
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

    def record_trade(self, ticker: str, action: str, quantity: float, order_id: int, price: Optional[float] = None, notes: str = ""):
        entry = {
            "timestamp": datetime.datetime.now().isoformat(),
            "ticker": ticker.upper(),
            "action": action.upper(),
            "quantity": quantity,
            "order_id": order_id,
            "price": price,
            "notes": notes
        }
        self._log_trade(entry)

    def record_close(self, ticker: str, quantity: float, order_id: int, entry_price: Optional[float] = None, exit_price: Optional[float] = None, pnl: Optional[float] = None):
        notes = ""
        if pnl is not None:
            notes = f"P&L: {pnl:.2f}"
        entry = {
            "timestamp": datetime.datetime.now().isoformat(),
            "ticker": ticker.upper(),
            "action": "CLOSE",
            "quantity": quantity,
            "order_id": order_id,
            "entry_price": entry_price,
            "exit_price": exit_price,
            "pnl": pnl,
            "notes": notes
        }
        self._log_trade(entry)

    def get_trades_for_ticker(self, ticker: str) -> List[Dict]:
        return [t for t in self.trades if t.get("ticker") == ticker.upper()]

    def calculate_pnl_for_ticker(self, ticker: str) -> float:
        trades = self.get_trades_for_ticker(ticker)
        total_pnl = 0.0
        position = 0.0
        avg_cost = 0.0
        for trade in trades:
            action = trade.get("action")
            qty = trade.get("quantity", 0)
            price = trade.get("price")
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
        return sum(self.calculate_pnl_for_ticker(t) for t in tickers)

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

# Global instance
_journal = None

def get_journal() -> TradingJournal:
    global _journal
    if _journal is None:
        _journal = TradingJournal()
    return _journal