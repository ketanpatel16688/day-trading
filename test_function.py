#!/usr/bin/env python
"""
Comprehensive Test Suite for Trading Bot
Tests all APIs, functions, and error handling in random order.
Run this before committing code to ensure overall repo health.

Usage:
    python test_function.py                    # Run all tests in random order
    python test_function.py -v                 # Verbose output
    python test_function.py TestIBKRManager    # Run specific test class
    python test_function.py TestIBKRManager.test_place_order_valid
"""

import unittest
import sys
import random
from unittest.mock import Mock, patch, MagicMock
from pathlib import Path
from typing import Dict, List

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent))

from ibkr_trading_bot.ibkr_manager import IBKRManager
from risk_management import RiskManager
import trade_alerts


class TestIBKRManagerParameterValidation(unittest.TestCase):
    """Test parameter validation in IBKRManager order placement APIs"""

    def setUp(self):
        """Set up test fixtures"""
        self.manager = IBKRManager()
        self.manager.client = MagicMock()
        self.manager.client.isConnected.return_value = True
        self.manager.client.next_order_id = 1

    def test_place_order_valid_parameters(self):
        """Test place_order with valid parameters"""
        try:
            order_id = self.manager.place_order(
                symbol="AAPL",
                action="BUY",
                quantity=100,
                order_type="MKT"
            )
            self.assertGreater(order_id, 0)
            self.assertTrue(self.manager.client.placeOrder.called)
            print("[PASS] place_order accepts valid parameters")
        except Exception as e:
            self.fail(f"place_order should accept valid parameters: {e}")

    def test_place_order_invalid_quantity(self):
        """Test place_order rejects invalid quantity"""
        with self.assertRaises(ValueError) as ctx:
            self.manager.place_order("AAPL", "BUY", quantity=-100)
        self.assertIn("quantity", str(ctx.exception).lower())
        print("[OK] place_order rejects negative quantity")

    def test_place_order_zero_quantity(self):
        """Test place_order rejects zero quantity"""
        with self.assertRaises(ValueError) as ctx:
            self.manager.place_order("AAPL", "BUY", quantity=0)
        self.assertIn("quantity", str(ctx.exception).lower())
        print("[OK] place_order rejects zero quantity")

    def test_place_order_invalid_action(self):
        """Test place_order rejects invalid action"""
        with self.assertRaises(ValueError) as ctx:
            self.manager.place_order("AAPL", "INVALID", quantity=100)
        self.assertIn("action", str(ctx.exception).lower())
        print("[OK] place_order rejects invalid action")

    def test_place_order_invalid_order_type(self):
        """Test place_order rejects invalid order type"""
        with self.assertRaises(ValueError) as ctx:
            self.manager.place_order("AAPL", "BUY", quantity=100, order_type="INVALID")
        self.assertIn("order_type", str(ctx.exception).lower())
        print("[OK] place_order rejects invalid order_type")

    def test_place_order_lmt_requires_price(self):
        """Test place_order LMT requires price"""
        with self.assertRaises(ValueError) as ctx:
            self.manager.place_order("AAPL", "BUY", quantity=100, order_type="LMT", price=None)
        self.assertIn("price", str(ctx.exception).lower())
        print("[OK] place_order requires price for LMT orders")

    def test_place_bracket_order_valid(self):
        """Test place_bracket_order with valid parameters"""
        try:
            result = self.manager.place_bracket_order(
                symbol="AAPL",
                action="BUY",
                quantity=100,
                stop_price=150.0,
                take_profit_price=160.0
            )
            self.assertIn("parent", result)
            self.assertIn("tp", result)
            self.assertIn("sl", result)
            print("[OK] place_bracket_order accepts valid parameters")
        except Exception as e:
            self.fail(f"place_bracket_order should accept valid parameters: {e}")

    def test_place_bracket_order_invalid_stop_price(self):
        """Test place_bracket_order rejects invalid stop_price"""
        with self.assertRaises(ValueError) as ctx:
            self.manager.place_bracket_order(
                symbol="AAPL",
                action="BUY",
                quantity=100,
                stop_price=-150.0,
                take_profit_price=160.0
            )
        self.assertIn("stop_price", str(ctx.exception).lower())
        print("[OK] place_bracket_order rejects negative stop_price")

    def test_place_bracket_order_invalid_tp_price(self):
        """Test place_bracket_order rejects invalid take_profit_price"""
        with self.assertRaises(ValueError) as ctx:
            self.manager.place_bracket_order(
                symbol="AAPL",
                action="BUY",
                quantity=100,
                stop_price=150.0,
                take_profit_price=0
            )
        self.assertIn("take_profit_price", str(ctx.exception).lower())
        print("[OK] place_bracket_order rejects invalid take_profit_price")

    def test_place_option_order_valid(self):
        """Test place_option_order with valid parameters"""
        try:
            order_id = self.manager.place_option_order(
                underlying="AAPL",
                expiry="20240821",
                strike=150.0,
                right="C",
                action="BUY",
                quantity=10
            )
            self.assertGreater(order_id, 0)
            print("[OK] place_option_order accepts valid parameters")
        except Exception as e:
            self.fail(f"place_option_order should accept valid parameters: {e}")

    def test_place_option_order_invalid_right(self):
        """Test place_option_order rejects invalid right"""
        with self.assertRaises(ValueError) as ctx:
            self.manager.place_option_order(
                underlying="AAPL",
                expiry="20240821",
                strike=150.0,
                right="X",
                action="BUY",
                quantity=10
            )
        self.assertIn("right", str(ctx.exception).lower())
        print("[OK] place_option_order rejects invalid right")

    def test_place_option_order_invalid_strike(self):
        """Test place_option_order rejects invalid strike"""
        with self.assertRaises(ValueError) as ctx:
            self.manager.place_option_order(
                underlying="AAPL",
                expiry="20240821",
                strike=-150.0,
                right="C",
                action="BUY",
                quantity=10
            )
        self.assertIn("strike", str(ctx.exception).lower())
        print("[OK] place_option_order rejects invalid strike")

    def test_place_crypto_order_valid_buy(self):
        """Test place_crypto_order with valid BUY parameters"""
        try:
            order_id = self.manager.place_crypto_order(
                symbol="SOL",
                exchange="PAXOS",
                currency="USD",
                action="BUY",
                quantity=1.5
            )
            self.assertGreater(order_id, 0)
            print("[OK] place_crypto_order accepts valid BUY parameters")
        except Exception as e:
            self.fail(f"place_crypto_order should accept valid BUY parameters: {e}")

    def test_place_crypto_order_sell_invalid_quantity(self):
        """Test place_crypto_order SELL with invalid quantity"""
        with self.assertRaises(ValueError) as ctx:
            self.manager.place_crypto_order(
                symbol="SOL",
                exchange="PAXOS",
                currency="USD",
                action="SELL",
                quantity=-1.0
            )
        self.assertIn("quantity", str(ctx.exception).lower())
        print("[OK] place_crypto_order rejects negative quantity")

    def test_place_crypto_order_sell_no_position(self):
        """Test place_crypto_order SELL without position"""
        with self.assertRaises(ValueError) as ctx:
            self.manager.place_crypto_order(
                symbol="NONEXISTENT",
                exchange="PAXOS",
                currency="USD",
                action="SELL",
                quantity=0.5
            )
        self.assertIn("position", str(ctx.exception).lower())
        print("[OK] place_crypto_order rejects SELL with no position")

    def test_place_crypto_order_invalid_action(self):
        """Test place_crypto_order rejects invalid action"""
        with self.assertRaises(ValueError) as ctx:
            self.manager.place_crypto_order(
                symbol="SOL",
                exchange="PAXOS",
                currency="USD",
                action="INVALID",
                quantity=1.0
            )
        self.assertIn("action", str(ctx.exception).lower())
        print("[OK] place_crypto_order rejects invalid action")


