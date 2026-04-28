from ib_insync import *
import pandas as pd
from datetime import datetime
import math

# -------------------------------
# CONFIG
# -------------------------------
TICKERS = ["NVDA", "SPY"]
MIN_DTE = 90
DELTA_RANGE = (0.65, 0.80)

HOST = "127.0.0.1"
PORT = 7496   # paper trading
CLIENT_ID = 1

# -------------------------------
# CONNECT
# -------------------------------
ib = IB()
ib.connect(HOST, PORT, clientId=CLIENT_ID)

# -------------------------------
# SUPPORT (simple proxy: 1M low)
# -------------------------------
def get_support_level(contract):
    bars = ib.reqHistoricalData(
        contract,
        endDateTime='',
        durationStr='1 M',
        barSizeSetting='1 day',
        whatToShow='TRADES',
        useRTH=True
    )
    df = util.df(bars)
    return df['low'].min()

# -------------------------------
# ATR CALCULATION
# -------------------------------
def get_atr(contract, period=14):
    bars = ib.reqHistoricalData(
        contract,
        endDateTime='',
        durationStr='2 M',
        barSizeSetting='1 day',
        whatToShow='TRADES',
        useRTH=True
    )
    df = util.df(bars)

    # True Range
    df['prev_close'] = df['close'].shift(1)
    df['tr'] = df[['high', 'prev_close']].max(axis=1) - df[['low', 'prev_close']].min(axis=1)

    df['atr'] = df['tr'].rolling(period).mean()

    return df['atr'].iloc[-1]

# -------------------------------
# OPTION DATA FETCH
# -------------------------------
def get_option_data(symbol):
    print(f"\nFetching data for {symbol}...")

    stock = Stock(symbol, 'SMART', 'USD')
    ib.qualifyContracts(stock)

    # Spot price
    ticker = ib.reqMktData(stock, "", False, False)
    ib.sleep(2)
    spot = ticker.marketPrice()

    # Support + ATR
    support = get_support_level(stock)
    atr = get_atr(stock)

    # Expected move (approx 1 month horizon)
    expected_move = atr * math.sqrt(30)

    print(f"{symbol} Spot: {spot}, Support: {support}, ATR: {atr:.2f}")

    # Option chain
    chains = ib.reqSecDefOptParams(
        stock.symbol, "", stock.secType, stock.conId
    )
    chain = chains[0]

    expirations = sorted(chain.expirations)

    # Filter LEAPS (>= MIN_DTE)
    valid_expiries = []
    for exp in expirations:
        dte = (datetime.strptime(exp, "%Y%m%d") - datetime.today()).days
        if dte >= MIN_DTE:
            valid_expiries.append((exp, dte))

    # Only ITM strikes (calls)
    strikes = [s for s in chain.strikes if s < spot]

    contracts = []
    for exp, dte in valid_expiries[:3]:  # limit for speed
        for strike in strikes:
            contracts.append(
                Option(symbol, exp, strike, 'C', 'SMART')
            )

    contracts = ib.qualifyContracts(*contracts)

    # Request market data (Greeks)
    tickers = ib.reqMktData(contracts, "", False, False)
    ib.sleep(5)

    rows = []
    for t in tickers:
        if t.modelGreeks:
            dte = (datetime.strptime(
                t.contract.lastTradeDateOrContractMonth, "%Y%m%d"
            ) - datetime.today()).days

            rows.append({
                "symbol": symbol,
                "expiry": t.contract.lastTradeDateOrContractMonth,
                "dte": dte,
                "strike": t.contract.strike,
                "price": t.marketPrice(),
                "delta": t.modelGreeks.delta,
                "theta": t.modelGreeks.theta,
                "vega": t.modelGreeks.vega,
                "iv": t.modelGreeks.impliedVol,
                "spot": spot,
                "support": support,
                "atr": atr,
                "exp_move": expected_move
            })

    df = pd.DataFrame(rows)
    return df

# -------------------------------
# LEAPS SELECTION (ATR + DELTA)
# -------------------------------
def select_leaps(df):
    # Delta filter
    df = df[
        (df["delta"] >= DELTA_RANGE[0]) &
        (df["delta"] <= DELTA_RANGE[1])
    ]

    # ITM only
    df = df[df["strike"] < df["spot"]]

    # ATR-based distance
    df["atr_distance"] = (df["spot"] - df["strike"]) / df["atr"]

    # Keep strikes within 0.5–1.5 ATR
    df = df[
        (df["atr_distance"] >= 0.5) &
        (df["atr_distance"] <= 1.5)
    ]

    # Distance from support
    df["dist_from_support"] = (df["spot"] - df["support"]) / df["spot"]

    # Scoring
    df["score"] = (
        df["delta"] * 0.4
        - df["iv"] * 0.25
        - df["dist_from_support"] * 0.2
        - abs(df["atr_distance"] - 1.0) * 0.15
    )

    return df.sort_values("score", ascending=False)

# -------------------------------
# RUN
# -------------------------------
for ticker in TICKERS:
    df = get_option_data(ticker)

    if df.empty:
        print(f"No data for {ticker}")
        continue

    best = select_leaps(df)

    print(f"\n=== BEST LEAPS for {ticker} ===")
    print(best.head(5)[[
        "expiry", "dte", "strike", "price",
        "delta", "iv", "atr_distance", "score"
    ]])

# -------------------------------
# DISCONNECT
# -------------------------------
ib.disconnect()