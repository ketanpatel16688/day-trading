from typing import List


class IndicatorCalculator:
    """A collection of common technical indicators."""

    def sma(self, values: List[float], window: int) -> float:
        if len(values) < window:
            raise ValueError("Not enough values to calculate SMA")
        return sum(values[-window:]) / window

    def rsi(self, values: List[float], window: int = 14) -> float:
        if len(values) < window + 1:
            raise ValueError("Not enough values to calculate RSI")

        gains = 0.0
        losses = 0.0
        for previous, current in zip(values[-window - 1 : -1], values[-window:]):
            change = current - previous
            if change > 0:
                gains += change
            else:
                losses -= change

        average_gain = gains / window
        average_loss = losses / window

        if average_loss == 0:
            return 100.0

        rs = average_gain / average_loss
        return 100.0 - (100.0 / (1.0 + rs))

    def atr(
        self,
        highs: List[float],
        lows: List[float],
        closes: List[float],
        window: int = 14,
    ) -> float:
        if len(highs) < window + 1 or len(lows) < window + 1 or len(closes) < window + 1:
            raise ValueError("Not enough values to calculate ATR")

        true_ranges = []
        for i in range(1, len(closes)):
            high = highs[i]
            low = lows[i]
            previous_close = closes[i - 1]
            true_range = max(
                high - low,
                abs(high - previous_close),
                abs(low - previous_close),
            )
            true_ranges.append(true_range)

        if len(true_ranges) < window:
            raise ValueError("Not enough true range data to calculate ATR")

        return sum(true_ranges[-window:]) / window
