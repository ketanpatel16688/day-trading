from abc import ABC, abstractmethod
from typing import Dict, List

from .indicators import IndicatorCalculator


class BaseStrategy(ABC):
    def __init__(self, indicator_calculator: IndicatorCalculator, config: Dict[str, object]):
        self.indicator_calculator = indicator_calculator
        self.config = config

    @abstractmethod
    def generate_signal(
        self,
        symbol: str,
        highs: List[float],
        lows: List[float],
        closes: List[float],
    ) -> Dict[str, object]:
        raise NotImplementedError


class SMARsiAtrStrategy(BaseStrategy):
    def generate_signal(
        self,
        symbol: str,
        highs: List[float],
        lows: List[float],
        closes: List[float],
    ) -> Dict[str, object]:
        strategy_settings = self.config.get("strategy", {})
        sma_window = int(strategy_settings.get("sma_window", 20))
        rsi_window = int(strategy_settings.get("rsi_window", 14))
        atr_window = int(strategy_settings.get("atr_window", 14))

        last_close = closes[-1]
        sma_value = self.indicator_calculator.sma(closes, sma_window)
        rsi_value = self.indicator_calculator.rsi(closes, rsi_window)
        atr_value = self.indicator_calculator.atr(highs, lows, closes, atr_window)

        signal = None
        exit_long = False
        exit_short = False

        if last_close > sma_value and rsi_value < 60:
            signal = "long"
        elif last_close < sma_value and rsi_value > 40:
            signal = "short"

        if last_close < sma_value or rsi_value > 70:
            exit_long = True

        if last_close > sma_value or rsi_value < 30:
            exit_short = True

        return {
            "signal": signal,
            "exit_long": exit_long,
            "exit_short": exit_short,
            "sma": sma_value,
            "rsi": rsi_value,
            "atr": atr_value,
        }


def get_strategy_class(name: str):
    strategies = {
        "SMARsiAtrStrategy": SMARsiAtrStrategy,
    }
    if name not in strategies:
        raise ValueError(f"Strategy '{name}' is not available")
    return strategies[name]
