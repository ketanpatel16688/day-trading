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

    def error(self, reqId: int, errorCode: int, errorString: str, *args) -> None:
        self.logger.error("IBKR error. reqId=%s errCode=%s errMsg=%s", reqId, errorCode, errorString)


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
    ) -> List[Dict[str, object]]:
        if not self.client.isConnected():
            raise RuntimeError("IBKR client is not connected")

        # prepare per-request buffer and event to avoid mixing responses
        request_id = int(time.time() * 1000) % 100000
        self.client._historical_data_map[request_id] = []
        ev = threading.Event()
        self.client._historical_data_events[request_id] = ev

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

    def get_latest_close(self, symbol: str, timeout: int = 20) -> Optional[float]:
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
    ) -> int:
        if not self.client.isConnected():
            raise RuntimeError("IBKR client is not connected")

        order_id = self.client.next_order_id
        self.client.next_order_id += 1

        contract = self._build_stock_contract(symbol)
        order = Order()
        order.action = action.upper()
        order.orderType = order_type
        order.totalQuantity = quantity

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
        parent.totalQuantity = quantity
        if limit_price is not None and parent.orderType == "LMT":
            parent.lmtPrice = limit_price
        parent.transmit = False

        # Child: take-profit (limit opposite side)
        tp_id = self.client.next_order_id
        self.client.next_order_id += 1
        tp = Order()
        tp.action = "SELL" if action.lower() == "buy" else "BUY"
        tp.orderType = "LMT"
        tp.totalQuantity = quantity
        tp.lmtPrice = take_profit_price
        tp.parentId = parent_id
        tp.transmit = False

        # Child: stop-loss (stop opposite side). This will be the last order and will transmit the group.
        sl_id = self.client.next_order_id
        self.client.next_order_id += 1
        sl = Order()
        sl.action = "SELL" if action.lower() == "buy" else "BUY"
        sl.orderType = "STP"
        sl.auxPrice = stop_price
        sl.totalQuantity = quantity
        sl.parentId = parent_id
        sl.transmit = True

        # Place orders
        self.logger.debug("Placing bracket order parent=%s tp=%s sl=%s for %s", parent_id, tp_id, sl_id, symbol)
        self.client.placeOrder(parent_id, contract, parent)
        self.client.placeOrder(tp_id, contract, tp)
        self.client.placeOrder(sl_id, contract, sl)

        return {"parent": parent_id, "tp": tp_id, "sl": sl_id}
