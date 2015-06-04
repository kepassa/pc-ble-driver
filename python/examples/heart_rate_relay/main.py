# Copyright (c) 2015 Nordic Semiconductor. All Rights Reserved.
#
# The information contained herein is property of Nordic Semiconductor ASA.
# Terms and conditions of usage are described in detail in NORDIC
# SEMICONDUCTOR STANDARD SOFTWARE LICENSE AGREEMENT.
# Licensees are granted free, non-transferable use of the information. NO
# WARRANTY of ANY KIND is provided. This heading must NOT be removed from
# the file.

"""
Example on use of s130_nrf51_ble_driver python binding library.

The example demonstrates how one can use the library to set up concurrent central and peripheral
operation. The example is a combination of a heart rate collector and a heart rate monitor.
The local central will connect to a peer heart rate monitor peripheral, and the local peripheral
will relay the data to a peer central.
"""

# Add location of binding library to path
import sys
sys.path.append("../..")

import platform
import traceback
import ctypes

SERIAL_PORT = ""

if platform.system() == "Windows":
    # Load the DLL into memory (instead of copying to current directory)
    ctypes.cdll.LoadLibrary('../../../driver/lib/s130_nrf51_ble_driver')

    SERIAL_PORT = "COM1"

if platform.system() == "Darwin":
    SERIAL_PORT = "/dev/tty.usbmodem00000"

if platform.system() == "Linux":
    # Load the DLL into memory (instead of copying to current directory)
    ctypes.cdll.LoadLibrary('../../../driver/lib/libs130_nrf51_ble_driver.so')

    SERIAL_PORT = "/dev/ttyACM0"

# Import the binding library
import s130_nrf51_ble_driver as ble_driver
import ble_driver_util as util

TARGET_DEV_NAME = "HRM Example"
MAX_PEER_COUNT = 1
BLE_UUID_HEART_RATE_SERVICE = 0x180D
BLE_UUID_HEART_RATE_MEASUREMENT_CHAR = 0x2A37
CCCD_UUID = 0x2902
CCCD_NOTIFY = 0x01
BLE_ADDRESS_LENGTH = 6
MAX_HRM_LEN = ble_driver.BLE_L2CAP_MTU_DEF - 1 - 2

connection_params = None
scan_params = None
connected_devices = 0
connection_handle = 0
service_start_handle = 0
service_end_handle = 0
hrm_char_handle = 0
hrm_cccd_handle = 0
peripheral_connection_handle = ble_driver.BLE_CONN_HANDLE_INVALID
central_connection_handle = ble_driver.BLE_CONN_HANDLE_INVALID
connection_is_in_progress = False
send_notifications = False
heart_rate_service_handle = 0
heart_rate_measurement_handle = ble_driver.ble_gatts_char_handles_t()


def log_message_handler(severity, log_message):
    try:
        print "Log: {}".format(log_message)
    except Exception, ex:
        print "Exception: {}".format(str(ex))


def ble_evt_handler(ble_event):
    try:
        if ble_event is None:
            print "Received empty ble_event"
            return

        evt_id = ble_event.header.evt_id

        if evt_id == ble_driver.BLE_GAP_EVT_CONNECTED:
            on_connected(ble_event.evt.gap_evt)

        elif evt_id == ble_driver.BLE_GAP_EVT_DISCONNECTED:
            on_disconnected(ble_event.evt.gap_evt)

        elif evt_id == ble_driver.BLE_GAP_EVT_ADV_REPORT:
            on_adv_report(ble_event.evt.gap_evt)

        elif evt_id == ble_driver.BLE_GAP_EVT_TIMEOUT:
            on_timeout(ble_event.evt.gap_evt)

        elif evt_id == ble_driver.BLE_GAP_EVT_SEC_PARAMS_REQUEST:
            on_sec_params_request(ble_event.evt.gap_evt)

        elif evt_id == ble_driver.BLE_GATTC_EVT_PRIM_SRVC_DISC_RSP:
            on_service_discovery_response(ble_event.evt.gattc_evt)

        elif evt_id == ble_driver.BLE_GATTC_EVT_CHAR_DISC_RSP:
            on_characteristic_discovery_response(ble_event.evt.gattc_evt)

        elif evt_id == ble_driver.BLE_GATTC_EVT_DESC_DISC_RSP:
            on_descriptor_discovery_response(ble_event.evt.gattc_evt)

        elif evt_id == ble_driver.BLE_GATTC_EVT_WRITE_RSP:
            on_write_response(ble_event.evt.gattc_evt)

        elif evt_id == ble_driver.BLE_GATTC_EVT_HVX:
            on_hvx(ble_event.evt.gattc_evt)

        elif evt_id == ble_driver.BLE_GATTS_EVT_SYS_ATTR_MISSING:
            on_sys_attr_missing(ble_event.evt.gatts_evt)

        elif evt_id == ble_driver.BLE_GATTS_EVT_WRITE:
            on_write(ble_event.evt.gatts_evt)

        elif evt_id == ble_driver.BLE_EVT_TX_COMPLETE:
            pass

        else:
            print "Unhandled event with ID: {}".format(evt_id)
    except Exception, ex:
        print "Exception: {}".format(str(ex))
        print traceback.extract_tb(sys.exc_info()[2])


