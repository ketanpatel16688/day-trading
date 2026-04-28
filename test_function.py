#!/usr/bin/env python
"""Quick test to verify _get_open_orders_for function exists"""

import sys
from pathlib import Path

# Test 1: Import the module
try:
    import trade_alerts
    print("✓ Module imported successfully")
except Exception as e:
    print(f"✗ Failed to import module: {e}")
    sys.exit(1)

# Test 2: Check if function exists
if hasattr(trade_alerts, '_get_open_orders_for'):
    print("✓ Function '_get_open_orders_for' found in module")
else:
    print("✗ Function '_get_open_orders_for' NOT found in module")
    print(f"Available functions: {[name for name in dir(trade_alerts) if name.startswith('_get')]}")
    sys.exit(1)

# Test 3: Check function is callable
func = getattr(trade_alerts, '_get_open_orders_for')
if callable(func):
    print(f"✓ Function is callable: {func}")
else:
    print(f"✗ Function is not callable")
    sys.exit(1)

print("\n✓ All checks passed! The function is properly defined.")
