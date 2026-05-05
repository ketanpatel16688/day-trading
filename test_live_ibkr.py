#!/usr/bin/env python3
"""
Live IBKR integration test.
Requires TWS or IB Gateway running on 127.0.0.1:7497

Tests:
1. Connect to IBKR
2. Fetch positions
3. Disconnect

Usage:
    python test_live_ibkr.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

import config
from config import load_config
from ibkr_trading_bot.ibkr_manager import IBKRManager


def test_connection_and_positions():
    """Test connecting to IBKR and fetching positions"""
    print("=" * 70)
    print("LIVE IBKR INTEGRATION TEST")
    print("=" * 70)
    print("\n[TEST] Connecting to IBKR...")
    config_path = Path("config.json")
    config = load_config(config_path)
    ibkr_config = config.get("ibkr", {})

    manager = IBKRManager(host="127.0.0.1", port=ibkr_config.get("port", 7497), client_id=9999)

    try:
        manager.connect()
        print("[OK] Connected to IBKR")

        if not manager.ib.isConnected():
            print("[FAIL] Connection check failed")
            return False

        print("\n[TEST] Fetching positions...")
        positions = manager.get_positions()
        print(f"[OK] Fetched {len(positions)} position(s)")

        if positions:
            print("\nPositions:")
            for pos in positions:
                print(f"  {pos['symbol']:10} | Qty: {pos['position']:10} | Avg Cost: {pos['avgCost']:10.2f}")
        else:
            print("  (No open positions)")

        print("\n" + "=" * 70)
        print("[OK] ALL TESTS PASSED - ib_async conversion successful!")
        print("=" * 70)
        return True

    except Exception as e:
        print(f"[FAIL] Error during test: {e}")
        print("\nMake sure TWS or IB Gateway is running on 127.0.0.1:7497")
        return False
    finally:
        try:
            manager.disconnect()
            print("\n[OK] Disconnected from IBKR")
        except Exception as e:
            print(f"\n[WARN] Error during disconnect: {e}")


if __name__ == "__main__":
    success = test_connection_and_positions()
    sys.exit(0 if success else 1)