def on_connected(gap_event):
    global connection_is_in_progress
    global peripheral_connection_handle
    global central_connection_handle

    connected_event = gap_event.params.connected

    if connected_event.role == ble_driver.BLE_GAP_ROLE_PERIPH:
        print "Connection to a central device established"
        connection_is_in_progress = False
        peripheral_connection_handle = gap_event.conn_handle
    elif connected_event.role == ble_driver.BLE_GAP_ROLE_CENTRAL:
        print "Connection to a peripheral device established"
        central_connection_handle = gap_event.conn_handle
        start_service_discovery()
        start_advertising()


def on_disconnected(gap_event):
    global peripheral_connection_handle
    global central_connection_handle

    if peripheral_connection_handle == gap_event.conn_handle:
        print "Disconnected from a central, reason: 0x{0:02X}".format(
            gap_event.params.disconnected.reason)
        peripheral_connection_handle = ble_driver.BLE_CONN_HANDLE_INVALID
        # If we have a connection to a periperhal device we start to advertise again
        if central_connection_handle != ble_driver.BLE_CONN_HANDLE_INVALID:
            start_advertising()
    elif central_connection_handle == gap_event.conn_handle:
        print "Disconnected from a peripheral, reason: 0x{0:02X}".format(
            gap_event.params.disconnected.reason)
        # If we have a connection to a central device we disconnect from it since we have no
        # peripheral that gives us values to propagate
        if peripheral_connection_handle == ble_driver.BLE_CONN_HANDLE_INVALID:
            ble_driver.sd_ble_gap_disconnect(peripheral_connection_handle,
                                             ble_driver.BLE_HCI_REMOTE_USER_TERMINATED_CONNECTION)
        start_scan()


def on_adv_report(gap_event):
    global connection_is_in_progress

    address_pointer = gap_event.params.adv_report.peer_addr.addr
    address_list = util.uint8_array_to_list(address_pointer, BLE_ADDRESS_LENGTH)
    address_string = "".join("{0:02X}".format(byte) for byte in address_list)

    adv_data_pointer = gap_event.params.adv_report.data
    adv_data_length = gap_event.params.adv_report.dlen
    adv_data_list = util.uint8_array_to_list(adv_data_pointer, adv_data_length)

    parsed_data = parse_adv_report(ble_driver.BLE_GAP_AD_TYPE_COMPLETE_LOCAL_NAME,
                                   adv_data_list)

    if not parsed_data:
        parsed_data = parse_adv_report(ble_driver.BLE_GAP_AD_TYPE_SHORT_LOCAL_NAME,
                                       adv_data_list)

    if not parsed_data:
        return

    peer_device_name = "".join(chr(element) for element in parsed_data)

    print "Received advertisment report, address: 0x{}, device_name: {}".format(
        address_string, peer_device_name)

    if peer_device_name != TARGET_DEV_NAME:
        return

    if central_connection_handle != ble_driver.BLE_CONN_HANDLE_INVALID:
        return

    if connection_is_in_progress:
        return

    err_code = ble_driver.sd_ble_gap_connect(gap_event.params.adv_report.peer_addr,
                                             scan_params,
                                             connection_params)

    if err_code != ble_driver.NRF_SUCCESS:
        print "Connection request failed, reason {}".format(err_code)
        return

    connection_is_in_progress = True