class TestConnectionValidation(unittest.TestCase):
    """Test connection validation across APIs"""

    def setUp(self):
        """Set up test fixtures"""
        self.manager = IBKRManager()
        self.manager.client = MagicMock()
        self.manager.client.isConnected.return_value = False

    def test_place_order_requires_connection(self):
        """Test place_order requires IBKR connection"""
        with self.assertRaises(RuntimeError) as ctx:
            self.manager.place_order("AAPL", "BUY", 100)
        self.assertIn("not connected", str(ctx.exception).lower())
        print("[OK] place_order requires IBKR connection")

    def test_place_bracket_order_requires_connection(self):
        """Test place_bracket_order requires IBKR connection"""
        with self.assertRaises(RuntimeError) as ctx:
            self.manager.place_bracket_order("AAPL", "BUY", 100, 150, 160)
        self.assertIn("not connected", str(ctx.exception).lower())
        print("[OK] place_bracket_order requires IBKR connection")

    def test_place_crypto_order_requires_connection(self):
        """Test place_crypto_order requires IBKR connection"""
        with self.assertRaises(RuntimeError) as ctx:
            self.manager.place_crypto_order("SOL", "PAXOS", "USD", "BUY", 1.0)
        self.assertIn("not connected", str(ctx.exception).lower())
        print("[OK] place_crypto_order requires IBKR connection")


