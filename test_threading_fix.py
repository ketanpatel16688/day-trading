"""
Test to verify that IBKRManager methods work correctly when called from different threads.
This demonstrates the fix for the event loop issue using asyncio.run_coroutine_threadsafe.
"""
import threading
import time
from unittest.mock import MagicMock, patch
from ibkr_trading_bot.ibkr_manager import IBKRManager


def test_call_in_ib_thread_from_same_thread():
    """Test that _call_in_ib_thread works when called from the same thread."""
    manager = IBKRManager()
    manager.ib = MagicMock()
    manager.ib.isConnected.return_value = True
    manager._ib_thread = threading.current_thread()
    manager._event_loop = None

    def sample_func():
        return "success"

    result = manager._call_in_ib_thread(sample_func)
    assert result == "success"
    print("[OK] _call_in_ib_thread works from same thread")


def test_get_open_orders_from_worker_thread():
    """Test that get_open_orders handles threading correctly."""
    manager = IBKRManager()
    manager.ib = MagicMock()
    manager.ib.isConnected.return_value = True
    manager.ib.reqAllOpenOrders.return_value = None
    manager.ib.openTrades.return_value = []

    # Set the main thread as the IB thread
    manager._ib_thread = threading.current_thread()
    import asyncio
    manager._event_loop = asyncio.new_event_loop()
    asyncio.set_event_loop(manager._event_loop)

    result = {"orders": None, "error": None}

    def worker():
        try:
            result["orders"] = manager.get_open_orders()
        except Exception as e:
            result["error"] = str(e)

    thread = threading.Thread(target=worker)
    thread.start()
    thread.join(timeout=5)

    if thread.is_alive():
        print("[ERROR] get_open_orders stuck in infinite loop")
        return False

    if result["error"] and "event loop" in result["error"].lower():
        print(f"[ERROR] Event loop error: {result['error']}")
        return False

    assert isinstance(result["orders"], list)
    print("[OK] get_open_orders works from worker thread")
    return True


def test_get_positions_from_worker_thread():
    """Test that get_positions handles threading correctly."""
    manager = IBKRManager()
    manager.ib = MagicMock()
    manager.ib.isConnected.return_value = True
    manager.ib.reqPositions.return_value = []

    manager._ib_thread = threading.current_thread()
    import asyncio
    manager._event_loop = asyncio.new_event_loop()
    asyncio.set_event_loop(manager._event_loop)

    result = {"positions": None, "error": None}

    def worker():
        try:
            result["positions"] = manager.get_positions()
        except Exception as e:
            result["error"] = str(e)

    thread = threading.Thread(target=worker)
    thread.start()
    thread.join(timeout=5)

    if thread.is_alive():
        print("[ERROR] get_positions stuck in infinite loop")
        return False

    if result["error"] and "event loop" in result["error"].lower():
        print(f"[ERROR] Event loop error: {result['error']}")
        return False

    assert isinstance(result["positions"], list)
    print("[OK] get_positions works from worker thread")
    return True


if __name__ == "__main__":
    print("\n=== Testing Threading Fix ===\n")
    test_call_in_ib_thread_from_same_thread()
    success1 = test_get_open_orders_from_worker_thread()
    success2 = test_get_positions_from_worker_thread()

    if success1 and success2:
        print("\n[OK] All threading tests passed!")
    else:
        print("\n[ERROR] Some tests failed")