def on_timeout(gap_event):
    global connection_is_in_progress

    source = gap_event.params.timeout.src
    if source == ble_driver.BLE_GAP_TIMEOUT_SRC_CONN:
        connection_is_in_progress = False
        start_scan()
    elif gap_event.params.timeout.src == ble_driver.BLE_GAP_TIMEOUT_SRC_ADVERTISING:
        start_advertising()
    elif source == ble_driver.BLE_GAP_TIMEOUT_SRC_SCAN:
        start_scan()


def on_sec_params_request(gap_event):
    ble_driver.sd_ble_gap_sec_params_reply(peripheral_connection_handle,
                                           ble_driver.BLE_GAP_SEC_STATUS_SUCCESS, None, None)


def parse_adv_report(adv_type, adv_data):
    length = len(adv_data)
    index = 0

    while index < length:
        field_length = adv_data[index]
        field_type = adv_data[index + 1]

        if field_type == adv_type:
            offset = index + 2
            parsed_data = adv_data[offset: offset + field_length - 1]
            return parsed_data

        index += (field_length + 1)

    return None


def on_service_discovery_response(gattc_event):
    global service_start_handle
    global service_end_handle

    if gattc_event.gatt_status != ble_driver.NRF_SUCCESS:
        print "Error. Service discovery failed. Error code 0x{0:X}".format(gattc_event.gatt_status)
        return

    count = gattc_event.params.prim_srvc_disc_rsp.count

    if count == 0:
        print "Error. Service not found"
        return

    print "Received service discovery response"

    service_list = util.service_array_to_list(gattc_event.params.prim_srvc_disc_rsp.services, count)
    service_index = 0  # We requested to discover Heart Rate service only, so selecting first result
    service = service_list[service_index]

    service_start_handle = service.handle_range.start_handle
    service_end_handle = service.handle_range.end_handle

    print "UUID: 0x{0:04X}, start handle: 0x{1:04X}, end handle: 0x{2:04X}".format(
        service.uuid.uuid, service_start_handle, service_end_handle)

    start_characteristic_discovery()


def on_characteristic_discovery_response(gattc_event):
    global hrm_char_handle

    if gattc_event.gatt_status != ble_driver.NRF_SUCCESS:
        print "Error. Characteristic discovery failed. Error code 0x{0:X}".format(
            gattc_event.gatt_status)
        return

    count = gattc_event.params.char_disc_rsp.count

    print "Received characteristic discovery response, characteristics count: {}".format(count)

    char_list = util.char_array_to_list(gattc_event.params.char_disc_rsp.chars, count)

    for i in range(0, count):
        characteristic = char_list[i]

        print "Handle: 0x{0:04X}, UUID: 0x{1:04X}".format(characteristic.handle_decl,
                                                          characteristic.uuid.uuid)

        if characteristic.uuid.uuid == BLE_UUID_HEART_RATE_MEASUREMENT_CHAR:
            hrm_char_handle = characteristic.handle_decl

    start_descriptor_discovery()


def on_descriptor_discovery_response(gattc_event):
    global hrm_cccd_handle

    if gattc_event.gatt_status != ble_driver.NRF_SUCCESS:
        print "Error. Descriptor discovery failed. Error code 0x{0:X}".format(
            gattc_event.gatt_status)
        return

    count = gattc_event.params.desc_disc_rsp.count

    print "Received descriptor discovery response, descriptor count: {}".format(count)

    desc_list = util.desc_array_to_list(gattc_event.params.desc_disc_rsp.descs, count)
    for i in range(0, count):
        descriptor = desc_list[i]
        print "Handle: 0x{0:04X}, UUID: 0x{1:04X}".format(descriptor.handle, descriptor.uuid.uuid)

        if descriptor.uuid.uuid == CCCD_UUID:
            hrm_cccd_handle = descriptor.handle

    print "Press enter to toggle notifications"


def on_sys_attr_missing(gatts_event):
    ble_driver.sd_ble_gatts_sys_attr_set(peripheral_connection_handle, None, 0, 0)


def on_write_response(gattc_event):
    print "Received write response"

    if gattc_event.gatt_status != ble_driver.NRF_SUCCESS:
        print "Error. Write operation failed. Error code 0x{0:X}".format(gattc_event.gatt_status)
        return


