from ib_async import IB

ib = IB()
ib.connect('127.0.0.1', 4002, clientId=1001)

# Retrieve all current positions
positions = ib.positions()

for pos in positions:
    print(f"Symbol: {pos.contract.symbol}, Size: {pos.position}, Avg Cost: {pos.avgCost}")

ib.disconnect()