class TestTradeAlertsValidation(unittest.TestCase):
    """Test webhook and trade_alerts validation"""

    def test_webhook_function_exists(self):
        """Test webhook function exists"""
        self.assertTrue(hasattr(trade_alerts, 'webhook'))
        self.assertTrue(callable(trade_alerts.webhook))
        print("[OK] webhook function exists and is callable")

    def test_get_position_for_exists(self):
        """Test _get_position_for function exists"""
        self.assertTrue(hasattr(trade_alerts, '_get_position_for'))
        self.assertTrue(callable(trade_alerts._get_position_for))
        print("[OK] _get_position_for function exists")

    def test_get_open_orders_for_exists(self):
        """Test _get_open_orders_for function exists"""
        self.assertTrue(hasattr(trade_alerts, '_get_open_orders_for'))
        self.assertTrue(callable(trade_alerts._get_open_orders_for))
        print("[OK] _get_open_orders_for function exists")

    def test_cancel_orders_for_exists(self):
        """Test _cancel_orders_for function exists"""
        self.assertTrue(hasattr(trade_alerts, '_cancel_orders_for'))
        self.assertTrue(callable(trade_alerts._cancel_orders_for))
        print("[OK] _cancel_orders_for function exists")


class TestRiskManagerValidation(unittest.TestCase):
    """Test RiskManager parameter handling"""

    def setUp(self):
        """Set up test fixtures"""
        self.mock_manager = MagicMock()
        self.config = {"risk": {"initial_capital": 100000}}
        self.risk_manager = RiskManager(self.mock_manager, self.config)

    def test_get_initial_capital_returns_number(self):
        """Test get_initial_capital returns a number"""
        self.mock_manager.get_settled_cash.return_value = None
        capital = self.risk_manager.get_initial_capital()
        self.assertIsInstance(capital, (int, float))
        self.assertGreater(capital, 0)
        print("[OK] get_initial_capital returns positive number")

    def test_calculate_quantity_returns_none_on_invalid_atr(self):
        """Test calculate_quantity handles invalid ATR"""
        self.mock_manager.calculate_atr.return_value = 0
        qty = self.risk_manager.calculate_quantity("AAPL", 100000)
        self.assertIsNone(qty)
        print("[OK] calculate_quantity returns None when ATR is invalid")

    def test_get_risk_params_returns_tuple(self):
        """Test get_risk_params returns tuple"""
        self.mock_manager.get_settled_cash.return_value = 100000.0
        self.mock_manager.get_stock_price.return_value = 150.0
        self.mock_manager.calculate_atr.return_value = 2.5
        result = self.risk_manager.get_risk_params("AAPL", "BUY")
        self.assertIsInstance(result, tuple)
        self.assertEqual(len(result), 2)
        print("[OK] get_risk_params returns tuple of (qty, sl_price)")

    def test_calculate_sl_returns_float(self):
        """Test calculate_sl returns float"""
        sl = self.risk_manager.calculate_sl(150.0, 2.5, "BUY")
        self.assertIsInstance(sl, (int, float))
        self.assertLess(sl, 150.0)  # SL should be below entry for BUY
        print("[OK] calculate_sl returns proper value")