def on_hvx(gattc_event):
    if gattc_event.gatt_status != ble_driver.NRF_SUCCESS:
        print "Error. Handle value notification failed. Error code 0x{0:X}".format(
            gattc_event.gatt_status)
        return

    length = gattc_event.params.hvx.len
    data_array = gattc_event.params.hvx.data
    data_list = util.uint8_array_to_list(data_array, length)

    data_list_string = "".join("{0:02X}".format(el) for el in data_list)

    print "Received handle value notification, handle: 0x{0:04X}, value: 0x{1}".format(
        gattc_event.params.hvx.handle, data_list_string)

    if (peripheral_connection_handle != ble_driver.BLE_CONN_HANDLE_INVALID) and send_notifications:
        send_heart_rate_relay(length, data_array)


def on_write(gatts_event):
    global send_notifications
    write_event = gatts_event.params.write

    if write_event.context.char_uuid.uuid == BLE_UUID_HEART_RATE_MEASUREMENT_CHAR:
        cccd_value_array = write_event.data
        cccd_value_list = util.uint8_array_to_list(cccd_value_array, write_event.len)
        cccd_value = cccd_value_list[0]
        set_hrm_cccd(cccd_value)
        send_notifications = (cccd_value == ble_driver.BLE_GATT_HVX_NOTIFICATION)


def send_heart_rate_relay(length, data):
    hvx_length = ble_driver.new_uint16()
    ble_driver.uint16_assign(hvx_length, length)

    hvx_params = ble_driver.ble_gatts_hvx_params_t()
    hvx_params.handle = heart_rate_measurement_handle.value_handle
    hvx_params.type = ble_driver.BLE_GATT_HVX_NOTIFICATION
    hvx_params.offset = 0
    hvx_params.p_len = hvx_length
    hvx_params.p_data = data

    error_code = ble_driver.sd_ble_gatts_hvx(peripheral_connection_handle, hvx_params)

    actual_hvx_length = ble_driver.uint16_value(hvx_length)
    ble_driver.delete_uint16(hvx_length)

    if error_code == ble_driver.NRF_SUCCESS and length != actual_hvx_length:
        error_code = ble_driver.NRF_ERROR_DATA_SIZE
        print "Failed to send heart rate measurement. Error code: 0x{0:02X}".format(error_code)
        return error_code

    if error_code != ble_driver.NRF_SUCCESS:
        print "Failed to send heart rate measurement. Error code: 0x{0:02X}".format(error_code)
        return error_code

    return ble_driver.NRF_SUCCESS


def start_scan():
    error_code = ble_driver.sd_ble_gap_scan_start(scan_params)

    if error_code != ble_driver.NRF_SUCCESS:
        print "Scan start failed"
        return

    print "Scan started"


def start_service_discovery():
    print "Discovering primary services"
    start_handle = 0x0001

    srvc_uuid = ble_driver.ble_uuid_t()
    srvc_uuid.type = ble_driver.BLE_UUID_TYPE_BLE
    srvc_uuid.uuid = BLE_UUID_HEART_RATE_SERVICE

    error_code = ble_driver.sd_ble_gattc_primary_services_discover(central_connection_handle, start_handle,
                                                                   srvc_uuid)

    if error_code != ble_driver.NRF_SUCCESS:
        print "Failed to discover primary services"
        return error_code

    return ble_driver.NRF_SUCCESS


def start_characteristic_discovery():
    print "Discovering characteristics"

    handle_range = ble_driver.ble_gattc_handle_range_t()
    handle_range.start_handle = service_start_handle
    handle_range.end_handle = service_end_handle

    error_code = ble_driver.sd_ble_gattc_characteristics_discover(central_connection_handle,
                                                                  handle_range)

    return error_code


def start_descriptor_discovery():
    print "Discovering descriptors"

    handle_range = ble_driver.ble_gattc_handle_range_t()

    if hrm_char_handle == 0:
        print "Error. No HRM characteristic handle has been found"
        return

    handle_range.start_handle = hrm_char_handle
    handle_range.end_handle = service_end_handle

    ble_driver.sd_ble_gattc_descriptors_discover(connection_handle, handle_range)


def set_adv_data():
    device_name = "HRM Example"
    device_name_utf8 = [ord(character) for character in list(device_name)]

    data_type = [ble_driver.BLE_GAP_AD_TYPE_COMPLETE_LOCAL_NAME]

    payload = list(data_type + device_name_utf8)
    payload_length = len(payload)

    data_list = [payload_length] + payload
    data_length = len(data_list)

    data_array = util.list_to_uint8_array(data_list)
    # To get the correct pointer type, call cast() on the array object.
    data_array_pointer = data_array.cast()

    error_code = ble_driver.sd_ble_gap_adv_data_set(data_array_pointer, data_length, None, 0)

    if error_code != ble_driver.NRF_SUCCESS:
        print "Failed to set advertisement data. Error code: 0x{0:02X}".format(error_code)
        return

    print "Advertising data set"


