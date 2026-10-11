# -*- coding: utf-8 -*-
#
# CiefpChannelHistory - EPG reader
#
import time
from enigma import eEPGCache, eServiceReference


def _event_to_dict(event):
    if not event:
        return None
    if isinstance(event, (tuple, list)):
        return {
            "begin": int(event[0]) if len(event) > 0 and event[0] else None,
            "duration": int(event[1]) if len(event) > 1 and event[1] else None,
            "name": str(event[2]) if len(event) > 2 else "",
            "short": str(event[3]) if len(event) > 3 else "",
            "ext": str(event[4]) if len(event) > 4 else "",
        }
    try:
        return {
            "begin": int(event.getBeginTime()) if hasattr(event, "getBeginTime") else None,
            "duration": int(event.getDuration()) if hasattr(event, "getDuration") else None,
            "name": event.getEventName() or "",
            "short": event.getShortDescription() or "",
            "ext": event.getExtendedDescription() or "",
        }
    except Exception:
        return None


def get_epg_for_ref(ref_str, max_items=10):
    """Vraća listu EPG događaja za zadati service reference."""
    out = []
    try:
        ref = eServiceReference(ref_str)
        epg = eEPGCache.getInstance()
        cur = epg.lookupEventTime(ref, -1, 0)
        cur_d = _event_to_dict(cur)
        if not cur_d or not cur_d.get("name"):
            return []
        out.append(cur_d)
        t = cur_d.get("begin")
        d = cur_d.get("duration")
        if not t or not d:
            return out
        next_time = int(t) + int(d) + 1
        for _ in range(max_items - 1):
            ev = epg.lookupEventTime(ref, next_time, 0)
            ev_d = _event_to_dict(ev)
            if not ev_d or not ev_d.get("name"):
                break
            out.append(ev_d)
            b = ev_d.get("begin")
            dd = ev_d.get("duration")
            if not b or not dd:
                break
            next_time = int(b) + int(dd) + 1
    except Exception as e:
        print("[CiefpChannelHistory] get_epg_for_ref error:", e)
    return out


def format_event_time(event, fmt="%H:%M"):
    """Formatira početak EPG događaja."""
    b = event.get("begin") if event else None
    if not b:
        return "--:--"
    try:
        return time.strftime(fmt, time.localtime(int(b)))
    except Exception:
        return "--:--"