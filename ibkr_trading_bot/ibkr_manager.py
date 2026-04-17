import logging
import threading
import time
from datetime import datetime
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
        self.historical_data: List[Dict[str, object]] = []
        self._historical_data_event = threading.Event()
        self.next_order_id = 1

    def nextValidId(self, orderId: int) -> None:
        self.next_order_id = orderId
        self.logger.info("Received next valid order ID %s", orderId)

    def historicalData(self, reqId: int, bar) -> None:
        self.historical_data.append(
            {
                "date": bar.date,
                "open": bar.open,
                "high": bar.high,
                "low": bar.low,
                "close": bar.close,
                "volume": bar.volume,
            }
        )

    def historicalDataEnd(self, reqId: int, start: str, end: str) -> None:
        self.logger.info("Historical data download complete for request %s", reqId)
        self._historical_data_event.set()

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
        self.logger.info("Connecting to IBKR at %s:%s client=%s", self.host, self.port, self.client_id)
        self.client.connect(self.host, self.port, self.client_id)
        self._thread = threading.Thread(target=self.client.run, daemon=True)
        self._thread.start()
        time.sleep(1)

    def disconnect(self) -> None:
        if self.client.isConnected():
            self.logger.info("Disconnecting from IBKR")
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

        self.client.historical_data = []
        self.client._historical_data_event.clear()

        contract = self._build_stock_contract(symbol)
        request_time = datetime.now().strftime("%Y%m%d %H:%M:%S")
        request_id = int(time.time() * 1000) % 100000

        self.logger.info(
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

        if not self.client._historical_data_event.wait(timeout=20):
            raise TimeoutError(f"Timed out waiting for historical data for {symbol}")

        return self.client.historical_data

    def place_order(
        self,
        symbol: str,
        action: str,
        quantity: int,
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

        self.logger.info(
            "Placing order %s for %s shares of %s (type=%s)",
            order_id,
            quantity,
            symbol,
            order_type,
        )
        self.client.placeOrder(order_id, contract, order)
        return order_id
