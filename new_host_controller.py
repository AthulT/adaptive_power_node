import asyncio
import time

import bumble.logging
import logging
from bumble.controller import Controller
from bumble.core import AdvertisingData
from bumble.device import Device, Peer
from bumble.host import Host
from bumble.link import LocalLink
from bumble.transport.unix import open_unix_server_transport

# ---------------------------------------------------------------------------
# Connection config
# ---------------------------------------------------------------------------
TARGET_DEVICE_NAME = "EFR32_M33_QEMU"
POWER_SERVICE_UUID = "12345678-1234-5678-1234-56789abcdef0"
POWER_CHAR_UUID = "12345678-1234-5678-1234-56789abcdef1"
SOCKET_PATH = "/tmp/bt-server-bredr"

# ---------------------------------------------------------------------------
# Control-loop config
# Source of truth for the power bounds is src/ble_power_svc.h — keep in sync.
# ---------------------------------------------------------------------------
MIN_TX_POWER = -26          # ble_power_svc.h
MAX_TX_POWER = 8            # ble_power_svc.h
LINK_TIMEOUT_S = 3.0        # firmware LINK_TIMEOUT_MS

DEMO_DURATION_S = 35.0
TICK_S = 1.0
HYSTERESIS_DB = 2           # ignore target changes smaller than this
MIN_DWELL_S = 2.0           # minimum time between power changes
IDLE_WINDOW = (18.0, 22.5)  # deliberately > LINK_TIMEOUT_S wide

# RSSI calibration points for the synthetic link
RSSI_STRONG = -45.0
RSSI_WEAK = -95.0

# ---------------------------------------------------------------------------
# Shared state
# ---------------------------------------------------------------------------
log = []
START_TIME = None


def now() -> float:
    return time.monotonic() - START_TIME


def synthetic_rssi(t: float) -> float:
    """Triangular sweep: strong -> weak -> strong across the demo duration.

    Bumble's virtual controller hardcodes RSSI to -50 with no path-loss model,
    so link strength has to be scripted here rather than measured.
    """
    half = DEMO_DURATION_S / 2.0
    frac = (t / half) if t <= half else ((DEMO_DURATION_S - t) / half)
    frac = max(0.0, min(1.0, frac))
    return RSSI_STRONG + frac * (RSSI_WEAK - RSSI_STRONG)


class MedianFilter:
    """Median of the last n samples — mirrors sl_bt_connection_get_median_rssi()."""

    def __init__(self, n: int = 7):
        self.n = n
        self.buf = []

    def push(self, value: float) -> float:
        self.buf.append(value)
        if len(self.buf) > self.n:
            self.buf.pop(0)
        ordered = sorted(self.buf)
        mid = len(ordered) // 2
        if len(ordered) % 2:
            return ordered[mid]
        return (ordered[mid - 1] + ordered[mid]) / 2.0


def rssi_to_tx_power(rssi_dbm: float) -> int:
    """Weak link -> more power, strong link -> less power. Clamped to firmware bounds."""
    frac = (rssi_dbm - RSSI_STRONG) / (RSSI_WEAK - RSSI_STRONG)
    frac = max(0.0, min(1.0, frac))
    power = MIN_TX_POWER + frac * (MAX_TX_POWER - MIN_TX_POWER)
    return int(round(max(MIN_TX_POWER, min(MAX_TX_POWER, power))))


def notification_handler(data: bytearray):
    """Ground truth: what the firmware says its power actually is."""
    if len(data) >= 3:
        seq = (data[0] << 8) | data[1]
        tx_power = int.from_bytes([data[2]], byteorder="big", signed=True)
        t = now()
        print(f"[{t:5.1f}s] [TELEMETRY] seq={seq:<4d} firmware TX power = {tx_power:+d} dBm")
        log.append({"t": t, "source": "telemetry", "reported_power": tx_power})
    else:
        print(f"[TELEMETRY] Raw payload: {data.hex()}")


async def control_loop(char):
    median = MedianFilter(n=7)
    last_applied = None
    last_change_t = 0.0

    while True:
        t = now()
        if t >= DEMO_DURATION_S:
            break

        in_idle_window = IDLE_WINDOW[0] <= t <= IDLE_WINDOW[1]
        raw = synthetic_rssi(t)
        filtered = median.push(raw)
        target = rssi_to_tx_power(filtered)

        if not in_idle_window:
            should_write = last_applied is None or (
                abs(target - last_applied) >= HYSTERESIS_DB
                and t - last_change_t >= MIN_DWELL_S
            )
            if should_write:
                await char.write_value(
                    target.to_bytes(1, "little", signed=True), with_response=True
                )
                print(
                    f"[{t:5.1f}s] [CONTROL]   RSSI {filtered:6.1f} dBm "
                    f"-> write TX power {target:+d} dBm"
                )
                last_applied = target
                last_change_t = t
        elif last_applied is not None:
            print(f"[{t:5.1f}s] [CONTROL]   (idle window — withholding writes)")
            last_applied = None  # force a fresh write once the window ends

        log.append(
            {
                "t": t,
                "source": "control",
                "raw_rssi": raw,
                "filtered_rssi": filtered,
                "requested_power": None if in_idle_window else target,
                "phase": "idle_timeout" if in_idle_window else "adaptive",
            }
        )
        await asyncio.sleep(TICK_S)


