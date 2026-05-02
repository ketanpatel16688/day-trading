from ib_async import *

def get_settled_cash():
    ib = IB()
    try:
        # Use ib.connect() directly. 
        # In Python 3.14, this is safer as it manages the internal event loop/tasks for you.
        print("Connecting to IB Gateway...")
        ib.connect('127.0.0.1', 7497, clientId=1001)
        print("Connected!")

        # Fetch all account values (the "Account" tab in TWS)
        # For settled cash, we look at the 'SettledCash' tag
        print("Fetching account values...")
        acc_values = ib.accountValues()
        
        found = False
        for v in acc_values:
            # We filter for SettledCash and USD (or your specific currency)
            if v.tag == 'SettledCash' and v.currency == 'USD':
                print(f"Settled Cash (USD): {v.value}")
                found = True
        
        if not found:
            # Fallback: some accounts use 'AvailableFunds' for immediate trading cash
            for v in acc_values:
                if v.tag == 'AvailableFunds' and v.currency == 'USD':
                    print(f"Available Funds (USD): {v.value}")

    except Exception as e:
        print(f"Error occurred: {e}")
    finally:
        ib.disconnect()
        print("Disconnected.")

if __name__ == '__main__':
    get_settled_cash()
