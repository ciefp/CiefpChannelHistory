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


# Cache za lamedb providers
_LAMEDB_CACHE = None
_LAMEDB_CACHE_LOADED = False
_LAMEDB_PATH = "/etc/enigma2/lamedb"


def _load_lamedb_providers():
    """
    Učitaj providers iz /etc/enigma2/lamedb.
    Vraća dict {ref_kljuc: provider_name}.

    Format lamedb:
        0307:00eb0000:0c94:0003:25:0       ← sid:ns:tsid:onid:srv_type:src
        HBO HD                              ← naziv
        p:M7 Group,c:...,C:...,C:...        ← provider + CAID
    """
    global _LAMEDB_CACHE, _LAMEDB_CACHE_LOADED
    if _LAMEDB_CACHE_LOADED:
        return _LAMEDB_CACHE

    _LAMEDB_CACHE = {}
    _LAMEDB_CACHE_LOADED = True

    if not os.path.exists(_LAMEDB_PATH):
        print("[CiefpChannelHistory] lamedb not found: %s" % _LAMEDB_PATH)
        return _LAMEDB_CACHE

    try:
        with open(_LAMEDB_PATH, "r", encoding="utf-8", errors="ignore") as f:
            lines = f.readlines()

        i = 0
        while i < len(lines):
            line = lines[i].strip()
            # Tražimo liniju koja počinje sa hex (sid:ns:tsid:onid:srv_type:src)
            if (line and ":" in line and
                    not line.startswith("p:") and
                    not line.startswith("c:") and
                    not line.startswith("C:") and
                    not line.startswith("f:") and
                    not line.startswith("#")):
                parts = line.split(":")
                if len(parts) >= 5:
                    # parts: sid, ns, tsid, onid, srv_type, src
                    sid = parts[0].lower()
                    ns = parts[1].lower()
                    tsid = parts[2].lower()
                    onid = parts[3].lower()

                    # Ključevi za lookup (različiti formati)
                    keys = [
                        "%s:%s:%s:%s" % (sid, ns, tsid, onid),
                        "%s:%s:%s:%s" % (sid.lstrip("0") or "0", ns,
                                         tsid.lstrip("0") or "0",
                                         onid.lstrip("0") or "0"),
                    ]

                    # Nađi provider u sljedeće 2-3 linije (p:)
                    provider = ""
                    for j in range(i + 1, min(i + 5, len(lines))):
                        next_line = lines[j].strip()
                        if next_line.startswith("p:"):
                            # Format: p:Provider Name,c:...,C:...
                            rest = next_line[2:]  # ukloni "p:"
                            # Uzmi sve do prve zapete
                            if "," in rest:
                                provider = rest.split(",")[0].strip()
                            else:
                                provider = rest.strip()
                            break

                    if provider:
                        for key in keys:
                            _LAMEDB_CACHE[key] = provider

            i += 1

        print("[CiefpChannelHistory] Loaded %d providers from lamedb"
              % len(_LAMEDB_CACHE))
    except Exception as e:
        print("[CiefpChannelHistory] lamedb parse error:", e)

    return _LAMEDB_CACHE


def _ref_to_lamedb_key(ref_str):
    """
    Konvertuj service reference u lamedb ključ za provider lookup.

    Service ref: 1:0:19:307:C94:3:EB0000:0:0:0:
    - parts[3] = SID  (307)
    - parts[4] = TSID (C94)
    - parts[5] = ONID (3)
    - parts[6] = NS   (EB0000)

    Lamedb key: sid:ns:tsid:onid
    - 0307:00eb0000:0c94:0003
    """
    try:
        parts = ref_str.split(":")
        if len(parts) < 7:
            return None

        sid = parts[3].lower().zfill(4)
        tsid = parts[4].lower().zfill(4)
        onid = parts[5].lower().zfill(4)
        ns = parts[6].lower().zfill(8)

        # Format 1: padded
        key1 = "%s:%s:%s:%s" % (sid, ns, tsid, onid)
        # Format 2: bez leading zeros
        key2 = "%s:%s:%s:%s" % (sid.lstrip("0") or "0", ns,
                                tsid.lstrip("0") or "0",
                                onid.lstrip("0") or "0")
        return key1, key2
    except Exception as e:
        print("[CiefpChannelHistory] ref_to_lamedb_key error:", e)
        return None


