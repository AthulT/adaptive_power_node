#include <zephyr/kernel.h>
#include <zephyr/sys/printk.h>
#include "ble_power_svc.h"

int main(void) {
    uint16_t packet_seq = 0;

    int err = ble_power_svc_init();
    if (err) {
        printk("Failed to initialize BLE Power Service (err %d)\n", err);
        return err;
    }

    while (1) {
        k_msleep(500);
        packet_seq++;
        
        ble_power_svc_notify_telemetry(packet_seq);
    }
    return 0;
}