def start_advertising():
    adv_params = ble_driver.ble_gap_adv_params_t()

    adv_params.type = ble_driver.BLE_GAP_ADV_TYPE_ADV_IND
    adv_params.p_peer_addr = None  # Undirected advertisement.
    adv_params.fp = ble_driver.BLE_GAP_ADV_FP_ANY
    adv_params.p_whitelist = None
    adv_params.interval = util.msec_to_units(40, util.UNIT_0_625_MS)
    adv_params.timeout = 180  # Advertising timeout 180 seconds

    error_code = ble_driver.sd_ble_gap_adv_start(adv_params)

    if error_code != ble_driver.NRF_SUCCESS:
        print "Failed to start advertising. Error code: 0x{0:02X}".format(error_code)
        return
    print "Started advertising"


def encode_heart_rate_measurement(encoded_hrm, heart_rate_value):
    encoded_hrm[0] = 0
    encoded_hrm[1] = heart_rate_value

    return 2


def init_characteristics():
    char_md = ble_driver.ble_gatts_char_md_t()
    cccd_md = ble_driver.ble_gatts_attr_md_t()
    attr_char_value = ble_driver.ble_gatts_attr_t()
    ble_uuid = ble_driver.ble_uuid_t()
    attr_md = ble_driver.ble_gatts_attr_md_t()
    encoded_initial_hrm = ble_driver.uint8_array(MAX_HRM_LEN)

    cccd_md.read_perm.sm = 1
    cccd_md.read_perm.lv = 1
    cccd_md.write_perm.sm = 1
    cccd_md.write_perm.lv = 1
    cccd_md.vloc = ble_driver.BLE_GATTS_VLOC_STACK

    char_md.char_props.notify = 1
    char_md.p_char_user_desc = None
    char_md.p_char_pf = None
    char_md.p_user_desc_md = None
    char_md.p_cccd_md = cccd_md
    char_md.p_sccd_md = None

    ble_uuid.type = ble_driver.BLE_UUID_TYPE_BLE
    ble_uuid.uuid = 0x2A37

    attr_md.read_perm.sm = 1
    attr_md.read_perm.lv = 1
    attr_md.write_perm.sm = 1
    attr_md.write_perm.lv = 1
    attr_md.vloc = ble_driver.BLE_GATTS_VLOC_STACK
    attr_md.rd_auth = 0
    attr_md.wr_auth = 0
    attr_md.vlen = 1

    attr_char_value_init_len = encode_heart_rate_measurement(encoded_initial_hrm, 10)

    attr_char_value.p_uuid = ble_uuid
    attr_char_value.p_attr_md = attr_md
    attr_char_value.init_len = attr_char_value_init_len
    attr_char_value.init_offs = 0
    attr_char_value.max_len = MAX_HRM_LEN
    attr_char_value.p_value = encoded_initial_hrm.cast()

    error_code = ble_driver.sd_ble_gatts_characteristic_add(heart_rate_service_handle,
                                                            char_md,
                                                            attr_char_value,
                                                            heart_rate_measurement_handle)

    if error_code != ble_driver.NRF_SUCCESS:
        print "Failed to initialize characteristics. Error code: 0x{0:02X}".format(error_code)
        return error_code

    print "Characteristics initiated"

    return ble_driver.NRF_SUCCESS


def init_services():
    global heart_rate_service_handle
    ble_uuid = ble_driver.ble_uuid_t()

    ble_uuid.type = ble_driver.BLE_UUID_TYPE_BLE
    ble_uuid.uuid = 0x180D

    heart_rate_service_handle_send = ble_driver.new_uint16()

    error_code = ble_driver.sd_ble_gatts_service_add(ble_driver.BLE_GATTS_SRVC_TYPE_PRIMARY,
                                                     ble_uuid,
                                                     heart_rate_service_handle_send)

    heart_rate_service_handle = ble_driver.uint16_value(heart_rate_service_handle_send)
    ble_driver.delete_uint16(heart_rate_service_handle_send)

    if error_code != ble_driver.NRF_SUCCESS:
        print "Could not initialize service. Error code: 0x{0:02X}".format(error_code)
        return error_code

    print "Services initiated"

    error_code = init_characteristics()

    if error_code != ble_driver.NRF_SUCCESS:
        return error_code

    return ble_driver.NRF_SUCCESS


