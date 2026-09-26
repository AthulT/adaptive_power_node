import asyncio, traceback
from bleak import BleakScanner, BleakClient

async def main():
	d = await BleakScanner.find_device_by_name("EFR32_M33_QEMU", timeout=30.0, adapter="hci2")
	print("found: ", d)
	if not d:
		return
	try:
		async with BleakClient(d, adapter="hci2", timeout=20.0) as c:
			print("connected: ", c.is_connected)
			for s in c.services:
				print("service: ", s.uuid)
				for ch in s.characteristics:
					print("char: ", ch.uuid, ch.properties)
	except Exception:
		traceback.print_exec()

asyncio.run(main())
