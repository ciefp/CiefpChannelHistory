# -*- coding: utf-8 -*-
#
# CiefpChannelHistory - satellite info
#
import os
import re
import xml.etree.ElementTree as ET


_SAT_CACHE = None
_SAT_CACHE_LOADED = False

SATELLITES_XML_PATHS = [
    "/etc/tuxbox/satellites.xml",
    "/etc/enigma2/satellites.xml",
]


def _load_satellites_xml():
    """Učitaj satellites.xml i vrati dict {position_int: name}."""
    global _SAT_CACHE, _SAT_CACHE_LOADED
    if _SAT_CACHE_LOADED:
        return _SAT_CACHE

    _SAT_CACHE = {}
    _SAT_CACHE_LOADED = True

    xml_path = None
    for p in SATELLITES_XML_PATHS:
        if os.path.exists(p):
            xml_path = p
            break

    if not xml_path:
        return _SAT_CACHE

    try:
        tree = ET.parse(xml_path)
        root = tree.getroot()
        for sat in root.findall("sat"):
            name = sat.get("name", "").strip()
            position_raw = sat.get("position", "").strip()
            if not name or not position_raw:
                continue
            try:
                pos_val = int(position_raw)
            except ValueError:
                continue

            clean_name = re.sub(r'\(\d+\)\s*', '', name).strip()
            clean_name = re.sub(r'^\d+\.\d+[EW]\s*', '', clean_name).strip()

            _SAT_CACHE[pos_val] = clean_name
    except Exception as e:
        print("[CiefpChannelHistory] satellites.xml parse error:", e)

    return _SAT_CACHE


def get_satellite_from_ref(ref_str):
    """
    Parsira namespace iz service reference za DVB-S, DVB-T i DVB-C.
    Ispravno mapira zapadne pozicije na negativne vrednosti iz satellites.xml.
    """
    try:
        parts = ref_str.split(":")
        if len(parts) < 7:
            return "", ""

        raw_ns = parts[6].upper()
        namespace = raw_ns.zfill(8) if len(raw_ns) > 4 else raw_ns + "0000"
        ns_key = namespace[:4].upper()

        # DVB-T i DVB-C
        if ns_key.startswith("EEEE"):
            return "Terrestrial", "Terrestrial"
        if ns_key.startswith("FFFF"):
            return "Cable", "Cable"

        # DVB-S
        try:
            ns_val = int(ns_key, 16)
        except ValueError:
            return "", ""

        if ns_val == 0 or ns_val > 3600:
            return "", ""

        sat_cache = _load_satellites_xml()

        if ns_val < 0x708:   # Istočne pozicije (< 180.0E)
            deg = ns_val / 10.0
            pos_str = "%.1fE" % deg
            xml_lookup_val = int(ns_val)
            sat_name = sat_cache.get(xml_lookup_val, "")
        else:               # Zapadne pozicije
            deg = (3600 - ns_val) / 10.0
            if 0 <= deg <= 180.0:
                pos_str = "%.1fW" % deg
                # W sateliti u satellites.xml imaju negativnu vrednost (npr. -300 za 30.0W)
                xml_lookup_val = -int(round(deg * 10))
                sat_name = sat_cache.get(xml_lookup_val, "")
                # Rezervna opcija ako je u nekom XML-u upisano pozitivno
                if not sat_name:
                    sat_name = sat_cache.get(int(round(deg * 10)), "")
            else:
                return "", ""

        return pos_str, sat_name
    except Exception as e:
        print("[CiefpChannelHistory] get_satellite_from_ref error:", e)
        return "", ""


def get_satellite_for_ref(ref_str):
    if not ref_str:
        return "", ""
    return get_satellite_from_ref(ref_str)


def format_satellite_label(pos_str, sat_name):
    if not pos_str:
        return "Unknown"
    if sat_name and sat_name != pos_str:
        return "%s (%s)" % (pos_str, sat_name)
    return pos_str


def reload_cache():
    global _SAT_CACHE, _SAT_CACHE_LOADED
    _SAT_CACHE = None
    _SAT_CACHE_LOADED = False