class TestTypeConsistency(unittest.TestCase):
    """Test type consistency across APIs"""

    def setUp(self):
        """Set up test fixtures"""
        self.manager = IBKRManager()
        self.manager.client = MagicMock()
        self.manager.client.isConnected.return_value = True
        self.manager.client.next_order_id = 1

    def test_place_order_returns_int(self):
        """Test place_order returns integer order ID"""
        result = self.manager.place_order("AAPL", "BUY", 100)
        self.assertIsInstance(result, int)
        print("[OK] place_order returns int order ID")

    def test_place_bracket_order_returns_dict(self):
        """Test place_bracket_order returns dict with order IDs"""
        result = self.manager.place_bracket_order("AAPL", "BUY", 100, 150, 160)
        self.assertIsInstance(result, dict)
        self.assertIn("parent", result)
        self.assertIn("tp", result)
        self.assertIn("sl", result)
        print("[OK] place_bracket_order returns dict with parent/tp/sl")

    def test_place_option_order_returns_int(self):
        """Test place_option_order returns integer order ID"""
        result = self.manager.place_option_order(
            "AAPL", "20240821", 150.0, "C", "BUY", 10
        )
        self.assertIsInstance(result, int)
        print("[OK] place_option_order returns int order ID")

    def test_place_crypto_order_returns_int(self):
        """Test place_crypto_order returns integer order ID"""
        result = self.manager.place_crypto_order(
            "SOL", "PAXOS", "USD", "BUY", 1.5
        )
        self.assertIsInstance(result, int)
        print("[OK] place_crypto_order returns int order ID")


class TestImportsAndDependencies(unittest.TestCase):
    """Test all imports and dependencies are available"""

    def test_ibkr_manager_import(self):
        """Test IBKRManager can be imported"""
        try:
            from ibkr_trading_bot.ibkr_manager import IBKRManager
            self.assertTrue(True)
            print("[OK] IBKRManager imports successfully")
        except ImportError as e:
            self.fail(f"Failed to import IBKRManager: {e}")

    def test_risk_manager_import(self):
        """Test RiskManager can be imported"""
        try:
            from risk_management import RiskManager
            self.assertTrue(True)
            print("[OK] RiskManager imports successfully")
        except ImportError as e:
            self.fail(f"Failed to import RiskManager: {e}")

    def test_trade_alerts_import(self):
        """Test trade_alerts can be imported"""
        try:
            import trade_alerts
            self.assertTrue(True)
            print("[OK] trade_alerts imports successfully")
        except ImportError as e:
            self.fail(f"Failed to import trade_alerts: {e}")

    def test_config_module_import(self):
        """Test config module can be imported"""
        try:
            from config import load_config, configure_logging
            self.assertTrue(True)
            print("[OK] config module imports successfully")
        except ImportError as e:
            self.fail(f"Failed to import config: {e}")


class TestEdgeCases(unittest.TestCase):
    """Test edge cases and boundary conditions"""

    def setUp(self):
        """Set up test fixtures"""
        self.manager = IBKRManager()
        self.manager.client = MagicMock()
        self.manager.client.isConnected.return_value = True
        self.manager.client.next_order_id = 1

    def test_place_order_very_small_quantity(self):
        """Test place_order with very small quantity"""
        try:
            order_id = self.manager.place_order("AAPL", "BUY", 0.0001)
            self.assertGreater(order_id, 0)
            print("[OK] place_order handles very small quantities")
        except Exception as e:
            self.fail(f"place_order should handle small quantities: {e}")

    def test_place_order_very_large_quantity(self):
        """Test place_order with very large quantity"""
        try:
            order_id = self.manager.place_order("AAPL", "BUY", 1000000)
            self.assertGreater(order_id, 0)
            print("[OK] place_order handles very large quantities")
        except Exception as e:
            self.fail(f"place_order should handle large quantities: {e}")

    def test_place_bracket_order_with_limit_price(self):
        """Test place_bracket_order with limit price"""
        try:
            result = self.manager.place_bracket_order(
                symbol="AAPL",
                action="BUY",
                quantity=100,
                stop_price=150.0,
                take_profit_price=160.0,
                limit_price=155.0
            )
            self.assertIn("parent", result)
            print("[OK] place_bracket_order accepts limit_price")
        except Exception as e:
            self.fail(f"place_bracket_order should accept limit_price: {e}")

    def test_action_case_insensitivity(self):
        """Test action parameter is case-insensitive"""
        try:
            # These should all work
            self.manager.place_order("AAPL", "buy", 100)
            self.manager.place_order("AAPL", "BUY", 100)
            self.manager.place_order("AAPL", "Buy", 100)
            print("[OK] Action parameter is case-insensitive")
        except Exception as e:
            self.fail(f"Action should be case-insensitive: {e}")


