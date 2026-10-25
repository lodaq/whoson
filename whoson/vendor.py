"""Who makes this device?  (MAC address -> maker)

Every network gadget has a MAC address — a fixed serial number for its
radio/ethernet hardware, like `aa:bb:cc:11:22:33`.  The first half is
assigned to the maker, so it reveals the brand ("Apple", "Samsung"...).

Two honest caveats baked in:

* Phones and modern gadgets use *private addresses*: they make up a
  random MAC per Wi-Fi network for privacy.  Random ones start with a
  telltale bit we detect, and we show "Private address" instead of a
  wrong maker.
* The table below covers common makers; unknown means unknown, not broken.
"""

# Random/private MACs: the second-least-significant bit of the first
# byte is set (the "locally administered" flag).
def is_private_mac(mac: str) -> bool:
    try:
        first = int(mac.split(":")[0], 16)
    except (ValueError, AttributeError, IndexError):
        return False
    return bool(first & 0x02)


# Common makers by the first three bytes of the MAC (an "OUI").
# Small, offline, best-effort — unknown makers simply show as "unknown".
_OUI = {
    # Apple
    "f0:18:98": "Apple", "ac:de:48": "Apple", "a4:83:e7": "Apple",
    "3c:07:54": "Apple", "98:9e:63": "Apple", "b8:e8:56": "Apple",
    "dc:2b:2a": "Apple", "f0:f1:ec": "Apple", "14:99:e2": "Apple",
    # Samsung
    "8c:0f:5f": "Samsung", "fc:f1:52": "Samsung", "50:b7:c3": "Samsung",
    "34:23:87": "Samsung", "5c:3c:27": "Samsung", "b0:72:bf": "Samsung",
    # Intel (laptop Wi-Fi chips)
    "3c:a9:f4": "Intel", "a0:36:9f": "Intel", "8c:ec:4b": "Intel",
    "24:fd:5b": "Intel", "98:3b:8f": "Intel", "48:e7:da": "Intel",
    # Realtek (cheap TV sticks, dongles)
    "52:54:00": "QEMU/KVM (virtual)", "0e:00:00": "realtek",
    "00:e0:4c": "Realtek", "b8:27:eb": "Raspberry Pi",
    "dc:a6:32": "Raspberry Pi", "e4:5f:01": "Raspberry Pi",
    # Espressif (ESP32/ESP8266 — most DIY smart-home gadgets)
    "24:6f:28": "Espressif", "30:ae:a4": "Espressif", "5c:cf:7f": "Espressif",
    "a4:cf:12": "Espressif", "84:0d:8e": "Espressif", "68:c6:ac": "Espressif",
    # Xiaomi / Redmi / Poco
    "64:09:80": "Xiaomi", "78:11:dc": "Xiaomi", "8c:be:be": "Xiaomi",
    "50:8f:4c": "Xiaomi", "f8:a4:5f": "Xiaomi",
    # Huawei / Honor
    "18:de:d7": "Huawei", "34:6b:d3": "Huawei", "78:1d:ba": "Huawei",
    "84:46:fe": "Huawei", "c8:0c:c8": "Huawei", "48:00:29": "Huawei",
    # ZTE
    "f4:6a:92": "ZTE", "34:4b:50": "ZTE", "d8:9d:67": "ZTE",
    # Networking gear
    "50:c7:bf": "TP-Link", "a4:2b:b0": "TP-Link", "14:cc:20": "TP-Link",
    "c8:3a:35": "TP-Link", "34:96:72": "TP-Link",
    "1c:bf:c0": "Mercury/Mercusys", "d8:07:b6": "Tenda",
    "c8:3c:85": "D-Link", "14:d6:4d": "D-Link", "34:08:04": "D-Link",
    "04:d4:c4": "D-Link", "ac:84:c6": "ASUS", "04:d9:f5": "ASUS",
    "38:2c:4a": "ASUS", "e0:3f:49": "TRENDnet", "00:1a:2b": "Ayecom",
    "b0:4e:26": "IPC (IP cameras)", "f4:5e:ab": "Beken (IoT)",
    # Google / Nest / Chromecast
    "f4:f5:d8": "Google", "6c:ad:f8": "Google", "54:60:09": "Google",
    "3c:5a:b4": "Google", "fa:8f:ca": "Google",
    # Amazon (Echo, Fire TV, Kindle)
    "fc:65:de": "Amazon", "74:c2:46": "Amazon", "f0:4f:7c": "Amazon",
    "18:b6:97": "Amazon", "44:65:0d": "Amazon", "40:b4:cd": "Amazon",
    # TV / console makers
    "48:44:f7": "Samsung TV", "60:6b:bd": "LG", "00:e0:91": "LG",
    "8c:10:d4": "Sony", "b4:3d:50": "Sony", "30:f9:ed": "Sony",
    "98:b6:e9": "Nintendo", "e8:4e:ce": "Xiaomi TV",
    "00:1a:9a": "Xbox (Microsoft)", "7c:ed:8d": "Xbox (Microsoft)",
    # PC makers
    "3c:d9:2b": "Hewlett-Packard", "10:1f:74": "Hewlett-Packard",
    "d4:be:d9": "Dell", "8c:04:ba": "Azurewave",
    "9c:b6:d0": "Dell", "80:86:f2": "Dell",
    "48:2a:e3": "Lenovo", "60:d9:c7": "Lenovo",
    # Oneplus/Oppo/Vivo
    "38:2d:5d": "OnePlus", "74:23:44": "Oppo", "8c:cd:e8": "Vivo",
    # Broadlink, Tuya-based smart plugs, SONOFF
    "24:df:a7": "Broadlink", "10:56:ca": "Broadlink", "84:0d:8e": "Espressif",
    "d8:f1:5b": "Tuya (smart home)", "7c:f6:66": "Tuya (smart home)",
    "10:ce:a9": "Sonoff", "68:57:2d": "Shelly",
    # Routers themselves
    "c8:0e:14": "Huawei router", "20:0d:b0": "Huawei router",
    "4c:1f:cc": "Huawei router", "58:2a:f7": "Huawei router",
    "cc:32:e5": "TP-Link router", "e4:95:6e": "Xiaomi router",
}


def vendor_of(mac: str) -> str:
    """Maker name for a MAC, or 'Private address'/'unknown' honestly."""
    if not mac:
        return "unknown"
    mac = mac.strip().lower()
    if is_private_mac(mac):
        return "Private address"
    return _OUI.get(":".join(mac.split(":")[:3]), "unknown")