def plot_results():
    import matplotlib.pyplot as plt

    control_pts = [e for e in log if e["source"] == "control"]
    telemetry_pts = [e for e in log if e["source"] == "telemetry"]

    if not control_pts or not telemetry_pts:
        print("[!] Not enough data collected, skipping plot.")
        return

    t_ctrl = [e["t"] for e in control_pts]
    raw_rssi = [e["raw_rssi"] for e in control_pts]
    filt_rssi = [e["filtered_rssi"] for e in control_pts]
    requested = [
        e["requested_power"] if e["requested_power"] is not None else float("nan")
        for e in control_pts
    ]

    t_tel = [e["t"] for e in telemetry_pts]
    reported = [e["reported_power"] for e in telemetry_pts]

    below_max = sum(1 for p in reported if p < MAX_TX_POWER)
    pct_below_max = 100.0 * below_max / len(reported)

    fig, (ax1, ax2) = plt.subplots(2, 1, sharex=True, figsize=(10, 7))

    ax1.plot(t_ctrl, raw_rssi, color="lightgray", linewidth=1, label="raw synthetic RSSI")
    ax1.plot(t_ctrl, filt_rssi, color="tab:blue", linewidth=2,
             label="filtered RSSI (7-sample median)")
    ax1.set_ylabel("RSSI (dBm)")
    ax1.legend(loc="lower right", fontsize=8)
    ax1.set_title("Adaptive TX Power — Zephyr BLE peripheral under QEMU")
    ax1.grid(alpha=0.3)

    ax2.step(t_ctrl, requested, where="post", color="tab:orange", linewidth=2,
             label="requested TX power (host algorithm)")
    ax2.plot(t_tel, reported, "o-", color="tab:green", markersize=3, linewidth=1,
             label="applied TX power (firmware telemetry)")
    ax2.axhline(MAX_TX_POWER, color="red", linestyle=":", linewidth=1,
                label=f"MAX_TX_POWER ({MAX_TX_POWER:+d} dBm fail-safe)")
    ax2.set_ylabel("TX Power (dBm)")
    ax2.set_xlabel("Time (s)")
    ax2.legend(loc="lower right", fontsize=8)
    ax2.grid(alpha=0.3)

    for ax in (ax1, ax2):
        ax.axvspan(IDLE_WINDOW[0], IDLE_WINDOW[1], color="red", alpha=0.12)
    ax2.annotate(
        "host stops writing\n-> watchdog forces MAX",
        xy=(sum(IDLE_WINDOW) / 2, MAX_TX_POWER),
        xytext=(sum(IDLE_WINDOW) / 2, MAX_TX_POWER - 14),
        ha="center", fontsize=8, color="red",
        arrowprops=dict(arrowstyle="->", color="red", lw=1),
    )

    fig.text(0.5, 0.01,
             f"{pct_below_max:.0f}% of demo spent below max TX power",
             ha="center", fontsize=10, style="italic")
    fig.tight_layout(rect=[0, 0.03, 1, 1])
    fig.savefig("demo_plot.png", dpi=150)
    print("[+] Saved plot to demo_plot.png")
    plt.show()


async def main():
    global START_TIME

    print(f"[*] Listening on unix:{SOCKET_PATH} — start QEMU now")
    async with await open_unix_server_transport(SOCKET_PATH) as qemu_transport:
        link = LocalLink()

        # Controller A: bridges to Zephyr over the unix socket QEMU connects to
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
        print("[+] Subscribed to telemetry\n")

        START_TIME = time.monotonic()
        print(
            f"[*] Running {DEMO_DURATION_S:.0f}s adaptive control loop "
            f"(idle-timeout window at {IDLE_WINDOW[0]:.0f}-{IDLE_WINDOW[1]:.1f}s)\n"
        )
        await control_loop(char)

        print("\n[*] Control loop complete, disconnecting...")
        await connection.disconnect()

    plot_results()


if __name__ == "__main__":
    bumble.logging.setup_basic_logging("WARNING")
    logging.getLogger("bumble.controller").setLevel(logging.CRITICAL)
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