class TestCryptoSpecifics(unittest.TestCase):
    """Test crypto-specific functionality"""

    def setUp(self):
        """Set up test fixtures"""
        self.manager = IBKRManager()
        self.manager.client = MagicMock()
        self.manager.client.isConnected.return_value = True
        self.manager.client.next_order_id = 1

    def test_place_crypto_order_buy_uses_cashqty(self):
        """Test place_crypto_order BUY uses cashQty"""
        self.manager.place_crypto_order("SOL", "PAXOS", "USD", "BUY", 1.0)
        # Check that placeOrder was called
        self.assertTrue(self.manager.client.placeOrder.called)
        print("[OK] place_crypto_order BUY operation completes")

    def test_place_crypto_bracket_order_structure(self):
        """Test place_crypto_bracket_order returns proper structure"""
        result = self.manager.place_crypto_bracket_order(
            symbol="SOL",
            exchange="PAXOS",
            currency="USD",
            action="BUY",
            quantity=1.0,
            stop_price=140.0,
            take_profit_price=160.0
        )
        self.assertEqual(set(result.keys()), {"parent", "tp", "sl"})
        print("[OK] place_crypto_bracket_order returns correct structure")


class TestAccountStatistics(unittest.TestCase):
    """Test account statistics and balance APIs"""

    def setUp(self):
        """Set up test fixtures"""
        self.manager = IBKRManager()
        self.manager.client = MagicMock()
        self.manager.client.isConnected.return_value = True
        self.manager.client.next_order_id = 1

    def test_get_cash_balance_returns_float(self):
        """Test get_cash_balance returns float"""
        with patch.object(self.manager, 'get_account_summary') as mock_summary:
            mock_summary.return_value = {"CashBalance": "50000.50"}
            result = self.manager.get_cash_balance()
            self.assertIsInstance(result, float)
            self.assertEqual(result, 50000.50)
            print("[OK] get_cash_balance returns float")

    def test_get_cash_balance_handles_missing_value(self):
        """Test get_cash_balance handles missing values gracefully"""
        with patch.object(self.manager, 'get_account_summary') as mock_summary:
            mock_summary.return_value = {}
            result = self.manager.get_cash_balance()
            self.assertEqual(result, 0.0)
            print("[OK] get_cash_balance handles missing values")

    def test_get_total_portfolio_balance_returns_float(self):
        """Test get_total_portfolio_balance returns float"""
        with patch.object(self.manager, 'get_account_summary') as mock_summary:
            mock_summary.return_value = {"TotalCashBalance": "150000.75"}
            result = self.manager.get_total_portfolio_balance()
            self.assertIsInstance(result, float)
            self.assertEqual(result, 150000.75)
            print("[OK] get_total_portfolio_balance returns float")

    def test_get_total_daily_gain_returns_float(self):
        """Test get_total_daily_gain returns float"""
        with patch.object(self.manager, 'get_account_summary') as mock_summary:
            mock_summary.return_value = {"DayTradesBought": "1500.25"}
            result = self.manager.get_total_daily_gain()
            self.assertIsInstance(result, float)
            print("[OK] get_total_daily_gain returns float")

    def test_get_total_weekly_gain_returns_float(self):
        """Test get_total_weekly_gain returns float"""
        with patch.object(self.manager, 'get_account_summary') as mock_summary:
            mock_summary.return_value = {"UnrealizedPnL": "5000.00"}
            result = self.manager.get_total_weekly_gain()
            self.assertIsInstance(result, float)
            self.assertEqual(result, 5000.00)
            print("[OK] get_total_weekly_gain returns float")

    def test_get_total_monthly_gain_returns_float(self):
        """Test get_total_monthly_gain returns float"""
        with patch.object(self.manager, 'get_account_summary') as mock_summary:
            mock_summary.return_value = {"RealizedPnL": "10000.00"}
            result = self.manager.get_total_monthly_gain()
            self.assertIsInstance(result, float)
            self.assertEqual(result, 10000.00)
            print("[OK] get_total_monthly_gain returns float")

    def test_get_ytd_gain_returns_float(self):
        """Test get_ytd_gain returns float"""
        with patch.object(self.manager, 'get_account_summary') as mock_summary:
            mock_summary.return_value = {"RealizedPnL": "25000.00"}
            result = self.manager.get_ytd_gain()
            self.assertIsInstance(result, float)
            self.assertEqual(result, 25000.00)
            print("[OK] get_ytd_gain returns float")

    def test_get_all_time_gain_sums_pnl(self):
        """Test get_all_time_gain sums realized and unrealized P&L"""
        with patch.object(self.manager, 'get_account_summary') as mock_summary:
            mock_summary.return_value = {"RealizedPnL": "25000.00", "UnrealizedPnL": "5000.00"}
            result = self.manager.get_all_time_gain()
            self.assertIsInstance(result, float)
            self.assertEqual(result, 30000.00)
            print("[OK] get_all_time_gain sums realized and unrealized P&L")

    def test_get_all_time_gain_handles_zero_values(self):
        """Test get_all_time_gain handles zero values"""
        with patch.object(self.manager, 'get_account_summary') as mock_summary:
            mock_summary.return_value = {"RealizedPnL": "0", "UnrealizedPnL": "0"}
            result = self.manager.get_all_time_gain()
            self.assertEqual(result, 0.0)
            print("[OK] get_all_time_gain handles zero values")

    def test_get_cash_balance_exception_handling(self):
        """Test get_cash_balance handles exceptions gracefully"""
        with patch.object(self.manager, 'get_account_summary') as mock_summary:
            mock_summary.side_effect = Exception("Connection error")
            result = self.manager.get_cash_balance()
            self.assertIsNone(result)
            print("[OK] get_cash_balance handles exceptions")

    def test_get_all_time_gain_exception_handling(self):
        """Test get_all_time_gain handles exceptions gracefully"""
        with patch.object(self.manager, 'get_account_summary') as mock_summary:
            mock_summary.side_effect = Exception("Connection error")
            result = self.manager.get_all_time_gain()
            self.assertIsNone(result)
            print("[OK] get_all_time_gain handles exceptions")


