import asyncio
from bleak import BleakScanner

async def main():
    for d in await BleakScanner.discover(timeout=10.0, adapter="hci2"):
        print(d.address, repr(d.name))

asyncio.run(main())
