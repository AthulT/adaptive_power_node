import asyncio

import bumble.logging
from bumble.controller import Controller
from bumble.core import AdvertisingData
from bumble.device import Device, Peer
from bumble.host import Host
from bumble.link import LocalLink
from bumble.transport.unix import open_unix_server_transport

TARGET_DEVICE_NAME = "EFR32_M33_QEMU"
POWER_SERVICE_UUID = "12345678-1234-5678-1234-56789abcdef0"
POWER_CHAR_UUID = "12345678-1234-5678-1234-56789abcdef1"
SOCKET_PATH = "/tmp/bt-server-bredr"


def notification_handler(data: bytearray):
    if len(data) >= 3:
        seq = (data[0] << 8) | data[1]
        tx_power = int.from_bytes([data[2]], byteorder="big", signed=True)
        print(f"[NOTIFICATION] Packet Seq: {seq} | Current TX Power: {tx_power} dBm")
    else:
        print(f"[NOTIFICATION] Raw payload: {data.hex()}")


async def main():
    print(f"[*] Listening on unix:{SOCKET_PATH} — start QEMU now")
    async with await open_unix_server_transport(SOCKET_PATH) as qemu_transport:
        link = LocalLink()

        # Controller A: bridges to Zephyr over the same unix socket QEMU already uses
        Controller(
            "A",
            host_source=qemu_transport.source,
            host_sink=qemu_transport.sink,
            link=link,
        )

        # Controller B: purely in-process, our central
        controller_b = Controller("B", link=link)
        host = Host()
        host.controller = controller_b
        device = Device(host=host)

        await device.power_on()
        await device.start_scanning()

        print(f"[*] Scanning for '{TARGET_DEVICE_NAME}'...")
        found = asyncio.get_event_loop().create_future()

        @device.on("advertisement")
        def on_adv(adv):
            names = adv.data.get_all(AdvertisingData.Type.COMPLETE_LOCAL_NAME)
            if TARGET_DEVICE_NAME in names and not found.done():
                found.set_result(adv.address)

        address = await asyncio.wait_for(found, timeout=30.0)
        await device.stop_scanning()

        print(f"[+] Found {address}, connecting...")
        connection = await device.connect(address)
        print("[+] Connected")

        peer = Peer(connection)
        peer_services = await peer.discover_services()
        service = next(s for s in peer_services if s.uuid == POWER_SERVICE_UUID)
        characteristics = await service.discover_characteristics()
        char = next(c for c in characteristics if c.uuid == POWER_CHAR_UUID)

        await char.subscribe(notification_handler)
        print("[+] Subscribed to telemetry")

        await char.write_value(bytes([0xFA]), with_response=True)
        print("[+] Sent GATT Write: -6 dBm")

        print("[*] Monitoring telemetry. Ctrl+C to exit.")
        await asyncio.get_running_loop().create_future()


if __name__ == "__main__":
    bumble.logging.setup_basic_logging("DEBUG")
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
