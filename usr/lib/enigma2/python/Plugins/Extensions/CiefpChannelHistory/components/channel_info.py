# -*- coding: utf-8 -*-
#
# CiefpChannelHistory - helper za čitanje imena kanala iz service reference
#

import os
from enigma import eServiceReference, eServiceCenter


def detect_service_type(ref_str):
    """
    Najpouzdanija detekcija tipa servisa:
    1. Ako je ref IPTV (4097/5001/5002) → 'iptv' (ne troši frontend)
    2. Ako je ref streamrelay (8192) → 'streamrelay'
    3. Inače probaj frontend (get_tuner_type_from_frontend)
    4. Ako frontend ne radi → fallback na parse_service_type

    Vraća: 'dvb-s', 'dvb-s2', 'dvb-t', 'dvb-t2', 'dvb-c', 'dvb-c2',
           'iptv', 'streamrelay', 'unknown'
    """
    if not ref_str:
        return "unknown"

    # Brza provjera za IPTV i streamrelay (ne troši frontend)
    try:
        stype = ref_str.split(":")[0]
        if stype in ("4097", "5001", "5002"):
            return "iptv"
        if stype == "8192":
            return "streamrelay"
    except Exception:
        pass

    # Probaj frontend (samo ako je trenutni kanal isti kao ref_str)
    try:
        from Screens.InfoBar import InfoBar
        if InfoBar.instance:
            session = InfoBar.instance.session
            current_ref = session.nav.getCurrentlyPlayingServiceReference()
            if current_ref and current_ref.toString() == ref_str:
                ft = get_tuner_type_from_frontend()
                if ft != "unknown":
                    return ft
    except Exception:
        pass

    # Fallback
    return parse_service_type(ref_str)


def parse_service_type(ref_str):
    """
    Fallback parser za service reference (kada frontend nije dostupan).

    Vraća: 'dvb-s', 'dvb-t', 'dvb-c', 'iptv', 'streamrelay', 'unknown'

    Napomena: Ovo je heuristika. Za tačan tip koristi get_tuner_type_from_frontend().
    """
    try:
        if not ref_str:
            return "unknown"
        parts = ref_str.split(":")
        if len(parts) < 3:
            return "unknown"

        # Tip servisa (prvi element)
        stype = parts[0]

        # IPTV
        if stype in ("4097", "5001", "5002"):
            return "iptv"

        # Streamrelay
        if stype == "8192":
            return "streamrelay"

        # DVB (1 = TV, 2 = Radio, 17 = HDTV, itd. — svi imaju namespace)
        if stype in ("1", "2", "17", "22", "25", "31", "134"):
            # Namespace je obično parts[6] u standardnom formatu
            # ali može biti i parts[5] ili parts[7] zavisno od broja polja
            ns = ""
            if len(parts) >= 7:
                ns = parts[6].upper()
            elif len(parts) >= 6:
                ns = parts[5].upper()

            if ns.startswith("EEEE"):
                return "dvb-t"
            if ns.startswith("FFFF"):
                return "dvb-c"
            return "dvb-s"

        return "unknown"
    except Exception:
        return "unknown"

def get_channel_name(ref_str):
    """Vraća ime kanala iz service reference. Sinhrono, glavni thread."""
    try:
        ref = eServiceReference(ref_str)
        info = eServiceCenter.getInstance().info(ref)
        if info:
            name = info.getName(ref)
            if name:
                return name.strip()
    except Exception as e:
        print("[CiefpChannelHistory] get_channel_name error:", e)
    return ""


def get_channel_provider(ref_str):
    """Provider iz service reference."""
    try:
        ref = eServiceReference(ref_str)
        info = eServiceCenter.getInstance().info(ref)
        if info:
            # Neki image-i imaju getProvider
            if hasattr(info, "getProvider"):
                prov = info.getProvider(ref)
                if prov:
                    return prov.strip()
    except Exception:
        pass
    return ""

