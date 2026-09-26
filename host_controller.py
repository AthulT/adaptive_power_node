import asyncio
import sys
import os
from bleak import BleakScanner, BleakClient
from bleak.exc import BleakError, BleakDBusError

# ==============================================================================
# CONFIGURATION
# ==============================================================================
TARGET_DEVICE_NAME = "EFR32_M33_QEMU"

POWER_SERVICE_UUID = "12345678-1234-5678-1234-56789abcdef0"
POWER_CHAR_UUID    = "12345678-1234-5678-1234-56789abcdef1"

SCAN_TIMEOUT_SEC = 10.0


# ==============================================================================
# ADAPTER PROMPT SELECTION
# ==============================================================================
def select_hci_adapter() -> str:
    """Prompts the user to select or input an HCI adapter interactively."""
    # Read available HCI interfaces if running on Linux
    available_adapters = []
    try:
        if os.path.exists("/sys/class/bluetooth"):
            available_adapters = sorted(os.listdir("/sys/class/bluetooth"))
    except Exception:
        pass

    print("=" * 60)
    print("        BLE HOST CONTROLLER - ADAPTER SELECTION        ")
    print("=" * 60)

    if available_adapters:
        print("Detected Bluetooth Adapters on System:")
        for idx, adapter in enumerate(available_adapters, start=1):
            print(f"  [{idx}] {adapter}")
        print("  [0] Enter custom interface manually")
        print("-" * 60)

        while True:
            choice = input(f"Select adapter (1-{len(available_adapters)}, or 0) [Default: 1]: ").strip()
            
            # Handle default selection
            if choice == "":
                return available_adapters[0]
            
            if choice.isdigit():
                val = int(choice)
                if 1 <= val <= len(available_adapters):
                    return available_adapters[val - 1]
                elif val == 0:
                    break
            
            print("Invalid choice. Please try again.")

    # Manual input fallback or explicit choice
    manual_adapter = input("Enter HCI adapter name (e.g., hci0, hci1, hci2) [Default: hci0]: ").strip()
    return manual_adapter if manual_adapter else "hci0"


# ==============================================================================
# TELEMETRY & GATT HANDLERS
# ==============================================================================
def notification_handler(sender, data: bytearray):
    """Callback for telemetry notifications sent by the Zephyr target."""
    if len(data) >= 3:
        seq = (data[0] << 8) | data[1]
        tx_power = int.from_bytes([data[2]], byteorder='big', signed=True)
        print(f"[NOTIFICATION] Packet Seq: {seq} | Current TX Power: {tx_power} dBm")
    else:
        print(f"[NOTIFICATION] Raw payload: {data.hex()}")


# ==============================================================================
# MAIN ASYNC LOOP
# ==============================================================================
async def main(adapter: str):
    print(f"\n[*] Starting BLE Host Controller on adapter '{adapter}'...")
    print(f"[*] Searching for target device: '{TARGET_DEVICE_NAME}'")

    # 1. Device Discovery Phase
    device = None
    try:
        #scanner = BleakScanner(adapter=adapter)
        device = await BleakScanner.find_device_by_name(TARGET_DEVICE_NAME, timeout=SCAN_TIMEOUT_SEC, adapter=adapter)
    
    except BleakDBusError as e:
        if "org.bluez.Error.InProgress" in str(e):
            print(f"\n[!] Error: A scan operation is already in progress on '{adapter}'.")
            print(f"    Fix: Run 'sudo hciconfig {adapter} down && sudo hciconfig {adapter} up'")
        elif "org.bluez.Error.NotReady" in str(e):
            print(f"\n[!] Error: Adapter '{adapter}' is powered off or not ready.")
            print(f"    Fix: Run 'sudo hciconfig {adapter} up' or 'sudo rfkill unblock bluetooth'")
        else:
            print(f"\n[!] D-Bus Error during scan: {e}")
        return

    except BleakError as e:
        print(f"\n[!] Bleak Driver Error on adapter '{adapter}': {e}")
        return

    except Exception as e:
        print(f"\n[!] Unexpected Error during scan: {e}")
        return

    if not device:
        print(f"\n[-] Device '{TARGET_DEVICE_NAME}' not found within {SCAN_TIMEOUT_SEC} seconds.")
        print(f"    Ensure QEMU is running, HCI link is UP, and device is advertising on {adapter}.")
        return

    print(f"[+] Found device: {device.name} [{device.address}]")

    # 2. Connection Phase
    print(f"[*] Connecting to {device.address}...")
    try:
        async with BleakClient(device, adapter=adapter, timeout=15.0) as client:
            if not client.is_connected:
                print("[-] Failed to establish GATT connection.")
                return

            print(f"[+] Connected successfully to {device.name}!")

            # Start notifications on telemetry characteristic
            await client.start_notify(POWER_CHAR_UUID, notification_handler)
            print(f"[+] Subscribed to telemetry notifications ({POWER_CHAR_UUID})")

            # Example: Send dynamic TX power command (Write -6 dBm to target)
            new_tx_power_command = bytes([0xFA])  # -6 in int8_t (0xFA)
            await client.write_gatt_char(POWER_CHAR_UUID, new_tx_power_command, response=True)
            print("[+] Sent GATT Write Command: Adjust TX Power -> -6 dBm")

            print("\n[*] Host Controller active. Monitoring telemetry... Press Ctrl+C to exit cleanly.\n")
            
            # Keep link open for telemetry reception
            while client.is_connected:
                await asyncio.sleep(1)

    except BleakDBusError as e:
        print(f"\n[!] Connection lost or D-Bus error: {e}")
    except BleakError as e:
        print(f"\n[!] GATT Connection error: {e}")
    except asyncio.CancelledError:
        print("\n[*] Task cancelled. Disconnecting cleanly...")
    except Exception as e:
        print(f"\n[!] Unexpected connection error: {e}")
    finally:
        print("[*] Cleanup complete. Exiting controller session.")


# ==============================================================================
# ENTRY POINT
# ==============================================================================
if __name__ == "__main__":
    # Command-line argument override: `python3 host_controller.py hci0`
    if len(sys.argv) > 1:
        selected_adapter = sys.argv[1]
    else:
        selected_adapter = select_hci_adapter()

    try:
        asyncio.run(main(selected_adapter))
    except KeyboardInterrupt:
        print("\n[*] Interrupted by user (Ctrl+C). Exiting cleanly.")
        sys.exit(0)
