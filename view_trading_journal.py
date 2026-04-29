#!/usr/bin/env python3
"""
Trading Journal Viewer and Exporter
Displays journal statistics and exports CSV for analysis
"""

import sys
import datetime
from pathlib import Path
from ibkr_trading_bot.trading_journal import TradingJournal

def main():
    journal_log = Path("logs/journal.log")
    journal = TradingJournal(str(journal_log))

    # Display current week statistics
    stats = journal.get_journal_stats(all_weeks=False)

    now = datetime.datetime.now()
    iso_year, iso_week, _ = now.isocalendar()

    print("\n" + "=" * 70)
    print(f"TRADING JOURNAL - WEEK {iso_week} ({iso_year})")
    print("=" * 70)
    print(f"Total Closed Trades:     {stats['total_trades']}")
    print(f"Winning Trades:          {stats['winning_trades']}")
    print(f"Losing Trades:           {stats['losing_trades']}")
    print(f"Win Rate:                {stats['win_rate']}%")
    print(f"Total P&L:               ${stats['total_pnl']:.2f}")
    print(f"Average P&L per Trade:   ${stats['avg_pnl']:.2f}")
    print("=" * 70)

    # All-time statistics
    all_time_stats = journal.get_journal_stats(all_weeks=True)
    if all_time_stats['total_trades'] > stats['total_trades']:
        print(f"\nALL-TIME STATISTICS (All Weeks)")
        print("-" * 70)
        print(f"Total Closed Trades:     {all_time_stats['total_trades']}")
        print(f"Winning Trades:          {all_time_stats['winning_trades']}")
        print(f"Losing Trades:           {all_time_stats['losing_trades']}")
        print(f"Win Rate:                {all_time_stats['win_rate']}%")
        print(f"Total P&L:               ${all_time_stats['total_pnl']:.2f}")
        print(f"Average P&L per Trade:   ${all_time_stats['avg_pnl']:.2f}")
        print("-" * 70)

    # Weekly CSV files
    weekly_files = journal.get_weekly_csv_files()
    print(f"\nWeekly CSV Files ({len(weekly_files)} total):")
    for csv_file in weekly_files[:5]:  # Show last 5 weeks
        print(f"  • {csv_file.name}")
    if len(weekly_files) > 5:
        print(f"  ... and {len(weekly_files) - 5} more")

    # Current week CSV location
    csv_path = journal.export_csv()
    print(f"\nCurrent Week CSV: {Path(csv_path).name}")
    print("Location: " + csv_path)
    print("\nColumns: timestamp_entry, timestamp_exit, ticker, order_type, qty,")
    print("         entry_price, exit_price, pnl, pnl_percent, duration_minutes,")
    print("         status, order_id_entry, order_id_exit, notes")
    print("\n✓ Each week gets its own CSV file for easy weekly review!")
    print("✓ You can import any CSV into Excel or your analysis tool!")

if __name__ == "__main__":
    main()
