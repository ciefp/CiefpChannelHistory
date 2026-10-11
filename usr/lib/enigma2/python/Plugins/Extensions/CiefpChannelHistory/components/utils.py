# -*- coding: utf-8 -*-
#
# CiefpChannelHistory - common helpers
#
import os
from Tools.LoadPixmap import LoadPixmap


def ensure_folder(path):
    if path and not os.path.exists(path):
        try:
            os.makedirs(path)
        except Exception:
            pass
    return path


def load_pixmap_safe(path):
    if path and os.path.exists(path):
        try:
            return LoadPixmap(path)
        except Exception:
            return None
    return None


def format_duration(seconds):
    seconds = int(seconds)
    h = seconds // 3600
    m = (seconds % 3600) // 60
    if h > 0:
        return "%dh %02dmin" % (h, m)
    return "%dmin" % m

def format_bar(pct, width=12):
    """Bar chart — '█' za popunjen, '.' za prazan dio."""
    filled = int(round(pct / 100.0 * width))
    filled = max(0, min(width, filled))
    if filled == 0 and pct > 0.05:
        filled = 1
    return "█" * filled + "." * (width - filled)