def get_tuner_type_from_frontend():
    """
    Vraća stvarni tuner type iz aktivnog frontenda.
    Vraća: "dvb-s", "dvb-t", "dvb-c", "dvb-s2", "dvb-t2", "dvb-c2", "iptv", "unknown"
    """
    try:
        from Screens.InfoBar import InfoBar
        if not InfoBar.instance:
            return "unknown"
        session = InfoBar.instance.session
        service = session.nav.getCurrentService()
        if not service:
            return "iptv"  # nema frontenda → vjerovatno IPTV

        frontendInfo = service.frontendInfo()
        if not frontendInfo:
            return "iptv"  # nema frontenda → IPTV

        fd = frontendInfo.getAll(True)
        if not fd:
            return "iptv"

        tuner_type = fd.get("tuner_type", "") or ""

        if tuner_type == "DVB-S":
            return "dvb-s"
        elif tuner_type == "DVB-S2":
            return "dvb-s2"
        elif tuner_type == "DVB-T":
            return "dvb-t"
        elif tuner_type == "DVB-T2":
            return "dvb-t2"
        elif tuner_type == "DVB-C":
            return "dvb-c"
        elif tuner_type == "DVB-C2":
            return "dvb-c2"
        return "unknown"
    except Exception as e:
        print("[CiefpChannelHistory] get_tuner_type error:", e)
        return "unknown"
# ---------- PARENTAL LOCK (blacklist) ----------
_PARENTAL_CACHE = None
_PARENTAL_CACHE_LOADED = False

# Na OpenATV, parental lock se čuva u /etc/enigma2/blacklist
BLACKLIST_PATH = "/etc/enigma2/blacklist"
# Fallback ako postoji whitelist
WHITELIST_PATH = "/etc/enigma2/whitelist"


def _load_parental_refs():
    """
    Učitaj reference iz /etc/enigma2/blacklist (parental lock).
    Ako blacklist ne postoji, probaj whitelist.
    Vraća set referenci (normalizovanih, bez trailing ':').
    """
    global _PARENTAL_CACHE, _PARENTAL_CACHE_LOADED
    if _PARENTAL_CACHE_LOADED:
        return _PARENTAL_CACHE

    _PARENTAL_CACHE = set()
    _PARENTAL_CACHE_LOADED = True

    # Probaj blacklist prvo, pa whitelist
    paths = []
    if os.path.exists(BLACKLIST_PATH):
        paths.append(BLACKLIST_PATH)
    if os.path.exists(WHITELIST_PATH):
        paths.append(WHITELIST_PATH)

    if not paths:
        print("[CiefpChannelHistory] No parental lock file found (blacklist/whitelist)")
        return _PARENTAL_CACHE

    for path in paths:
        try:
            with open(path, "r", encoding="utf-8", errors="ignore") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    # Preskoči komentare
                    if line.startswith("#") and not line.startswith("#SERVICE"):
                        continue
                    # Ukloni #SERVICE prefiks
                    if line.startswith("#SERVICE"):
                        line = line[8:].strip()
                    # Ukloni sve posle #
                    if "#" in line:
                        line = line.split("#")[0].strip()
                    # Normalizuj — ukloni trailing ':'
                    line = line.rstrip(":")
                    # Dodaj samo validne ref-ove
                    if line and (line.startswith("1:") or
                                 line.startswith("4097:") or
                                 line.startswith("8192:") or
                                 line.startswith("5001:") or
                                 line.startswith("5002:")):
                        _PARENTAL_CACHE.add(line)

            print("[CiefpChannelHistory] Loaded %d parental refs from %s"
                  % (len(_PARENTAL_CACHE), path))
        except Exception as e:
            print("[CiefpChannelHistory] parental load error (%s):" % path, e)

    return _PARENTAL_CACHE


def is_parental_locked(ref_str):
    """Provjeri je li ref u parental lock listi (blacklist)."""
    if not ref_str:
        return False
    refs = _load_parental_refs()
    if not refs:
        return False
    ref_clean = ref_str.strip().rstrip(":")
    return ref_clean in refs


def reload_parental_cache():
    """Resetuj cache — pozovi ako se blacklist promijeni."""
    global _PARENTAL_CACHE, _PARENTAL_CACHE_LOADED
    _PARENTAL_CACHE = None
    _PARENTAL_CACHE_LOADED = False