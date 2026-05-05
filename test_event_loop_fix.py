"""
Verify that IBKRManager methods work when called from Flask worker threads.
The fix routes all ib_async calls through a single dedicated worker thread
so they always run on the event loop that owns the IBKR socket.
"""
import threading
from unittest.mock import MagicMock
from ibkr_trading_bot.ibkr_manager import IBKRManager


def _make_manager():
    mgr = IBKRManager()
    mgr.ib = MagicMock()
    mgr.ib.isConnected.return_value = True
    # Simulate connect() having recorded the worker thread id
    # by running a no-op through the executor so _ib_thread_id is set.
    mgr._executor.submit(lambda: setattr(mgr, "_ib_thread_id", threading.get_ident())).result()
    return mgr


def test_get_open_orders_from_flask_thread():
    mgr = _make_manager()
    mgr.ib.reqAllOpenOrders.return_value = None
    mgr.ib.openTrades.return_value = []

    result = {"orders": None, "error": None}

    def flask_worker():
        try:
            result["orders"] = mgr.get_open_orders()
        except Exception as e:
            result["error"] = str(e)

    t = threading.Thread(target=flask_worker, daemon=True)
    t.start()
    t.join(timeout=10)

    assert not t.is_alive(), "get_open_orders stuck"
    assert result["error"] is None, f"Error: {result['error']}"
    assert isinstance(result["orders"], list)
    print("[OK] get_open_orders works from Flask worker thread")


def test_get_positions_from_flask_thread():
    mgr = _make_manager()
    mgr.ib.reqPositions.return_value = []

    result = {"positions": None, "error": None}

    def flask_worker():
        try:
            result["positions"] = mgr.get_positions()
        except Exception as e:
            result["error"] = str(e)

    t = threading.Thread(target=flask_worker, daemon=True)
    t.start()
    t.join(timeout=10)

    assert not t.is_alive(), "get_positions stuck"
    assert result["error"] is None, f"Error: {result['error']}"
    assert isinstance(result["positions"], list)
    print("[OK] get_positions works from Flask worker thread")


def test_place_order_from_flask_thread():
    mgr = _make_manager()
    mgr.ib.placeOrder.return_value = None

    result = {"order_id": None, "error": None}

    def flask_worker():
        try:
            result["order_id"] = mgr.place_order("AAPL", "BUY", 1.0)
        except Exception as e:
            result["error"] = str(e)

    t = threading.Thread(target=flask_worker, daemon=True)
    t.start()
    t.join(timeout=10)

    assert not t.is_alive(), "place_order stuck"
    assert result["error"] is None, f"Error: {result['error']}"
    assert isinstance(result["order_id"], int)
    print("[OK] place_order works from Flask worker thread")


def test_ib_calls_run_on_worker_thread():
    """Confirm that ib.* calls actually execute on the dedicated worker thread, not the Flask thread."""
    mgr = _make_manager()
    called_from = {}

    def fake_req_positions():
        called_from["tid"] = threading.get_ident()
        return []

    mgr.ib.reqPositions.side_effect = fake_req_positions

    flask_tid = {}

    def flask_worker():
        flask_tid["tid"] = threading.get_ident()
        mgr.get_positions()

    t = threading.Thread(target=flask_worker, daemon=True)
    t.start()
    t.join(timeout=10)

    assert not t.is_alive()
    assert called_from["tid"] == mgr._ib_thread_id, "IB call ran on wrong thread"
    assert called_from["tid"] != flask_tid["tid"], "IB call ran on Flask thread (not routed)"
    print("[OK] IB calls execute on the dedicated worker thread, not the Flask thread")


if __name__ == "__main__":
    print("\n=== Testing ThreadPoolExecutor-based IB thread fix ===\n")
    test_get_open_orders_from_flask_thread()
    test_get_positions_from_flask_thread()
    test_place_order_from_flask_thread()
    test_ib_calls_run_on_worker_thread()
    print("\n[OK] All tests passed!")
