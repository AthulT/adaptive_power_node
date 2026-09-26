#ifndef BLE_POWER_SVC_H_
#define BLE_POWER_SVC_H_

#include <stdint.h>

#define MAX_TX_POWER 8
#define MIN_TX_POWER -26

/**
 * @brief Initialize the Bluetooth stack, GATT service, and watchdog timer.
 * @return 0 on success, negative error code on failure.
 */
int ble_power_svc_init(void);

/**
 * @brief Sends a BLE GATT notification containing sequence number and current TX power.
 * @param seq Packet sequence number.
 * @return 0 on success, negative error code on failure.
 */
int ble_power_svc_notify_telemetry(uint16_t seq);

/**
 * @brief Get the current configured TX power level.
 * @return Current TX power in dBm.
 */
int8_t ble_power_svc_get_tx_power(void);
void ble_power_svc_readvertise_if_idle(void);
#endif /* BLE_POWER_SVC_H_ */
