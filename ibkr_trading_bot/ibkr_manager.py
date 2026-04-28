import logging
import threading
import time
from pathlib import Path
from typing import Dict, List, Optional

from ibapi.client import EClient
from ibapi.contract import Contract
from ibapi.order import Order
from ibapi.wrapper import EWrapper


class IBKRClient(EWrapper, EClient):
    def __init__(self, logger: Optional[logging.Logger] = None):
        EClient.__init__(self, self)
        self.logger = logger or logging.getLogger("ibkr")
        # global fallback buffer (rarely used) and per-request buffers/events
        self.historical_data: List[Dict[str, object]] = []
        self._historical_data_map: Dict[int, List[Dict[str, object]]] = {}
        self._historical_data_event = threading.Event()
        self._historical_data_events: Dict[int, threading.Event] = {}
        self.positions: List[Dict[str, object]] = []
        self._positions_event = threading.Event()
        self.open_orders: List[Dict[str, object]] = []
        self._open_orders_event = threading.Event()
        self._account_summary_map: Dict[int, Dict[str, str]] = {}
        self._account_summary_events: Dict[int, threading.Event] = {}
        self.next_order_id = 1

    def nextValidId(self, orderId: int) -> None:
        self.next_order_id = orderId
        self.logger.debug("Received next valid order ID %s", orderId)

    def historicalData(self, reqId: int, bar) -> None:
        entry = {
            "date": bar.date,
            "open": bar.open,
            "high": bar.high,
            "low": bar.low,
            "close": bar.close,
            "volume": bar.volume,
        }
        if reqId in self._historical_data_map:
            self._historical_data_map[reqId].append(entry)
        else:
            # fallback to global buffer
            self.historical_data.append(entry)

    def historicalDataEnd(self, reqId: int, start: str, end: str) -> None:
        self.logger.debug("Historical data download complete for request %s", reqId)
        ev = self._historical_data_events.get(reqId)
        if ev is not None:
            ev.set()
        else:
            self._historical_data_event.set()

    def position(self, account: str, contract: Contract, position: float, avgCost: float) -> None:
        try:
            symbol = getattr(contract, "symbol", None)
        except Exception:
            symbol = None

        self.positions.append(
            {
                "account": account,
                "symbol": symbol,
                "position": position,
                "avgCost": avgCost,
            }
        )

    def positionEnd(self) -> None:
        self.logger.debug("Position download complete")
        self._positions_event.set()

    def openOrder(self, orderId: int, contract: Contract, order: Order, orderState) -> None:
        try:
            symbol = getattr(contract, "symbol", None)
        except Exception:
            symbol = None

        self.open_orders.append(
            {
                "orderId": orderId,
                "symbol": symbol,
                "action": getattr(order, "action", None),
                "orderType": getattr(order, "orderType", None),
                "totalQuantity": getattr(order, "totalQuantity", None),
            }
        )

    def openOrderEnd(self) -> None:
        self.logger.debug("Open orders download complete")
        self._open_orders_event.set()

    def accountSummary(self, reqId: int, account: str, tag: str, value: str, currency: str) -> None:
        if reqId in self._account_summary_map:
            self._account_summary_map[reqId][tag] = value

    def accountSummaryEnd(self, reqId: int) -> None:
        ev = self._account_summary_events.get(reqId)
        if ev:
            ev.set()

    def error(self, reqId: int, errorCode: int, errorString: str, *args) -> None:
        # Filter out informational connection status messages
        # Error codes 2101-2107 and 2158 are connection status messages, not actual errors
        informational_codes = {2101, 2102, 2103, 2104, 2105, 2106, 2107, 2158}
        if errorCode in informational_codes:
            self.logger.debug("IBKR status. reqId=%s errCode=%s errMsg=%s", reqId, errorCode, errorString)
        else:
            self.logger.error("IBKR error. reqId=%s errCode=%s errMsg=%s", reqId, errorCode, errorString)
            # Only unblock waiting historical data requests for truly terminal errors.
            # Non-terminal warnings (pacing notices, subscription messages) can arrive
            # alongside valid data and must not fire the event early.
            terminal_hist_codes = {162, 200, 321, 322, 354, 420}
            if errorCode in terminal_hist_codes:
                ev = self._historical_data_events.get(reqId)
                if ev is not None:
                    ev.set()


