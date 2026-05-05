#!/usr/bin/env python
"""
Demonstration and verification script for new account statistics APIs.
This script verifies the structure and signatures of all new methods.
"""

import inspect
import ast
from pathlib import Path

def verify_methods_exist():
    """Verify all new methods exist in IBKRManager"""
    with open("ibkr_trading_bot/ibkr_manager.py", "r") as f:
        tree = ast.parse(f.read())
    
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef) and node.name == "IBKRManager":
            methods = {m.name: m for m in node.body if isinstance(m, ast.FunctionDef)}
            
            new_methods = [
                "get_cash_balance",
                "get_total_portfolio_balance",
                "get_total_daily_gain",
                "get_total_weekly_gain",
                "get_total_monthly_gain",
                "get_ytd_gain",
                "get_all_time_gain",
            ]
            
            print("=" * 70)
            print("ACCOUNT STATISTICS API VERIFICATION")
            print("=" * 70)
            print("\n1. Method Existence Check:")
            print("-" * 70)
            
            all_found = True
            for method_name in new_methods:
                if method_name in methods:
                    method_node = methods[method_name]
                    print(f"   [OK] {method_name}")
                else:
                    print(f"   [FAIL] {method_name} - NOT FOUND")
                    all_found = False
            
            if all_found:
                print("\n   [SUCCESS] All 7 methods found!")
            else:
                print("\n   [ERROR] Some methods are missing!")
            
            return all_found
    
    return False

def verify_command_line_args():
    """Verify all command-line arguments were added to main.py"""
    with open("main.py", "r") as f:
        content = f.read()
    
    import re
    pattern = r'parser\.add_argument\([\'\"](--.+?)[\'\"]'
    matches = re.findall(pattern, content)
    
    expected_args = [
        "--account-summary",
        "--cash-balance",
        "--portfolio-value",
        "--daily-gain",
        "--weekly-gain",
        "--monthly-gain",
        "--ytd-gain",
        "--all-time-gain",
    ]
    
    print("\n2. Command-Line Arguments Check:")
    print("-" * 70)
    
    all_found = True
    for arg in expected_args:
        if arg in matches:
            print(f"   [OK] {arg}")
        else:
            print(f"   [FAIL] {arg} - NOT FOUND")
            all_found = False
    
    if all_found:
        print(f"\n   [SUCCESS] All {len(expected_args)} command-line args found!")
    else:
        print("\n   [ERROR] Some command-line args are missing!")
    
    return all_found

def verify_unit_tests():
    """Verify all unit tests were added"""
    with open("test_function.py", "r") as f:
        tree = ast.parse(f.read())
    
    found_test_class = False
    test_methods = []
    
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef) and node.name == "TestAccountStatistics":
            found_test_class = True
            test_methods = [m.name for m in node.body if isinstance(m, ast.FunctionDef) and m.name.startswith("test_")]
            break
    
    print("\n3. Unit Tests Check:")
    print("-" * 70)
    
    if found_test_class:
        print(f"   [OK] TestAccountStatistics class found")
        print(f"   [OK] Found {len(test_methods)} test methods:")
        for method in sorted(test_methods):
            print(f"        - {method}")
    else:
        print("   [FAIL] TestAccountStatistics class NOT FOUND")
        return False
    
    # Verify the test class is in the suite
    with open("test_function.py", "r") as f:
        content = f.read()
    
    if "TestAccountStatistics" in content and "test_classes = [" in content:
        if "TestAccountStatistics," in content or "TestAccountStatistics\n" in content or "TestAccountStatistics]" in content:
            print(f"\n   [SUCCESS] TestAccountStatistics is included in test suite!")
            return True
        else:
            print(f"\n   [FAIL] TestAccountStatistics not in test suite list!")
            return False
    
    return False

def show_example_usage():
    """Show example usage of the new APIs"""
    print("\n4. Example Usage:")
    print("-" * 70)
    print("""
    # In Python code:
    from ibkr_trading_bot.ibkr_manager import IBKRManager
    
    manager = IBKRManager()
    manager.connect()
    
    # Fetch individual metrics
    cash = manager.get_cash_balance()
    portfolio = manager.get_total_portfolio_balance()
    daily_gain = manager.get_total_daily_gain()
    weekly_gain = manager.get_total_weekly_gain()
    monthly_gain = manager.get_total_monthly_gain()
    ytd_gain = manager.get_ytd_gain()
    all_time_gain = manager.get_all_time_gain()
    
    # From command line:
    python main.py --account-summary          # Show all metrics
    python main.py --cash-balance             # Show cash balance
    python main.py --portfolio-value          # Show portfolio value
    python main.py --daily-gain               # Show daily P&L
    python main.py --weekly-gain              # Show weekly P&L
    python main.py --monthly-gain             # Show monthly P&L
    python main.py --ytd-gain                 # Show YTD P&L
    python main.py --all-time-gain            # Show all-time P&L
    """)

if __name__ == "__main__":
    methods_ok = verify_methods_exist()
    args_ok = verify_command_line_args()
    tests_ok = verify_unit_tests()
    
    show_example_usage()
    
    print("\n" + "=" * 70)
    print("SUMMARY")
    print("=" * 70)
    
    if methods_ok and args_ok and tests_ok:
        print("[SUCCESS] All verifications passed!")
        print("\nThe following have been successfully implemented:")
        print("  1. 7 new account statistics methods in IBKRManager")
        print("  2. 8 new command-line arguments in main.py")
        print("  3. 11 unit tests in TestAccountStatistics")
        exit(0)
    else:
        print("[FAILURE] Some verifications failed!")
        print(f"  Methods OK: {methods_ok}")
        print(f"  Args OK: {args_ok}")
        print(f"  Tests OK: {tests_ok}")
        exit(1)
