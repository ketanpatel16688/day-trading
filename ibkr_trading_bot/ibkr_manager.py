import asyncio
import logging
import math
import threading
from concurrent.futures import ThreadPoolExecutor
from typing import Callable, Dict, List, Optional

from ib_async import IB, Contract, Order, Trade


class IBKRManager:
    def __init__(self, host: str = "127.0.0.1", port: int = 7497, client_id: int = 1001, account_id: str = ""):
        self.host = host
        self.port = port
        self.client_id = client_id
        self.account_id = account_id
        self.logger = logging.getLogger("execution")
        self.ib = IB()
        self._next_order_id: int = 1
        self._placed_orders: Dict[int, Order] = {}
        # Single-threaded executor: all IB calls run on one thread
        # that owns the event loop ib_async uses.
        self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="ib_worker")
        self._ib_thread_id: Optional[int] = None

    def _ib(self, fn: Callable):
        """
        Run fn() on the dedicated IB worker thread and block until done.
        This ensures every ib_async call happens on the thread that owns the
        event loop, preventing the 'response never arrives' deadlock that
        occurs when a coroutine is dispatched from a Flask worker thread whose
        event loop is not connected to ib_async's socket reader.
        """
        if threading.get_ident() == self._ib_thread_id:
            return fn()
        future = self._executor.submit(fn)
        return future.result(timeout=30)

    def connect(self) -> None:
        self.logger.debug("Connecting to IBKR at %s:%s client=%s account=%s", self.host, self.port, self.client_id, self.account_id)

        def _connect():
            self._ib_thread_id = threading.get_ident()
            # Passing account triggers reqAccountUpdates() during startup so that
            # accountValues() / accountSummary() cache is populated immediately.
           # self.ib.setConnectOptions('DownloadOpenOrders=0') # we call reqAllOpenOrders() manually in get_open_orders() instead
            self.ib.connect(self.host, self.port, clientId=self.client_id, account=self.account_id)

        self._executor.submit(_connect).result(timeout=30)

    def disconnect(self) -> None:
        if self.ib.isConnected():
            self.logger.debug("Disconnecting from IBKR")
            self._ib(self.ib.disconnect)

    def _build_stock_contract(
        self,
        symbol: str,
        sec_type: str = "STK",
        currency: str = "USD",
        exchange: str = "SMART",
    ) -> Contract:
        contract = Contract()
        contract.symbol = symbol
        contract.secType = sec_type
        contract.currency = currency
        contract.exchange = exchange
        return contract

    def _build_crypto_contract(
        self,
        symbol: str,
        exchange: str = "PAXOS",
        currency: str = "USD",
    ) -> Contract:
        contract = Contract()
        contract.symbol = symbol
        contract.secType = "CRYPTO"
        contract.currency = currency
        contract.exchange = exchange
        return contract

    def _build_option_contract(
        self,
        underlying: str,
        expiry: str,
        strike: float,
        right: str,
    ) -> Contract:
        contract = Contract()
        contract.symbol = underlying
        contract.secType = "OPT"
        contract.currency = "USD"
        contract.exchange = "SMART"
        contract.lastTradeDateOrContractMonth = expiry
        contract.strike = strike
        contract.right = right.upper()
        return contract

    def _allot_order_id(self) -> int:
        # getReqId() is the official ib_async API — same one used internally by
        # ib.placeOrder(). It reads from the client's internal sequence which is
        # kept in sync with the gateway's nextValidId callback automatically.
        oid = self.ib.client.getReqId()
        self.logger.debug("Allocated order ID %s from gateway sequence", oid)
        return oid

    # Terminal statuses that mean the order was accepted by the gateway
    _ACTIVE_STATUSES = {"PreSubmitted", "Submitted", "Filled", "PartiallyFilled"}
    # Terminal statuses that mean the gateway rejected/cancelled the order
    _FAILED_STATUSES = {"Cancelled", "ApiCancelled", "Inactive"}
    # Error codes that are fatal (duplicate id, invalid contract, etc.)
    _FATAL_ERROR_CODES = {103, 200, 201, 202, 203, 321, 322}

    def _wait_for_order_ack(self, trade: Trade, timeout: float = 5.0) -> None:
        """
        Block (on the IB worker thread) until the gateway acknowledges the order.
        Raises RuntimeError if the gateway rejects it or a fatal error is received.
        Must be called from within an _ib() closure so ib_async's event loop runs.
        """
        deadline = self.ib.wrapper.lastTime if hasattr(self.ib, "wrapper") else None
        elapsed = 0.0
        interval = 0.1
        while elapsed < timeout:
            status = trade.orderStatus.status
            if status in self._ACTIVE_STATUSES:
                return
            if status in self._FAILED_STATUSES:
                raise RuntimeError(
                    f"Order {trade.order.orderId} rejected by gateway: status={status}"
                )
            # Check for error log entries on this trade
            for entry in trade.log:
                if entry.errorCode in self._FATAL_ERROR_CODES:
                    raise RuntimeError(
                        f"Order {trade.order.orderId} error {entry.errorCode}: {entry.message}"
                    )
            self.ib.sleep(interval)
            elapsed += interval
        # Timed out — log a warning but don't crash; gateway may still accept it
        self.logger.warning(
            "Order %s still in status '%s' after %.1fs — proceeding without confirmation",
            trade.order.orderId, trade.orderStatus.status, timeout,
        )

    def fetch_historical_data(
        self,
        symbol: str,
        duration: str = "2 D",
        bar_size: str = "30 mins",
        what_to_show: str = "TRADES",
        use_rth: int = 1,
        contract_details: Optional[Dict[str, str]] = None,
    ) -> List[Dict[str, object]]:
        if not self.ib.isConnected():
            raise RuntimeError("IBKR client is not connected")

        def _fetch() -> List[Dict[str, object]]:
            if contract_details:
                contract = Contract()
                contract.symbol = symbol
                contract.secType = contract_details.get("secType", "STK")
                contract.currency = contract_details.get("currency", "USD")
                contract.exchange = contract_details.get("exchange", "SMART")
            else:
                contract = self._build_stock_contract(symbol)
            self.ib.qualifyContracts(contract)
            self.logger.debug(
                "Requesting historical data for %s: duration=%s bar_size=%s",
                symbol, duration, bar_size,
            )
            bars = self.ib.reqHistoricalData(
                contract,
                endDateTime="",
                durationStr=duration,
                barSizeSetting=bar_size,
                whatToShow=what_to_show,
                useRTH=bool(use_rth),
                formatDate=1,
            )
            return [
                {
                    "date": b.date,
                    "open": b.open,
                    "high": b.high,
                    "low": b.low,
                    "close": b.close,
                    "volume": b.volume,
                }
                for b in bars
            ]

        return self._ib(_fetch)

    def get_crypto_price(self, symbol: str, exchange: str, currency: str) -> Optional[float]:
        bars = self.fetch_historical_data(
            symbol=symbol,
            duration="1 D",
            bar_size="1 day",
            what_to_show="MIDPOINT",
            use_rth=1,
            contract_details={"secType": "CRYPTO", "exchange": exchange, "currency": currency},
        )
        if not bars:
            return None
        return float(bars[-1].get("close"))

    def get_latest_close(self, symbol: str, timeout: int = 10) -> Optional[float]:
        bars = self.fetch_historical_data(symbol=symbol, duration="1 D", bar_size="1 day", what_to_show="TRADES")
        if not bars:
            return None
        return float(bars[-1].get("close"))

    def get_positions(self, timeout: int = 5) -> List[Dict[str, object]]:
        if not self.ib.isConnected():
            raise RuntimeError("IBKR client is not connected")

        def _fetch() -> List[Dict[str, object]]:
            positions = self.ib.reqPositions()
            return [
                {
                    "account": p.account,
                    "symbol": p.contract.symbol,
                    "position": p.position,
                    "avgCost": p.avgCost,
                }
                for p in positions
            ]

        return self._ib(_fetch)

    def get_ticker_position(self, symbol: str, timeout: int = 5) -> Optional[Dict[str, object]]:
        positions = self.get_positions(timeout=timeout)
        for pos in positions:
            if pos.get("symbol") == symbol:
                self.logger.debug("Found position for %s: %s", symbol, pos)
                return pos
        self.logger.debug("No position found for %s", symbol)
        return None

    def get_open_orders(self, timeout: int = 5) -> List[Dict[str, object]]:
        self.logger.debug("Fetching open orders...")

        if not self.ib.isConnected():
            self.logger.debug("IBKR client is not connected")
            raise RuntimeError("IBKR client is not connected")

        def _fetch() -> List[Dict[str, object]]:
            self.ib.reqAllOpenOrders()
            trades = self.ib.openTrades()
            for t in trades:
                self.logger.debug("Found open order for %s: %s", t.contract.symbol, t.order)
            return [
                {
                    "orderId": t.order.orderId,
                    "symbol": t.contract.symbol,
                    "action": t.order.action,
                    "orderType": t.order.orderType,
                    "totalQuantity": t.order.totalQuantity,
                }
                for t in trades
            ]

        try:
            return self._ib(_fetch)
        except Exception as e:
            self.logger.error("Failed to fetch open orders: %s", e)
            raise

    def get_account_summary(self, tags: List[str] = ["SettledCash"], currency: str = "USD") -> Dict[str, str]:
        if not self.ib.isConnected():
            raise RuntimeError("IBKR client is not connected")

        def _fetch() -> Dict[str, str]:
            # accountValues() reads from the cache populated by reqAccountUpdates() which
            # connectAsync() already awaited at connect time (requires account_id to be set).
            # SettledCash is only in this stream, not in reqAccountSummary.
            values = self.ib.accountValues()
            if not values:
                raise TimeoutError("Timed out fetching account summary")
            return {v.tag: v.value for v in values if v.tag in tags and v.currency == currency}

        return self._ib(_fetch)

    def get_settled_cash(self) -> Optional[float]:
        try:
            summary = self.get_account_summary(["AvailableFunds"])
            return float(summary.get("AvailableFunds", 0))
        except Exception as e:
            self.logger.warning("Failed to fetch settled cash: %s", e)
            return None

    def get_stock_price(self, symbol: str) -> Optional[float]:
        return self.get_latest_close(symbol)

    def calculate_atr(
        self,
        symbol: str,
        length: int = 14,
        bar_size: str = "1 day",
        duration: str = "2 M",
        is_crypto: bool = False,
        crypto_info: Optional[Dict] = None,
    ) -> Optional[float]:
        try:
            contract_details = None
            actual_symbol = symbol
            if is_crypto and crypto_info:
                contract_details = {
                    "secType": "CRYPTO",
                    "exchange": crypto_info["exchange"],
                    "currency": crypto_info["currency"],
                }
                actual_symbol = crypto_info["symbol"]

            bars = self.fetch_historical_data(
                actual_symbol,
                duration=duration,
                bar_size=bar_size,
                contract_details=contract_details,
                what_to_show="MIDPOINT",
            )
            if len(bars) < length + 1:
                return None

            trs = []
            for i in range(1, len(bars)):
                high = float(bars[i]["high"])
                low = float(bars[i]["low"])
                prev_close = float(bars[i - 1]["close"])
                tr = max(high - low, abs(high - prev_close), abs(low - prev_close))
                trs.append(tr)

            return sum(trs[-length:]) / length
        except Exception as e:
            self.logger.error("Failed to calculate ATR for %s: %s", symbol, e)
            return None

    def place_order(
        self,
        symbol: str,
        action: str,
        quantity: float,
        order_type: str = "MKT",
        price: Optional[float] = None,
        tif: str = "GTC",
    ) -> int:
        if not self.ib.isConnected():
            raise RuntimeError("IBKR client is not connected")

        action_upper = action.upper()
        if action_upper not in ("BUY", "SELL"):
            raise ValueError(f"Invalid action: {action}. Must be BUY or SELL")
        if quantity <= 0:
            raise ValueError(f"Invalid quantity: {quantity}. Must be > 0")
        if order_type not in ("MKT", "LMT", "STP"):
            raise ValueError(f"Invalid order_type: {order_type}. Must be MKT, LMT, or STP")
        if order_type == "LMT" and price is None:
            raise ValueError("LMT orders require a price")

        order_id = self._allot_order_id()
        contract = self._build_stock_contract(symbol)

        order = Order()
        order.orderId = order_id
        order.action = action_upper
        order.orderType = order_type
        order.totalQuantity = math.floor(quantity * 100) / 100
        order.outsideRth = True
        order.tif = tif
        if price is not None and order_type == "LMT":
            order.lmtPrice = price

        self.logger.debug("Placing order %s for %.2f shares of %s (type=%s)", order_id, quantity, symbol, order_type)

        def _place():
            trade = self.ib.placeOrder(contract, order)
            self._wait_for_order_ack(trade)

        self._ib(_place)
        self._placed_orders[order_id] = order
        return order_id

    def place_bracket_order(
        self,
        symbol: str,
        action: str,
        quantity: float,
        stop_price: float,
        take_profit_price: float,
        limit_price: Optional[float] = None,
        tif: str = "GTC",
    ) -> Dict[str, int]:
        if not self.ib.isConnected():
            raise RuntimeError("IBKR client is not connected")

        action_upper = action.upper()
        if action_upper not in ("BUY", "SELL"):
            raise ValueError(f"Invalid action: {action}. Must be BUY or SELL")
        if quantity <= 0:
            raise ValueError(f"Invalid quantity: {quantity}. Must be > 0")
        if stop_price <= 0:
            raise ValueError(f"Invalid stop_price: {stop_price}. Must be > 0")
        if take_profit_price <= 0:
            raise ValueError(f"Invalid take_profit_price: {take_profit_price}. Must be > 0")
        if limit_price is not None and limit_price <= 0:
            raise ValueError(f"Invalid limit_price: {limit_price}. Must be > 0")

        contract = self._build_stock_contract(symbol)
        qty = math.floor(quantity * 100) / 100

        parent_id = self._allot_order_id()
        parent = Order()
        parent.orderId = parent_id
        parent.orderType = "LMT" if limit_price is not None else "MKT"
        parent.action = action_upper
        parent.totalQuantity = qty
        parent.outsideRth = True
        parent.tif = tif
        if limit_price is not None and parent.orderType == "LMT":
            parent.lmtPrice = round(limit_price, 2)
        parent.transmit = False

        tp_id = self._allot_order_id()
        tp = Order()
        tp.orderId = tp_id
        tp.action = "SELL" if action_upper == "BUY" else "BUY"
        tp.orderType = "LMT"
        tp.totalQuantity = qty
        tp.lmtPrice = round(take_profit_price, 2)
        tp.tif = tif
        tp.parentId = parent_id
        tp.outsideRth = True
        tp.transmit = False

        sl_id = self._allot_order_id()
        sl = Order()
        sl.orderId = sl_id
        sl.action = "SELL" if action_upper == "BUY" else "BUY"
        sl.orderType = "STP"
        sl.auxPrice = round(stop_price, 2)
        sl.totalQuantity = qty
        sl.tif = tif
        sl.parentId = parent_id
        sl.outsideRth = True
        sl.transmit = True

        self.logger.debug("Placing bracket order parent=%s tp=%s sl=%s for %s", parent_id, tp_id, sl_id, symbol)

        def _place():
            parent_trade = self.ib.placeOrder(contract, parent)
            tp_trade = self.ib.placeOrder(contract, tp)
            sl_trade = self.ib.placeOrder(contract, sl)
            self._wait_for_order_ack(parent_trade)
            self._wait_for_order_ack(tp_trade)
            self._wait_for_order_ack(sl_trade)

        self._ib(_place)
        self._placed_orders.update({parent_id: parent, tp_id: tp, sl_id: sl})

        return {"parent": parent_id, "tp": tp_id, "sl": sl_id}

    def place_option_order(
        self,
        underlying: str,
        expiry: str,
        strike: float,
        right: str,
        action: str,
        quantity: float,
        order_type: str = "MKT",
        price: Optional[float] = None,
        tif: str = "GTC",
    ) -> int:
        if not self.ib.isConnected():
            raise RuntimeError("IBKR client is not connected")

        action_upper = action.upper()
        if action_upper not in ("BUY", "SELL"):
            raise ValueError(f"Invalid action: {action}. Must be BUY or SELL")
        if quantity <= 0:
            raise ValueError(f"Invalid quantity: {quantity}. Must be > 0")
        if order_type not in ("MKT", "LMT", "STP"):
            raise ValueError(f"Invalid order_type: {order_type}. Must be MKT, LMT, or STP")
        if order_type == "LMT" and price is None:
            raise ValueError("LMT orders require a price")
        if right.upper() not in ("C", "P"):
            raise ValueError(f"Invalid right: {right}. Must be C or P")
        if strike <= 0:
            raise ValueError(f"Invalid strike: {strike}. Must be > 0")

        order_id = self._allot_order_id()
        contract = self._build_option_contract(underlying, expiry, strike, right)

        order = Order()
        order.orderId = order_id
        order.action = action_upper
        order.orderType = order_type
        order.totalQuantity = quantity
        order.tif = tif
        order.eTradeOnly = False
        order.firmQuoteOnly = False
        if price is not None and order_type == "LMT":
            order.lmtPrice = price

        self.logger.debug(
            "Placing option order %s for %.2f contracts of %s %s %s",
            order_id, quantity, underlying, expiry, right,
        )

        def _place():
            trade = self.ib.placeOrder(contract, order)
            self._wait_for_order_ack(trade)

        self._ib(_place)
        self._placed_orders[order_id] = order
        return order_id

    def place_option_bracket(
        self,
        underlying: str,
        expiry: str,
        strike: float,
        right: str,
        action: str,
        quantity: float,
        stop_price: float,
        take_profit_price: float,
        limit_price: Optional[float] = None,
        tif: str = "GTC",
    ) -> Dict[str, int]:
        if not self.ib.isConnected():
            raise RuntimeError("IBKR client is not connected")

        action_upper = action.upper()
        if action_upper not in ("BUY", "SELL"):
            raise ValueError(f"Invalid action: {action}. Must be BUY or SELL")
        if quantity <= 0:
            raise ValueError(f"Invalid quantity: {quantity}. Must be > 0")
        if right.upper() not in ("C", "P"):
            raise ValueError(f"Invalid right: {right}. Must be C or P")
        if strike <= 0:
            raise ValueError(f"Invalid strike: {strike}. Must be > 0")
        if stop_price <= 0:
            raise ValueError(f"Invalid stop_price: {stop_price}. Must be > 0")
        if take_profit_price <= 0:
            raise ValueError(f"Invalid take_profit_price: {take_profit_price}. Must be > 0")
        if limit_price is not None and limit_price <= 0:
            raise ValueError(f"Invalid limit_price: {limit_price}. Must be > 0")

        contract = self._build_option_contract(underlying, expiry, strike, right)

        parent_id = self._allot_order_id()
        parent = Order()
        parent.orderId = parent_id
        parent.orderType = "LMT" if limit_price is not None else "MKT"
        parent.action = action_upper
        parent.totalQuantity = quantity
        parent.tif = tif
        if limit_price is not None and parent.orderType == "LMT":
            parent.lmtPrice = limit_price
        parent.transmit = False

        tp_id = self._allot_order_id()
        tp = Order()
        tp.orderId = tp_id
        tp.action = "SELL" if action_upper == "BUY" else "BUY"
        tp.orderType = "LMT"
        tp.totalQuantity = quantity
        tp.lmtPrice = round(take_profit_price, 2)
        tp.tif = tif
        tp.parentId = parent_id
        tp.transmit = False

        sl_id = self._allot_order_id()
        sl = Order()
        sl.orderId = sl_id
        sl.action = "SELL" if action_upper == "BUY" else "BUY"
        sl.orderType = "STP"
        sl.auxPrice = round(stop_price, 2)
        sl.totalQuantity = quantity
        sl.tif = tif
        sl.parentId = parent_id
        sl.transmit = True

        self.logger.debug(
            "Placing option bracket order parent=%s tp=%s sl=%s for %s %s %s",
            parent_id, tp_id, sl_id, underlying, expiry, right,
        )

        def _place():
            parent_trade = self.ib.placeOrder(contract, parent)
            tp_trade = self.ib.placeOrder(contract, tp)
            sl_trade = self.ib.placeOrder(contract, sl)
            self._wait_for_order_ack(parent_trade)
            self._wait_for_order_ack(tp_trade)
            self._wait_for_order_ack(sl_trade)

        self._ib(_place)
        self._placed_orders.update({parent_id: parent, tp_id: tp, sl_id: sl})

        return {"parent": parent_id, "tp": tp_id, "sl": sl_id}

    def place_crypto_order(
        self,
        symbol: str,
        exchange: str,
        currency: str,
        action: str,
        quantity: float,
        order_type: str = "MKT",
        price: Optional[float] = None,
        tif: str = "IOC",
    ) -> int:
        if not self.ib.isConnected():
            raise RuntimeError("IBKR client is not connected")

        action_upper = action.upper()
        if action_upper not in ("BUY", "SELL"):
            raise ValueError(f"Invalid action: {action}. Must be BUY or SELL")
        if quantity <= 0.009:
            raise ValueError(f"Invalid quantity: {quantity}. Must be > 0.009")

        order_id = self._allot_order_id()
        contract = self._build_crypto_contract(symbol, exchange, currency)

        order = Order()
        order.orderId = order_id
        order.action = action_upper
        order.orderType = order_type
        order.outsideRth = True
        order.tif = tif

        self.logger.debug("Placing crypto order with action %s and quantity %s", action_upper, quantity)

        if action_upper == "SELL":
            pos = self.get_ticker_position(symbol)
            if pos is None:
                raise ValueError(f"No open position found for {symbol} to sell")
            fetched_qty = float(pos.get("position", 0))
            if fetched_qty <= 0.001:
                raise ValueError(
                    f"No positive position for {symbol}. Cannot place sell order (position={fetched_qty})"
                )
            if quantity < 0.01:
                order.totalQuantity = math.floor(fetched_qty * 100) / 100
            else:
                order.totalQuantity = math.floor(quantity * 100) / 100
        else:
            order.cashQty = 500

        if price is not None and order_type == "LMT":
            order.lmtPrice = price

        self.logger.debug(
            "Placing crypto order %s for %.8f %s (type=%s)", order_id, quantity, symbol, order_type,
        )

        def _place():
            trade = self.ib.placeOrder(contract, order)
            self._wait_for_order_ack(trade)

        self._ib(_place)
        self._placed_orders[order_id] = order
        return order_id

    def place_crypto_bracket_order(
        self,
        symbol: str,
        exchange: str,
        currency: str,
        action: str,
        quantity: float,
        stop_price: float,
        take_profit_price: float,
        limit_price: Optional[float] = None,
        tif: str = "IOC",
    ) -> Dict[str, int]:
        if not self.ib.isConnected():
            raise RuntimeError("IBKR client is not connected")

        # IBKR does not support bracket orders for CRYPTO; only the entry order
        # is placed. The caller is responsible for a separate close/SL order.
        contract = self._build_crypto_contract(symbol, exchange, currency)

        parent_id = self._allot_order_id()
        parent = Order()
        parent.orderId = parent_id
        parent.orderType = "LMT" if limit_price is not None else "MKT"
        parent.action = action.upper()
        parent.cashQty = 500
        parent.outsideRth = True
        parent.tif = "IOC"
        if limit_price is not None and parent.orderType == "LMT":
            parent.lmtPrice = round(limit_price, 2)
        if stop_price is not None:
            parent.auxPrice = round(stop_price, 2)
        parent.transmit = True

        self.logger.debug("Placing crypto entry order parent=%s for %s", parent_id, symbol)

        def _place():
            trade = self.ib.placeOrder(contract, parent)
            self._wait_for_order_ack(trade)

        self._ib(_place)
        self._placed_orders[parent_id] = parent

        return {"parent": parent_id, "tp": -1, "sl": -1}

    def cancel_order(self, order_id: int) -> None:
        if not self.ib.isConnected():
            raise RuntimeError("IBKR client is not connected")

        self.logger.debug("Cancelling order %s", order_id)

        def _cancel() -> None:
            order = self._placed_orders.get(int(order_id))
            if order is None:
                for trade in self.ib.trades():
                    if trade.order.orderId == int(order_id):
                        order = trade.order
                        break
            if order is None:
                order = Order()
                order.orderId = int(order_id)
            self.ib.cancelOrder(order)

        try:
            self._ib(_cancel)
        except Exception as exc:
            self.logger.error("Failed to cancel order %s: %s", order_id, exc)
            raise

    def close_position(self, symbol: str, quantity: Optional[float] = None, tif: str = "GTC") -> int:
        if not self.ib.isConnected():
            raise RuntimeError("IBKR client is not connected")

        positions = self.get_positions()
        match = next((p for p in positions if p.get("symbol") == symbol), None)

        if match is None:
            raise ValueError(f"No open position found for symbol {symbol}")

        open_qty = float(match.get("position", 0))
        if open_qty == 0:
            raise ValueError(f"Position for {symbol} is zero")

        qty_to_close = abs(open_qty) if quantity is None else float(quantity)
        action = "SELL" if open_qty > 0 else "BUY"

        order_id = self.place_order(symbol=symbol, action=action, quantity=qty_to_close, order_type="MKT", tif=tif)
        self.logger.info("Submitted close order %s for %s qty=%.2f tif=%s", order_id, symbol, qty_to_close, tif)
        return order_id

    def close_crypto_position(
        self,
        symbol: str,
        exchange: str,
        currency: str,
        quantity: Optional[float] = None,
        tif: str = "IOC",
    ) -> int:
        if not self.ib.isConnected():
            raise RuntimeError("IBKR client is not connected")

        tif = "IOC"
        positions = self.get_positions()
        match = next((p for p in positions if p.get("symbol") == symbol), None)

        if match is None:
            raise ValueError(f"No open position found for crypto symbol {symbol}")

        open_qty = float(match.get("position", 0))
        if open_qty == 0:
            raise ValueError(f"Position for {symbol} is zero")

        qty_to_close = abs(open_qty) if quantity is None else float(quantity)

        # Action is opposite of the current position sign
        action = "SELL" if open_qty > 0 else "BUY"

        # Place a market order to close
        order_id = self.place_crypto_order(symbol=symbol, exchange=exchange, currency=currency, action=action, quantity=qty_to_close, order_type="MKT", tif=tif)
        self.logger.info("Submitted crypto close order %s for %s qty=%.8f tif=%s", order_id, symbol, qty_to_close, tif)
        return order_id