class IBKRManager:
    def __init__(self, host: str = "127.0.0.1", port: int = 7497, client_id: int = 1001):
        self.host = host
        self.port = port
        self.client_id = client_id
        self.logger = logging.getLogger("execution")
        self.ibkr_logger = logging.getLogger("ibkr")
        self.client = IBKRClient(logger=self.ibkr_logger)
        self._thread: Optional[threading.Thread] = None

    def connect(self) -> None:
        self.logger.debug("Connecting to IBKR at %s:%s client=%s", self.host, self.port, self.client_id)
        self.client.connect(self.host, self.port, self.client_id)
        self._thread = threading.Thread(target=self.client.run, daemon=True)
        self._thread.start()
        time.sleep(1)

    def disconnect(self) -> None:
        if self.client.isConnected():
            self.logger.debug("Disconnecting from IBKR")
            self.client.disconnect()

        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=2)

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

    def fetch_historical_data(
        self,
        symbol: str,
        duration: str = "2 D",
        bar_size: str = "30 mins",
        what_to_show: str = "TRADES",
        use_rth: int = 1,
        contract_details: Optional[Dict[str, str]] = None,
    ) -> List[Dict[str, object]]:
        if not self.client.isConnected():
            raise RuntimeError("IBKR client is not connected")

        # prepare per-request buffer and event to avoid mixing responses
        request_id = int(time.time() * 1000) % 100000
        self.client._historical_data_map[request_id] = []
        ev = threading.Event()
        self.client._historical_data_events[request_id] = ev

        if contract_details:
            # Build custom contract
            contract = Contract()
            contract.symbol = symbol
            contract.secType = contract_details.get("secType", "STK")
            contract.currency = contract_details.get("currency", "USD")
            contract.exchange = contract_details.get("exchange", "SMART")
        else:
            contract = self._build_stock_contract(symbol)

        request_time = ""  # Use empty string for current time

        self.logger.debug(
            "Requesting historical data for %s: duration=%s bar_size=%s",
            symbol,
            duration,
            bar_size,
        )

        self.client.reqHistoricalData(
            request_id,
            contract,
            request_time,
            duration,
            bar_size,
            what_to_show,
            use_rth,
            1,
            False,
            [],
        )

        if not ev.wait(timeout=20):
            # cleanup and raise
            self.client._historical_data_map.pop(request_id, None)
            self.client._historical_data_events.pop(request_id, None)
            raise TimeoutError(f"Timed out waiting for historical data for {symbol}")

        bars = self.client._historical_data_map.pop(request_id, [])
        self.client._historical_data_events.pop(request_id, None)
        return bars

    def get_crypto_price(self, symbol: str, exchange: str, currency: str) -> Optional[float]:
        """Get the latest price for a crypto symbol."""
        bars = self.fetch_historical_data(
            symbol=symbol,
            duration="1 D",
            bar_size="1 day",
            what_to_show="MIDPOINT",
            use_rth=1,
            contract_details={"secType": "CRYPTO", "exchange": exchange, "currency": currency}
        )
        if not bars:
            return None
        # historical bars are appended in order; take the last
        last = bars[-1]
        return float(last.get("close"))

    def get_latest_close(self, symbol: str, timeout: int = 10) -> Optional[float]:
        bars = self.fetch_historical_data(symbol=symbol, duration="1 D", bar_size="1 day", what_to_show="TRADES")
        if not bars:
            return None
        # historical bars are appended in order; take the last
        last = bars[-1]
        return float(last.get("close"))

    def get_positions(self, timeout: int = 5) -> List[Dict[str, object]]:
        if not self.client.isConnected():
            raise RuntimeError("IBKR client is not connected")

        # clear any previous state
        self.client.positions = []
        self.client._positions_event.clear()

        self.client.reqPositions()

        if not self.client._positions_event.wait(timeout=timeout):
            # best-effort: return whatever we have
            return self.client.positions

        # cancel to stop further position updates
        try:
            self.client.cancelPositions()
        except Exception:
            pass

        return self.client.positions

    def get_open_orders(self, timeout: int = 5) -> List[Dict[str, object]]:
        if not self.client.isConnected():
            raise RuntimeError("IBKR client is not connected")

        self.client.open_orders = []
        self.client._open_orders_event.clear()

        # request all open orders
        try:
            self.client.reqAllOpenOrders()
        except Exception:
            # fallback to reqOpenOrders if not available
            try:
                self.client.reqOpenOrders()
            except Exception:
                pass

        if not self.client._open_orders_event.wait(timeout=timeout):
            return self.client.open_orders

        return self.client.open_orders

    def place_order(
        self,
        symbol: str,
        action: str,
        quantity: float,
        order_type: str = "MKT",
        price: Optional[float] = None,
        tif: str = "GTC",
    ) -> int:
        if not self.client.isConnected():
            raise RuntimeError("IBKR client is not connected")

        order_id = self.client.next_order_id
        self.client.next_order_id += 1

        contract = self._build_stock_contract(symbol)
        order = Order()
        order.action = action.upper()
        order.orderType = order_type
        order.totalQuantity = round(quantity,4)
        order.tif = tif

        if price is not None and order_type == "LMT":
            order.lmtPrice = price

        self.logger.debug(
            "Placing order %s for %.2f shares of %s (type=%s)",
            order_id,
            quantity,
            symbol,
            order_type,
        )
        self.client.placeOrder(order_id, contract, order)
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
        """Place a bracket order: parent (market or limit) + TP + SL.

        Returns a dict with the created order IDs: {'parent': id, 'tp': id, 'sl': id}
        """
        if not self.client.isConnected():
            raise RuntimeError("IBKR client is not connected")

        contract = self._build_stock_contract(symbol)

        parent_id = self.client.next_order_id
        self.client.next_order_id += 1

        parent = Order()
        parent.orderType = "LMT" if limit_price is not None else "MKT"
        parent.action = action.upper()
        parent.totalQuantity = round(quantity,4)
        parent.tif = tif
        if limit_price is not None and parent.orderType == "LMT":
            parent.lmtPrice = round(limit_price, 4)
        parent.transmit = False

        # Child: take-profit (limit opposite side)
        tp_id = self.client.next_order_id
        self.client.next_order_id += 1
        tp = Order()
        tp.action = "SELL" if action.lower() == "buy" else "BUY"
        tp.orderType = "LMT"
        tp.totalQuantity = round(quantity,4)
        tp.lmtPrice = round(take_profit_price,4)
        tp.tif = tif
        tp.parentId = parent_id
        tp.transmit = False

        # Child: stop-loss (stop opposite side). This will be the last order and will transmit the group.
        sl_id = self.client.next_order_id
        self.client.next_order_id += 1
        sl = Order()
        sl.action = "SELL" if action.lower() == "buy" else "BUY"
        sl.orderType = "STP"
        sl.auxPrice = round(stop_price, 4)
        sl.totalQuantity = round(quantity,4)
        sl.tif = tif
        sl.parentId = parent_id
        sl.transmit = True

        # Place orders
        self.logger.debug("Placing bracket order parent=%s tp=%s sl=%s for %s", parent_id, tp_id, sl_id, symbol)
        self.client.placeOrder(parent_id, contract, parent)
        self.client.placeOrder(tp_id, contract, tp)
        self.client.placeOrder(sl_id, contract, sl)

        return {"parent": parent_id, "tp": tp_id, "sl": sl_id}

    def get_account_summary(self, tags: List[str] = ["SettledCash"]) -> Dict[str, str]:
        """Fetch account summary values like SettledCash."""
        if not self.client.isConnected():
            raise RuntimeError("IBKR client is not connected")

        request_id = int(time.time() * 1000) % 100000
        self.client._account_summary_map[request_id] = {}
        ev = threading.Event()
        self.client._account_summary_events[request_id] = ev

        self.client.reqAccountSummary(request_id, "All", ",".join(tags))

        if not ev.wait(timeout=10):
            raise TimeoutError("Timed out fetching account summary")

        summary = self.client._account_summary_map.get(request_id, {})
        self.client._account_summary_map.pop(request_id, None)
        self.client._account_summary_events.pop(request_id, None)
        return summary

    def get_settled_cash(self) -> Optional[float]:
        """Get settled cash from IBKR account."""
        try:
            summary = self.get_account_summary(["SettledCash"])
            return float(summary.get("SettledCash", 0))
        except Exception as e:
            self.logger.warning(f"Failed to fetch settled cash: {e}")
            return None

    def get_stock_price(self, symbol: str) -> Optional[float]:
        """Get latest close price for a stock (proxy for current price)."""
        return self.get_latest_close(symbol)

    def calculate_atr(self, symbol: str, length: int = 14, bar_size: str = "1 day", duration: str = "2 M", is_crypto: bool = False, crypto_info: Optional[Dict] = None) -> Optional[float]:
        """Calculate ATR from historical data."""
        try:
            contract_details = None
            actual_symbol = symbol
            if is_crypto and crypto_info:
                contract_details = {
                    "secType": "CRYPTO",
                    "exchange": crypto_info["exchange"],
                    "currency": crypto_info["currency"]
                }
                actual_symbol = crypto_info["symbol"]
            bars = self.fetch_historical_data(actual_symbol, duration=duration, bar_size=bar_size, contract_details=contract_details,what_to_show="MIDPOINT")
            if len(bars) < length + 1:
                return None
            trs = []
            for i in range(1, len(bars)):
                high = float(bars[i]["high"])
                low = float(bars[i]["low"])
                prev_close = float(bars[i-1]["close"])
                tr = max(high - low, abs(high - prev_close), abs(low - prev_close))
                trs.append(tr)
            return sum(trs[-length:]) / length
        except Exception as e:
            self.logger.error(f"Failed to calculate ATR for {symbol}: {e}")
            return None

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
        if not self.client.isConnected():
            raise RuntimeError("IBKR client is not connected")

        order_id = self.client.next_order_id
        self.client.next_order_id += 1

        contract = self._build_option_contract(underlying, expiry, strike, right)
        order = Order()
        order.action = action.upper()
        order.orderType = order_type
        order.totalQuantity = round(quantity,4)
        order.tif = tif
        order.eTradeOnly = False  # Add this line
        order.firmQuoteOnly = False # Often needed alongside eTradeOnly

        if price is not None and order_type == "LMT":
            order.lmtPrice = price

        self.logger.debug(
            "Placing option order %s for %.2f contracts of %s %s %s",
            order_id,
            quantity,
            underlying,
            expiry,
            right,
        )
        self.client.placeOrder(order_id, contract, order)
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
        if not self.client.isConnected():
            raise RuntimeError("IBKR client is not connected")

        contract = self._build_option_contract(underlying, expiry, strike, right)

        parent_id = self.client.next_order_id
        self.client.next_order_id += 1

        parent = Order()
        parent.orderType = "LMT" if limit_price is not None else "MKT"
        parent.action = action.upper()
        parent.totalQuantity = round(quantity,4)
        parent.tif = tif
        if limit_price is not None and parent.orderType == "LMT":
            parent.lmtPrice = limit_price
        parent.transmit = False

        tp_id = self.client.next_order_id
        self.client.next_order_id += 1
        tp = Order()
        tp.action = "SELL" if action.lower() == "buy" else "BUY"
        tp.orderType = "LMT"
        tp.totalQuantity = round(quantity,4)
        tp.lmtPrice = round(take_profit_price,4)
        tp.tif = tif
        tp.parentId = parent_id
        tp.transmit = False

        sl_id = self.client.next_order_id
        self.client.next_order_id += 1
        sl = Order()
        sl.action = "SELL" if action.lower() == "buy" else "BUY"
        sl.orderType = "STP"
        sl.auxPrice = round(stop_price, 4)
        sl.totalQuantity = round(quantity,4)
        sl.tif = tif
        sl.parentId = parent_id
        sl.transmit = True

        self.logger.debug(
            "Placing option bracket order parent=%s tp=%s sl=%s for %s %s %s",
            parent_id,
            tp_id,
            sl_id,
            underlying,
            expiry,
            right,
        )
        self.client.placeOrder(parent_id, contract, parent)
        self.client.placeOrder(tp_id, contract, tp)
        self.client.placeOrder(sl_id, contract, sl)

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
        if not self.client.isConnected():
            raise RuntimeError("IBKR client is not connected")

        order_id = self.client.next_order_id
        self.client.next_order_id += 1

        contract = self._build_crypto_contract(symbol, exchange, currency)
        order = Order()
        order.action = action.upper()
        order.orderType = order_type
        if(action == "SELL" or action == "Sell" or action == "sell"):
            order.totalQuantity = quantity
        else:
            order.cashQty = 500  # For crypto, use cashQty instead of totalQuantity
        order.tif = tif

        if price is not None and order_type == "LMT":
            order.lmtPrice = price

        self.logger.debug(
            "Placing crypto order %s for %.8f %s (type=%s)",
            order_id,
            quantity,
            symbol,
            order_type,
        )
        self.client.placeOrder(order_id, contract, order)
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
        """Place a crypto bracket order: parent (market or limit) + TP + SL.

        Returns a dict with the created order IDs: {'parent': id, 'tp': id, 'sl': id}
        """
        if not self.client.isConnected():
            raise RuntimeError("IBKR client is not connected")
        tif = "IOC"  # For crypto, default to IOC to avoid orphaned orders
        contract = self._build_crypto_contract(symbol, exchange, currency)

        parent_id = self.client.next_order_id
        self.client.next_order_id += 1

        parent = Order()
        parent.orderType = "LMT" if limit_price is not None else "MKT"
        parent.action = action.upper()
      #  parent.totalQuantity = round(quantity,4)
        parent.cashQty = 500  # For crypto, use cashQty instead of totalQuantity
        parent.tif = tif
        # adding stop loss here itself 
        parent.auxPrice = round(stop_price,2)  # For crypto, set auxPrice on parent for better stop-loss handling
        if limit_price is not None and parent.orderType == "LMT":
            parent.lmtPrice = round(limit_price, 2)
        parent.transmit = True #False # For crypto, transmit the parent immediately to avoid orphaned child orders. The auxPrice will help ensure the stop-loss is active even if the parent fills partially.

        # Child: take-profit (limit opposite side)
        tp_id = self.client.next_order_id
        self.client.next_order_id += 1
        tp = Order()
        tp.action = "SELL" if action.lower() == "buy" else "BUY"
        tp.orderType = "LMT"
        #tp.totalQuantity = round(quantity,4)
        tp.cashQty = 500  # For crypto, use cashQty instead of totalQuantity
        tp.lmtPrice = round(take_profit_price, 4)
        tp.tif = tif
        tp.parentId = parent_id
        tp.transmit = False

        # Child: stop-loss (stop opposite side). This will be the last order and will transmit the group.
        sl_id = self.client.next_order_id
        self.client.next_order_id += 1
        sl = Order()
        sl.action = "SELL" if action.lower() == "buy" else "BUY"
        sl.orderType = "STP"
        sl.auxPrice = round(stop_price, 4)
        sl.totalQuantity = round(quantity,4)
        sl.tif = tif
        sl.parentId = parent_id
        sl.transmit = True

        # Place orders
        self.logger.debug("Placing crypto bracket order parent=%s tp=%s sl=%s for %s", parent_id, tp_id, sl_id, symbol)
        self.client.placeOrder(parent_id, contract, parent)