def run_tests_in_random_order():
    """Run all tests in random order"""
    # Create test suite
    loader = unittest.TestLoader()
    suite = unittest.TestSuite()

    # Add all test classes
    test_classes = [
        TestImportsAndDependencies,
        TestConnectionValidation,
        TestIBKRManagerParameterValidation,
        TestTradeAlertsValidation,
        TestRiskManagerValidation,
        TestTypeConsistency,
        TestEdgeCases,
        TestCryptoSpecifics,
        TestAccountStatistics,
    ]

    for test_class in test_classes:
        tests = loader.loadTestsFromTestCase(test_class)
        suite.addTests(tests)

    # Convert to list and shuffle
    all_tests = list(suite)
    random.shuffle(all_tests)

    # Create new suite with shuffled tests
    shuffled_suite = unittest.TestSuite(all_tests)

    return shuffled_suite


if __name__ == "__main__":
    print("=" * 70)
    print("TRADING BOT - COMPREHENSIVE TEST SUITE")
    print("=" * 70)
    print("\nRunning comprehensive test suite...")
    print("Tests will run in RANDOM ORDER to ensure no hidden dependencies\n")

    # Run tests with randomized order
    suite = run_tests_in_random_order()
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)

    print("\n" + "=" * 70)
    print("TEST SUMMARY")
    print("=" * 70)
    print(f"Tests run: {result.testsRun}")
    print(f"Successes: {result.testsRun - len(result.failures) - len(result.errors)}")
    print(f"Failures: {len(result.failures)}")
    print(f"Errors: {len(result.errors)}")

    if result.wasSuccessful():
        print("\n[OK] ALL TESTS PASSED - REPO IS HEALTHY")
        print("[OK] Safe to commit code\n")
        sys.exit(0)
    else:
        print("\n[FAIL] SOME TESTS FAILED - DO NOT COMMIT")
        print("[FAIL] Fix failures before committing\n")
        sys.exit(1)
