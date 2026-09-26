#include <stddef.h>

#include <stdint.h>

#include <sys/types.h>

#include <zephyr/kernel.h>

#include <zephyr/sys/printk.h>

#include <zephyr/sys/util.h>

#include <zephyr/bluetooth/bluetooth.h>

#include <zephyr/bluetooth/conn.h>

#include <zephyr/bluetooth/gatt.h>

#include <zephyr/bluetooth/hci.h>

#include <zephyr/bluetooth/uuid.h>
#include "ble_power_svc.h"

#define LINK_TIMEOUT_MS 3000

static int8_t current_tx_power = 0;
static struct k_timer watchdog_timer;

#define BT_UUID_POWER_SERVICE_VAL BT_UUID_128_ENCODE(0x12345678, 0x1234, 0x5678, 0x1234, 0x56789abcdef0)
#define BT_UUID_POWER_CHAR_VAL    BT_UUID_128_ENCODE(0x12345678, 0x1234, 0x5678, 0x1234, 0x56789abcdef1)

static struct bt_uuid_128 power_service_uuid = BT_UUID_INIT_128(BT_UUID_POWER_SERVICE_VAL);
static struct bt_uuid_128 power_char_uuid = BT_UUID_INIT_128(BT_UUID_POWER_CHAR_VAL);

/* Watchdog fallback: reset power to MAX if host fails to check in */
static void watchdog_expiry_fn(struct k_timer *timer) {
    printk("[WATCHDOG] Link timeout! Forcing TX power to MAX (%d dBm)\n", MAX_TX_POWER);
    current_tx_power = MAX_TX_POWER;
}

/* GATT Callback when Host sends a new TX power command */
static ssize_t write_power_cmd(struct bt_conn *conn, const struct bt_gatt_attr *attr,
                               const void *buf, uint16_t len, uint16_t offset, uint8_t flags) {
    if (len < 1) return BT_GATT_ERR(BT_ATT_ERR_INVALID_ATTRIBUTE_LEN);
    
    int8_t new_power = ((int8_t *)buf)[0];
    if (new_power >= MIN_TX_POWER && new_power <= MAX_TX_POWER) {
        current_tx_power = new_power;
        printk("[GATT WRITE] PA Output Updated -> TX Power: %d dBm\n", current_tx_power);
        k_timer_start(&watchdog_timer, K_MSEC(LINK_TIMEOUT_MS), K_NO_WAIT);
    }
    return len;
}

BT_GATT_SERVICE_DEFINE(power_svc,
    BT_GATT_PRIMARY_SERVICE(&power_service_uuid),
    BT_GATT_CHARACTERISTIC(&power_char_uuid.uuid, 
                           BT_GATT_CHRC_NOTIFY | BT_GATT_CHRC_WRITE,
                           BT_GATT_PERM_WRITE, NULL, write_power_cmd, NULL),
    BT_GATT_CCC(NULL, BT_GATT_PERM_READ | BT_GATT_PERM_WRITE),
);

static const struct bt_data ad[] = {
    BT_DATA_BYTES(BT_DATA_FLAGS, (BT_LE_AD_GENERAL | BT_LE_AD_NO_BREDR)),
    BT_DATA(BT_DATA_NAME_COMPLETE, "EFR32_M33_QEMU", 14),
};

int ble_power_svc_init(void) {
    int err = bt_enable(NULL);
    if (err) {
        printk("Bluetooth init failed (err %d)\n", err);
        return err;
    }

    k_timer_init(&watchdog_timer, watchdog_expiry_fn, NULL);
    k_timer_start(&watchdog_timer, K_MSEC(LINK_TIMEOUT_MS), K_NO_WAIT);

    /* Construct advertising parameters explicitly for Zephyr 3.x/4.x */
    struct bt_le_adv_param adv_param = {
        .id = 0,
        .sid = 0,
        .options = (1 << 0) | (1 << 3), /* BIT(0)=Connectable, BIT(3)=Use Name */
        .interval_min = 0x0020,         /* 20 ms interval */
        .interval_max = 0x0040,         /* 40 ms interval */
        .peer = NULL,
    };
    err = bt_le_adv_start(&adv_param, ad, ARRAY_SIZE(ad), NULL, 0);
    if (err) {
        printk("Advertising failed to start (err %d)\n", err);
        return err;
    }

    printk("Zephyr Cortex-M33 QEMU Node Advertising...\n");
    return 0;
}

int ble_power_svc_notify_telemetry(uint16_t seq) {
    uint8_t payload[3] = { 
        (seq >> 8) & 0xFF, 
        seq & 0xFF, 
        (uint8_t)current_tx_power 
    };
    return bt_gatt_notify(NULL, &power_svc.attrs[1], payload, sizeof(payload));
}

int8_t ble_power_svc_get_tx_power(void) {
    return current_tx_power;
}
