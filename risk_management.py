import logging
from typing import Dict, Optional, Tuple
from venv import logger

from ibkr_trading_bot.ibkr_manager import IBKRManager

class RiskManager:
    def __init__(self, ibkr_manager: IBKRManager, config: Dict):
        self.ibkr_manager = ibkr_manager
        self.config = config
        self.logger = logging.getLogger("risk")

    def get_initial_capital(self) -> float:
        """Get initial capital: try IBKR settled cash, else config fallback."""
        settled_cash = self.ibkr_manager.get_settled_cash()
        if settled_cash and settled_cash > 0:
            self.logger.info(f"Using IBKR settled cash: ${settled_cash}")
            return settled_cash
        fallback = self.config.get("risk", {}).get("initial_capital", 100000)
        self.logger.info(f"Using config fallback capital: ${fallback}")
        return fallback

    def get_current_price(self, symbol: str, is_crypto: bool = False, crypto_info: Optional[Dict] = None) -> Optional[float]:
        """Get current price for symbol."""
        if is_crypto and crypto_info:
            return self.ibkr_manager.get_crypto_price(crypto_info["symbol"], crypto_info["exchange"], crypto_info["currency"])
        return self.ibkr_manager.get_stock_price(symbol)

    def calculate_atr(self, symbol: str, length: int = 14, timeframe: str = "1 day", is_crypto: bool = False, crypto_info: Optional[Dict] = None) -> Optional[float]:
        """Calculate ATR based on timeframe."""
        bar_size = timeframe  # e.g., "1 day", "1 hour"
        duration = "2 M" if timeframe == "1 day" else "2 D"  # Adjust for intraday if needed
        return self.ibkr_manager.calculate_atr(symbol, length, bar_size, duration, is_crypto, crypto_info)

    def calculate_quantity(self, symbol: str, capital: float, risk_percent: float = 0.001, timeframe: str = "1 day", is_crypto: bool = False, crypto_info: Optional[Dict] = None) -> Optional[float]:
        """Calculate position size: qty = capital * risk_percent / (2 * ATR)."""
        atr = self.calculate_atr(symbol, timeframe=timeframe, is_crypto=is_crypto, crypto_info=crypto_info)
        if not atr or atr <= 0:
            return None
        qty = capital * risk_percent / (2 * atr)
        self.logger.info(f"Calculated risk-based qty for {symbol}: {qty} (capital={capital}, ATR={atr})")
        return qty

    def calculate_sl(self, current_price: float, atr: float, action: str, is_crypto: bool = False) -> float:
        """Calculate stop-loss price: current_price ± 3*ATR."""
        if is_crypto:
            multiplier = 2.5    #TBD: Will revisit this number later based on backtesting results. Crypto can be more volatile, so we might want a wider stop-loss to avoid getting stopped out by normal price swings.
        else:
            multiplier = 2.0

        if action.upper() == "BUY":
            return current_price - (multiplier * atr)
        elif action.upper() == "SELL":
            return current_price + (multiplier * atr)
        raise ValueError(f"Invalid action: {action}")

    def get_risk_params(self, symbol: str, action: str, timeframe: str = "1 day", is_crypto: bool = False, crypto_info: Optional[Dict] = None) -> Tuple[Optional[float], Optional[float]]:
        """Get quantity and stop-loss price for a trade. For crypto, cap qty at $500 / current_price."""
        capital = self.get_initial_capital()
        qty = self.calculate_quantity(symbol, capital, timeframe=timeframe, is_crypto=is_crypto, crypto_info=crypto_info)
        current_price = self.get_current_price(symbol, is_crypto, crypto_info)
        atr = self.calculate_atr(symbol, timeframe=timeframe, is_crypto=is_crypto, crypto_info=crypto_info)
        if not current_price or not atr:
            return None, None
        
        self.logger.debug(f"Current price for {symbol}: {current_price}, ATR: {atr}, calculated qty before capping: {qty}")

        # Cap crypto qty at $500 / current_price
        if is_crypto:
            crypto_max_value = self.config.get("alert", {}).get("crypto_max_trade_value", 500)
            capped_qty = crypto_max_value / current_price
            if qty is not None and qty > capped_qty:
                qty = capped_qty
                self.logger.info(f"Capped crypto qty for {symbol} at {qty} (max $500)")
        else:
            qty = int(qty) if qty is not None else None  # For stocks/options, we need whole shares
            self.logger.info(f"Revised qty for {symbol}: {qty}")
        sl_price = self.calculate_sl(current_price, atr, action,is_crypto)
        return qty, sl_price