# Trading Journal - CSV Export System

## Overview
Your trading journal now automatically exports to **CSV format** for easy analysis in Excel, Google Sheets, or any data analysis tool. **A new CSV file is created every week** for easy weekly review and archival.

## Files
- **logs/journal.log** - Raw JSON log (internal use, for debugging)
- **logs/trading_journal_YYYY_WXX.csv** - Weekly CSV exports (one file per week, e.g., `trading_journal_2025_W18.csv`)

## CSV Columns

| Column | Description |
|--------|-------------|
| `trade_id` | Unique identifier for each trade |
| `timestamp_entry` | Date/time of order placement (ISO format) |
| `timestamp_exit` | Date/time of position close (ISO format) |
| `ticker` | Stock/crypto symbol |
| `order_type` | Type of order: `webalert` or `manual` |
| `quantity` | Number of shares/coins |
| `entry_price` | Price at which position was opened |
| `exit_price` | Price at which position was closed |
| `pnl` | Profit/Loss in dollars |
| `pnl_percent` | Return percentage (P&L as % of entry cost) |
| `duration_minutes` | How long position was held |
| `status` | Trade status: `OPEN` or `CLOSED` |
| `order_id_entry` | Order ID for entry |
| `order_id_exit` | Order ID for exit |
| `notes` | Any additional notes |

## Weekly Files & Archival

**Each Monday (start of ISO week)** a new CSV file is automatically created:
- `trading_journal_2025_W18.csv` (Week 18 of 2025)
- `trading_journal_2025_W17.csv` (Week 17 of 2025)
- etc.

All previous weeks are **preserved in the logs folder** for your manual archival. Archive old weeks whenever you want by moving them to a backup folder.

## Usage

### View Journal Statistics
```bash
python view_trading_journal.py
```

Output shows:
- **Current week** stats (closed trades, win rate, P&L)
- **All-time stats** (aggregate across all weeks)
- List of all weekly CSV files available

### Import CSV into Excel
1. Navigate to `logs/` folder
2. Open the week's CSV file directly (e.g., `trading_journal_2025_W18.csv`)
3. Or use Excel's **Data → From Text/CSV** menu
4. All columns are properly formatted for analysis

### Archive Old Weeks (Manual)
Simply move or copy older CSV files (e.g., `trading_journal_2025_W01.csv`) to a backup folder when ready.

### Create Dashboards
Example analysis you can do:
- **Profit by ticker**: GROUP BY ticker, SUM(pnl)
- **Win rate by order_type**: Filter by webalert vs manual
- **Performance by duration**: Analyze short vs long-hold trades
- **Monthly P&L**: Extract month from timestamp_entry, SUM(pnl)

## Auto-Logging

Trades are logged automatically when:
1. **BUY alert received** → `record_trade()` writes entry to CSV
2. **SELL alert received** → `record_close()` updates CSV with exit price and P&L

All timing and pricing is captured automatically.

## Weekly Files Example

Your `logs/` folder structure after trading for a few weeks:
```
logs/
├── journal.log                          (raw JSON log)
├── trading_journal_2025_W18.csv         (current week - in use)
├── trading_journal_2025_W17.csv         (archived manually)
├── trading_journal_2025_W16.csv         (archived manually)
└── trading_journal_2025_W15.csv         (archived manually)
```

File naming convention: `trading_journal_YYYY_WXX.csv`
- YYYY = Year (e.g., 2025)
- XX = ISO week number (01-53)
- Week starts Monday (ISO standard)

## Example CSV Row

```
trade_id,timestamp_entry,timestamp_exit,ticker,order_type,quantity,entry_price,exit_price,pnl,pnl_percent,duration_minutes,status,order_id_entry,order_id_exit,notes
NVDA_12345_20250428142530,2025-04-28T14:25:30.123456,2025-04-28T15:42:15.654321,NVDA,webalert,100,125.50,128.75,325.0,2.59,76,CLOSED,12345,12346,
```

## Metrics You Can Track

### Using the CSV:
- **Win Rate**: Count(pnl > 0) / Count(all closed trades)
- **Avg Winner**: Average(pnl where pnl > 0)
- **Avg Loser**: Average(pnl where pnl < 0)
- **Profit Factor**: Sum(pnl where pnl > 0) / Abs(Sum(pnl where pnl < 0))
- **Risk/Reward Ratio**: Avg(winner) / Abs(Avg(loser))

### Programmatically:
```python
from ibkr_trading_bot.trading_journal import TradingJournal

journal = TradingJournal("logs/journal.log")
stats = journal.get_journal_stats()

print(f"Win Rate: {stats['win_rate']}%")
print(f"Total P&L: ${stats['total_pnl']}")
print(f"Avg P&L: ${stats['avg_pnl']}")
```

## Notes
- Times are stored in ISO format (UTC) for consistency
- All prices are stored as floats with full precision
- P&L is calculated automatically when exit price is known
- Both entry and exit order IDs are tracked for audit trail