def set_hrm_cccd(value):
    print "Setting HRM CCCD"

    if hrm_cccd_handle == 0:
        print "Error. No CCCD handle has been found"

    cccd_list = [value, 0]
    cccd_array = util.list_to_uint8_array(cccd_list)

    write_params = ble_driver.ble_gattc_write_params_t()
    write_params.handle = hrm_cccd_handle
    write_params.len = len(cccd_list)
    write_params.p_value = cccd_array.cast()
    write_params.write_op = ble_driver.BLE_GATT_OP_WRITE_REQ
    write_params.offset = 0

    ble_driver.sd_ble_gattc_write(central_connection_handle, write_params)


def init_ble_stack():
    ble_enable_params = ble_driver.ble_enable_params_t()
    ble_enable_params.gatts_enable_params.attr_tab_size = ble_driver.BLE_GATTS_ATTR_TAB_SIZE_DEFAULT
    ble_enable_params.gatts_enable_params.service_changed = False

    error_code = ble_driver.sd_ble_enable(ble_enable_params)

    if error_code == ble_driver.NRF_SUCCESS:
        return error_code

    if error_code == ble_driver.NRF_ERROR_INVALID_STATE:
        print "BLE stack already enabled"
        return ble_driver.NRF_SUCCESS

    print "Failed to enable BLE stack"
    return error_code


def init_connection_params():
    global connection_params
    connection_params = ble_driver.ble_gap_conn_params_t()
    connection_params.min_conn_interval = util.msec_to_units(30, util.UNIT_1_25_MS)
    connection_params.max_conn_interval = util.msec_to_units(60, util.UNIT_1_25_MS)
    connection_params.conn_sup_timeout = util.msec_to_units(4000, util.UNIT_10_MS)
    connection_params.slave_latency = 0


def init_scan_params():
    global scan_params
    scan_params = ble_driver.ble_gap_scan_params_t()
    scan_params.active = 1
    scan_params.interval = util.msec_to_units(200, util.UNIT_0_625_MS)
    scan_params.window = util.msec_to_units(150, util.UNIT_0_625_MS)
    scan_params.timeout = 0x1000


def main(serial_port):
    print "Serial port used: {}".format(serial_port)
    ble_driver.sd_rpc_serial_port_name_set(serial_port)
    ble_driver.sd_rpc_serial_baud_rate_set(115200)
    ble_driver.sd_rpc_log_handler_set(log_message_handler)
    ble_driver.sd_rpc_evt_handler_set(ble_evt_handler)
    error_code = ble_driver.sd_rpc_open()

    if error_code != ble_driver.NRF_SUCCESS:
        print "Failed to open the nRF51 BLE Driver. Error code: 0x{0:X}.".format(error_code)
        return

    error_code = init_ble_stack()

    if error_code != ble_driver.NRF_SUCCESS:
        return

    init_connection_params()
    init_scan_params()

    error_code = init_services()

    if error_code != ble_driver.NRF_SUCCESS:
        return

    set_adv_data()

    start_scan()

    cccd_value = 0

    while True:
        char = sys.stdin.readline()
        if 'q' in char:
            break
        else:
            print "Received character {}".format(char)
        cccd_value ^= CCCD_NOTIFY
        set_hrm_cccd(cccd_value)

    if peripheral_connection_handle != ble_driver.BLE_CONN_HANDLE_INVALID:
        ble_driver.sd_ble_gap_disconnect(peripheral_connection_handle,
                                         ble_driver.BLE_HCI_REMOTE_USER_TERMINATED_CONNECTION)

    if central_connection_handle != ble_driver.BLE_CONN_HANDLE_INVALID:
        ble_driver.sd_ble_gap_disconnect(peripheral_connection_handle,
                                         ble_driver.BLE_HCI_REMOTE_USER_TERMINATED_CONNECTION)

    error_code = ble_driver.sd_rpc_close()

    if error_code != ble_driver.NRF_SUCCESS:
        print "Failed to close the nRF51 BLE Driver. Error code: 0x{0:X}".format(error_code)
        return

    print "Closed"

if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) == 2 else SERIAL_PORT)
    quit()