def get_channel_provider(ref_str):
    """
    Provider iz lamedb-a (p: linija).
    Fallback na service.info() ako lamedb nema.
    """
    if not ref_str:
        return ""

    # 1) Probaj iz lamedb-a
    try:
        keys = _ref_to_lamedb_key(ref_str)
        if keys:
            providers = _load_lamedb_providers()
            for key in keys:
                prov = providers.get(key)
                if prov:
                    return prov
    except Exception as e:
        print("[CiefpChannelHistory] lamedb provider error:", e)

    # 2) Fallback na service.info()
    try:
        ref = eServiceReference(ref_str)
        info = eServiceCenter.getInstance().info(ref)
        if info and hasattr(info, "getProvider"):
            prov = info.getProvider(ref)
            if prov:
                return prov.strip()
    except Exception:
        pass

    return ""


def reload_lamedb_cache():
    """Resetuj cache — pozovi ako se lamedb promijeni."""
    global _LAMEDB_CACHE, _LAMEDB_CACHE_LOADED
    _LAMEDB_CACHE = None
    _LAMEDB_CACHE_LOADED = False

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

# ---------- ONLINE VIDEO FILTER (YouTube, googlevideo, itd.) ----------

_ONLINE_VIDEO_DOMAINS = (
    "googlevideo.com",
    "youtube.com",
    "youtu.be",
    "ytimg.com",
    "vimeo.com",
    "dailymotion.com",
    "twitch.tv",
    "fbcdn.net",
    "instagram.com",
    "tiktok.com",
    "streamable.com",
    "redd.it",
    "bitchute.com",
    "rumble.com",
    "odysee.com",
    "lbry.tv",
)

# Ekstenzije za video/audio fajlove (lokalni ili stream)
_VIDEO_EXTENSIONS = (
    ".mp4", ".mkv", ".avi", ".mov", ".wmv", ".flv", ".webm", ".m4v",
    ".mp3", ".aac", ".flac", ".ogg", ".wav", ".m4a", ".wma",
)

# Putanje koje označavaju muziku/radio/kameru (ne TV kanal)
_MEDIA_PATHS = (
    "/muzika/",
    "/music/",
    "/radio/",
    "/kamera/",
    "/camera/",
    "/webcam/",
    "/cam/",
    "/stream/audio/",
    "/audio/",
    "/songs/",
    "/pesme/",
)


def _is_ip_address(host):
    """Provjeri je li host IP adresa (ne domena)."""
    if not host:
        return False
    # IPv4: 4 broja odvojena tačkom
    parts = host.split(".")
    if len(parts) == 4:
        try:
            for p in parts:
                if not (0 <= int(p) <= 255):
                    return False
            return True
        except ValueError:
            return False
    return False


def is_online_video_ref(ref_str):
    """
    Provjeri je li service reference online video/audio (YouTube, MP3, kamera)
    a ne pravi TV kanal.

    Vraća True ako treba preskočiti.
    Vraća False ako je pravi kanal (DVB-S/T/C, IPTV sa kratkim URL-om).
    """
    if not ref_str:
        return False

    # 1) Ako je DVB (1:), nije online video
    try:
        stype = ref_str.split(":")[0]
        if stype in ("1", "2", "17", "22", "25", "31", "134"):
            return False
    except Exception:
        pass

    # 2) Za IPTV/streamrelay (4097, 5001, 5002, 8192) — provjeri URL
    try:
        if stype in ("4097", "5001", "5002", "8192"):
            ref_lower = ref_str.lower()

            # 2a) Ako je URL predugačak (> 300 znakova) → online video
            if len(ref_str) > 300:
                return True

            # 2b) Provjeri poznate domene online videa
            for domain in _ONLINE_VIDEO_DOMAINS:
                if domain in ref_lower:
                    return True

            # 2c) YouTube specifični parametri
            if "videoplayback" in ref_lower:
                return True
            if "expire=" in ref_lower and "itag=" in ref_lower:
                return True

            # 2d) Ekstenzije video/audio fajlova
            for ext in _VIDEO_EXTENSIONS:
                if ext in ref_lower:
                    return True

            # 2e) Putanje za muziku/radio/kameru
            for path in _MEDIA_PATHS:
                if path in ref_lower:
                    return True

            # 2f) IP adrese sa portovima za streaming
            # (npr. http://212.200.115.2:8012/...)
            # Ako URL ima IP adresu i port, vjerojatno je web kamera/radio/muzika
            try:
                import re
                # Pronađi http://IP:PORT/ putanju
                m = re.search(r'https?://([\d\.]+):(\d+)', ref_lower)
                if m:
                    host = m.group(1)
                    port = int(m.group(2))
                    # Ako je IP adresa (ne domena), vjerojatno je stream
                    if _is_ip_address(host):
                        # Port 8000-9000 su tipični za streaming servere
                        # (Icecast, Shoutcast, itd.)
                        if 8000 <= port <= 9000:
                            return True
            except Exception:
                pass

    except Exception:
        pass

    return False