# -*- coding: utf-8 -*-
#
# CiefpChannelHistory - CAID info
#
import os


ECM_INFO_PATH = "/tmp/ecm.info"


# Mapiranje CAID -> ime sistema
CAID_NAMES = {
    0x0500: "Viaccess", 0x0600: "Seca", 0x0900: "NDS",
    0x098D: "NDS", 0x098C: "NDS", 0x091F: "NDS", 0x0911: "NDS",
    0x09CD: "NDS", 0x09C4: "NDS", 0x0963: "NDS", 0x0961: "NDS",
    0x0960: "NDS", 0x092B: "NDS", 0x09BD: "NDS", 0x09F0: "NDS",
    0x1813: "Nagravision", 0x1833: "Nagravision", 0x1834: "Nagravision",
    0x1830: "Nagravision", 0x1817: "Nagravision", 0x1818: "Nagravision",
    0x1878: "Nagravision", 0x1819: "Nagravision", 0x1880: "Nagravision",
    0x1883: "Nagravision", 0x1884: "Nagravision", 0x1863: "Nagravision",
    0x183D: "Nagravision", 0x1814: "Nagravision", 0x1810: "Nagravision",
    0x1811: "Nagravision", 0x1802: "Nagravision", 0x1807: "Nagravision",
    0x1843: "Nagravision", 0x1856: "Nagra Ma", 0x183E: "Nagra Ma",
    0x1803: "Nagra Ma", 0x1861: "Nagra Ma", 0x181D: "Nagra Ma",
    0x186C: "Nagra Ma", 0x1870: "Nagra Ma",
    0x0E00: "PowerVu", 0x1700: "Drecrypt", 0x1800: "Tandberg",
    0x2600: "Biss", 0x2700: "Bulcrypt",
    0x0D98: "Cryptoworks", 0x0D97: "Cryptoworks", 0x0D95: "Cryptoworks",
    0x0D00: "Cryptoworks", 0x0D01: "Cryptoworks", 0x0D02: "Cryptoworks",
    0x0D03: "Cryptoworks", 0x0D04: "Cryptoworks",
    0x0624: "Irdeto", 0x06E1: "Irdeto", 0x0653: "Irdeto",
    0x0648: "Irdeto", 0x06D9: "Irdeto", 0x0656: "Irdeto",
    0x0650: "Irdeto", 0x0D96: "Irdeto", 0x0629: "Irdeto",
    0x0606: "Irdeto", 0x0664: "Irdeto", 0x06EE: "Irdeto",
    0x06E2: "Irdeto", 0x06F8: "Irdeto", 0x0604: "Irdeto",
    0x069B: "Irdeto", 0x069F: "Irdeto",
    0x0B01: "Conax", 0x0B02: "Conax", 0x0B00: "Conax",
    0x4AEE: "Bulcrypt", 0x5581: "Bulcrypt",
    0x1EC0: "CryptoGuard", 0x0100: "Seca",
}


def get_ca_name(caid_str):
    """Mapiraj CAID (string, npr. '0624') u ime sistema."""
    try:
        caid_int = int(caid_str, 16)
    except (ValueError, TypeError):
        return ""
    return CAID_NAMES.get(caid_int, "")


def get_caids_for_service():
    """
    Čita CAID-ove iz AKTIVNOG servisa (service.info()).
    Ovo je pouzdanije od ecm.info jer je dostupno odmah.

    Vraća dict:
    - caids: lista svih CAID-ova (npr. ['0500', '0624', '0653'])
    - active_caid: aktivni CAID iz ecm.info (npr. '0624')
    - active_caid_name: ime aktivnog sistema (npr. 'Irdeto')
    - is_crypted: True ako ima CAID-ova
    - provider: iz ecm.info ako postoji
    """
    result = {
        "caids": [],
        "caid": "",  # aktivni (za kompatibilnost)
        "caid_name": "",
        "caids_str": "",  # svi, comma-separated
        "is_crypted": False,
        "provider": "",
        "system": "",
    }

    # 1) Uzmi SVE CAID-ove iz service.info()
    try:
        from Screens.InfoBar import InfoBar
        from enigma import iServiceInformation
        if InfoBar.instance:
            session = InfoBar.instance.session
            service = session.nav.getCurrentService()
            if service:
                info = service.info()
                if info:
                    caids = info.getInfoObject(iServiceInformation.sCAIDs) or []
                    if caids:
                        result["caids"] = ["%04X" % c for c in sorted(set(caids))]
                        result["caids_str"] = ",".join(result["caids"])
                        result["is_crypted"] = True
    except Exception as e:
        print("[CiefpChannelHistory] get_caids_for_service error:", e)

    # 2) Uzmi AKTIVNI CAID iz ecm.info
    try:
        ecm = read_ecm_info_raw()
        if ecm.get("caid"):
            result["caid"] = ecm["caid"]
            result["caid_name"] = ecm.get("caid_name", "")
            result["provider"] = ecm.get("provider", "")
            result["system"] = ecm.get("system", "")
            # Ako ecm ima CAID ali service.info nije vratio ništa — koristi ecm
            if not result["caids"] and ecm.get("caid"):
                result["caids"] = [ecm["caid"]]
                result["caids_str"] = ecm["caid"]
                result["is_crypted"] = True
    except Exception as e:
        print("[CiefpChannelHistory] ecm read error:", e)

    return result


def read_ecm_info_raw():
    """Interna — čita /tmp/ecm.info i vraća dict (bez side efekata)."""
    result = {
        "caid": "",
        "caid_name": "",
        "system": "",
        "provider": "",
        "using": "",
        "is_crypted": False,
    }

    if not os.path.exists(ECM_INFO_PATH):
        return result

    try:
        with open(ECM_INFO_PATH, "r") as f:
            content = f.read()
    except Exception:
        return result

    if not content.strip():
        return result

    for line in content.splitlines():
        line = line.strip()
        if ":" not in line:
            continue
        key, value = line.split(":", 1)
        key = key.strip().lower()
        value = value.strip()

        if key == "caid":
            clean = value.replace("0x", "").replace("0X", "").upper()
            if len(clean) < 4:
                clean = clean.zfill(4)
            result["caid"] = clean
            result["is_crypted"] = True
        elif key == "system":
            result["system"] = value
        elif key == "provider":
            result["provider"] = value
        elif key in ("using", "protocol"):
            result["using"] = value

    if result["caid"]:
        result["caid_name"] = get_ca_name(result["caid"])
        if not result["system"]:
            result["system"] = result["caid_name"]

    return result


# Zadrži staru funkciju za kompatibilnost
def read_ecm_info():
    """Stara funkcija — vraća samo aktivni CAID (kompatibilnost)."""
    return read_ecm_info_raw()


def format_caid_label(caid_str, caid_name):
    """Formatira label: 'Irdeto (0624)' ili samo '0624'."""
    if not caid_str:
        return "FTA"
    if caid_name:
        return "%s (%s)" % (caid_name, caid_str)
    return caid_str