#        self.client.placeOrder(tp_id, contract, tp)
#        self.client.placeOrder(sl_id, contract, sl)

        return {"parent": parent_id, "tp": tp_id, "sl": sl_id}

    def cancel_order(self, order_id: int) -> None:
        """Cancel a pending order by its IB order ID."""
        if not self.client.isConnected():
            raise RuntimeError("IBKR client is not connected")

        self.logger.debug("Cancelling order %s", order_id)
        try:
            self.client.cancelOrder(int(order_id))
        except Exception as exc:
            self.logger.error("Failed to cancel order %s: %s", order_id, exc)
            raise

    def close_position(self, symbol: str, quantity: Optional[float] = None, tif: str = "GTC") -> int:
        """Close an existing position for `symbol` by submitting an opposite market order.

        If `quantity` is None, the full open position size will be closed.
        `tif` specifies the time-in-force (default: "GTC").
        Returns the placed order id.
        """
        if not self.client.isConnected():
            raise RuntimeError("IBKR client is not connected")

        # Refresh positions
        positions = self.get_positions()
        match = None
        for p in positions:
            if p.get("symbol") == symbol:
                match = p
                break

        if match is None:
            raise ValueError(f"No open position found for symbol {symbol}")

        open_qty = float(match.get("position", 0))
        if open_qty == 0:
            raise ValueError(f"Position for {symbol} is zero")

        # Determine quantity to close
        qty_to_close = abs(open_qty) if quantity is None else float(quantity)

        # Action is opposite of the current position sign
        action = "SELL" if open_qty > 0 else "BUY"

        # Place a market order to close
        order_id = self.place_order(symbol=symbol, action=action, quantity=qty_to_close, order_type="MKT", tif=tif)
        self.logger.info("Submitted close order %s for %s qty=%.2f tif=%s", order_id, symbol, qty_to_close, tif)
        return order_id

    def close_crypto_position(self, symbol: str, exchange: str, currency: str, quantity: Optional[float] = None, tif: str = "IOC") -> int:
        """Close an existing crypto position for `symbol` by submitting an opposite market order.

        If `quantity` is None, the full open position size will be closed.
        `tif` specifies the time-in-force (default: "GTC").
        Returns the placed order id.
        """
        if not self.client.isConnected():
            raise RuntimeError("IBKR client is not connected")
        tif = "IOC"  # For crypto, default to IOC to avoid orphaned orders
        # Refresh positions
        positions = self.get_positions()
        match = None
        for p in positions:
            if p.get("symbol") == symbol:
                match = p
                break

        if match is None:
            raise ValueError(f"No open position found for crypto symbol {symbol}")

        open_qty = float(match.get("position", 0))
        if open_qty == 0:
            raise ValueError(f"Position for {symbol} is zero")

        # Determine quantity to close
        qty_to_close = abs(open_qty) if quantity is None else float(quantity)

        # Action is opposite of the current position sign
        action = "SELL" if open_qty > 0 else "BUY"

        # Place a market order to close
        order_id = self.place_crypto_order(symbol=symbol, exchange=exchange, currency=currency, action=action, quantity=qty_to_close, order_type="MKT", tif=tif)
        self.logger.info("Submitted crypto close order %s for %s qty=%.8f tif=%s", order_id, symbol, qty_to_close, tif)
        return order_id