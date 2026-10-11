# -*- coding: utf-8 -*-
#
# CiefpChannelHistory
# Channel watch history with statistics, EPG and TMDB enrichment
#
# -*- coding: utf-8 -*-
#
# CiefpChannelHistory
# Channel watch history with statistics, EPG and TMDB enrichment
#
from __future__ import print_function
import os
import re
import ssl
import json
import time
import threading
import urllib.request
import urllib.parse
from datetime import datetime

from Components.config import (config, ConfigSubsection, ConfigText,
                               ConfigSelection, ConfigYesNo, ConfigNumber,
                               configfile)
from Components.Pixmap import Pixmap
from Components.ActionMap import ActionMap
from Components.Label import Label
from Components.MenuList import MenuList
from Plugins.Plugin import PluginDescriptor
from Screens.Screen import Screen
from Screens.VirtualKeyBoard import VirtualKeyBoard
from Screens.MessageBox import MessageBox
from enigma import eTimer, eServiceReference, eConsoleAppContainer
# Local components
from .components.history_db import HistoryDB
from .components.history_hook import (ChannelTracker, install_hook,
                                      uninstall_hook, get_tracker)
from .components.picon_manager import PiconManager
from .components.utils import (ensure_folder, load_pixmap_safe,
                               format_duration, format_bar)
from .components.epg_reader import get_epg_for_ref
from .components.tmdb_client import (tmdb_search_multi, tmdb_details,
                                      omdb_rating, is_generic_title)
from .components.screens.epg_list_screen import EPGListScreen
from .components.channel_info import (get_channel_name, get_channel_provider,
                                      parse_service_type, detect_service_type)
# ---------- CONFIG ----------
config.plugins.ciefpchannelhistory = ConfigSubsection()
config.plugins.ciefpchannelhistory.db_folder = ConfigSelection(
    default="/media/hdd/CiefpChannelHistory/",
    choices=[
        ("/media/hdd/CiefpChannelHistory/", "/media/hdd/"),
        ("/media/usb/CiefpChannelHistory/", "/media/usb/"),
        ("/tmp/CiefpChannelHistory/", "/tmp/ (izgubi se na reboot)"),
    ])
config.plugins.ciefpchannelhistory.history_size = ConfigNumber(default=15)
config.plugins.ciefpchannelhistory.min_watch = ConfigNumber(default=30)
config.plugins.ciefpchannelhistory.debounce = ConfigNumber(default=10)
config.plugins.ciefpchannelhistory.history_retention = ConfigSelection(
    default="90",
    choices=[
        ("30", "30 days"),
        ("60", "60 days"),
        ("90", "90 days"),
        ("180", "180 days"),
        ("365", "1 year"),
        ("0", "Forever"),
    ])
config.plugins.ciefpchannelhistory.filter_adult = ConfigYesNo(default=True)
config.plugins.ciefpchannelhistory.tmdb_api_key = ConfigText(default="", fixed_size=False)
config.plugins.ciefpchannelhistory.omdb_api_key = ConfigText(default="", fixed_size=False)
config.plugins.ciefpchannelhistory.groq_api_key = ConfigText(default="", fixed_size=False)
config.plugins.ciefpchannelhistory.cache_folder = ConfigSelection(
    default="/tmp/CiefpChannelHistory/cache/",
    choices=[
        ("/tmp/CiefpChannelHistory/cache/", "/tmp/"),
        ("/media/hdd/CiefpChannelHistory/cache/", "/media/hdd/"),
    ])
config.plugins.ciefpchannelhistory.cache_enabled = ConfigYesNo(default=True)
config.plugins.ciefpchannelhistory.show_imdb_rating = ConfigYesNo(default=True)
config.plugins.ciefpchannelhistory.language = ConfigSelection(default="en-US", choices=[
    ("en-US", "English"),
    ("sr-RS", "Srpski"),
    ("hr-HR", "Hrvatski"),
    ("bs-BA", "Bosanski"),
    ("de-DE", "Deutsch"),
    ("fr-FR", "Français"),
    ("es-ES", "Español"),
    ("it-IT", "Italiano"),
    ("ru-RU", "Русский"),
])

PLUGIN_NAME = "CiefpChannelHistory"
PLUGIN_DESC = "Channel watch history with statistics, EPG and TMDB info"
PLUGIN_VERSION = "1.1"
PLUGIN_DIR = os.path.dirname(__file__) if '__file__' in globals() else \
    "/usr/lib/enigma2/python/Plugins/Extensions/CiefpChannelHistory"

TMDB_API_KEY_FILE = os.path.join(PLUGIN_DIR, "tmdbapikey.txt")
OMDB_API_KEY_FILE = os.path.join(PLUGIN_DIR, "omdbapikey.txt")
GROQ_API_KEY_FILE = os.path.join(PLUGIN_DIR, "groqapikey.txt")

PLUGIN_ICON = os.path.join(PLUGIN_DIR, "icon.png")
BACKGROUND_SETTINGS = os.path.join(PLUGIN_DIR, "settings.png")
PLACEHOLDER = os.path.join(PLUGIN_DIR, "placeholder.png")

VERSION_URL = "https://raw.githubusercontent.com/ciefp/CiefpChannelHistory/main/version.txt"
UPDATE_COMMAND = ("wget -q --no-check-certificate "
                  "https://raw.githubusercontent.com/ciefp/CiefpChannelHistory/main/installer.sh "
                  "-O - | /bin/sh")


# ---------- API KEY LOAD/SAVE ----------
def _load_key_from_file(path, cfg_attr):
    if os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                key = f.read().strip()
            if key:
                cfg = getattr(config.plugins.ciefpchannelhistory, cfg_attr)
                cfg.value = key
                cfg.save()
        except Exception:
            pass


def _save_key_to_file(path, value):
    try:
        with open(path, "w", encoding="utf-8") as f:
            f.write((value or "").strip())
    except Exception:
        pass


def load_all_api_keys():
    _load_key_from_file(TMDB_API_KEY_FILE, "tmdb_api_key")
    _load_key_from_file(OMDB_API_KEY_FILE, "omdb_api_key")
    _load_key_from_file(GROQ_API_KEY_FILE, "groq_api_key")


# ---------- DB / TRACKER SINGLETON ----------
_db = None
_tracker = None
_db_lock = threading.Lock()


def get_db():
    global _db
    with _db_lock:
        if _db is None:
            folder = config.plugins.ciefpchannelhistory.db_folder.value
            ensure_folder(folder)
            db_path = os.path.join(folder, "history.db")
            try:
                _db = HistoryDB(db_path)
            except Exception as e:
                print("[CiefpChannelHistory] DB init error:", e)
                _db = HistoryDB("/tmp/CiefpChannelHistory/history.db")
        return _db


def get_or_create_tracker():
    global _tracker
    if _tracker is not None:
        return _tracker

    db = get_db()

    def resolver(ref_str):
        name = get_channel_name(ref_str)
        provider = get_channel_provider(ref_str)
        stype = detect_service_type(ref_str)
        return (name, provider, stype)

    session = None
    try:
        from Screens.InfoBar import InfoBar
        if InfoBar.instance:
            session = InfoBar.instance.session
    except Exception:
        pass

    _tracker = ChannelTracker(
        db,
        min_watch_seconds=int(config.plugins.ciefpchannelhistory.min_watch.value),
        debounce_seconds=int(config.plugins.ciefpchannelhistory.debounce.value),
        poll_interval_seconds=5,
        name_resolver=resolver,
        session=session
    )

    from .components import history_hook
    history_hook.set_tracker(_tracker)

    return _tracker


# ---------- MAIN SCREEN ----------
class CiefpChannelHistoryMain(Screen):
    skin = """
        <screen name="CiefpChannelHistoryMain" position="0,0" size="1920,1080"
                backgroundColor="#011a2e" >

            <!-- LEVA STRANA 1/3 -->
            <widget name="picon" position="40,40" size="220,140" alphatest="blend" zPosition="2"/>

            <widget name="clock" position="290,40" size="200,100" font="Regular;80"
                    foregroundColor="#FFFFFF" backgroundColor="#011a2e"
                    transparent="1" halign="left"/>
            <widget name="day" position="500,40" size="200,40" font="Regular;30"
                    foregroundColor="#00BFFF" backgroundColor="#011a2e"
                    transparent="1" halign="left"/>
            <widget name="date" position="500,100" size="200,40" font="Regular;30"
                    foregroundColor="#00BFFF" backgroundColor="#011a2e"
                    transparent="1" halign="left"/>

            <widget name="service_name" position="40,200" size="600,50" font="Regular;36"
                    foregroundColor="#FFFFFF" backgroundColor="#011a2e" transparent="1"/>

            <widget name="history_list" position="30,260" size="610,720"
                    scrollbarMode="showOnDemand" itemHeight="40"
                    font="Regular;26" backgroundColor="#011a2e"/>

            <!-- DESNA STRANA 2/3 -->
            <widget name="title" position="680,40" size="900,50" font="Regular;38"
                    foregroundColor="#FFFFFF" backgroundColor="#011a2e" transparent="1"/>
            <widget name="epg_title" position="680,95" size="900,35" font="Regular;24"
                    foregroundColor="#A0A0A0" backgroundColor="#011a2e" transparent="1"/>

            <widget name="duration" position="680,140" size="300,35" font="Regular;26"
                    foregroundColor="#D3D3D3" backgroundColor="#011a2e" transparent="1"/>
            <widget name="rating" position="680,180" size="300,35" font="Regular;26"
                    foregroundColor="#03a81f" backgroundColor="#011a2e" transparent="1"/>
            <widget name="imdb_rating" position="680,220" size="300,35" font="Regular;26"
                    foregroundColor="#F5C518" backgroundColor="#011a2e" transparent="1"/>
            <widget name="genres" position="680,260" size="600,35" font="Regular;26"
                    foregroundColor="#f702db" backgroundColor="#011a2e" transparent="1"/>
            <widget name="director" position="680,300" size="900,35" font="Regular;26"
                    foregroundColor="#f79102" backgroundColor="#011a2e" transparent="1"/>

            <widget name="plot" position="680,340" size="600,450" font="Regular;24"
                    foregroundColor="#FFFFFF" backgroundColor="#011a2e"
                    transparent="1" valign="top"/>

            <widget name="cast_header" position="680,800" size="300,30" font="Regular;24"
                    foregroundColor="#00FFFF" backgroundColor="#011a2e" transparent="1"/>
            <widget name="cast_col1" position="680,850" size="510,280" font="Regular;20"
                    foregroundColor="#00FFFF" backgroundColor="#011a2e"
                    transparent="1" valign="top"/>
            <widget name="cast_col2" position="1200,850" size="510,280" font="Regular;20"
                    foregroundColor="#00FFFF" backgroundColor="#011a2e"
                    transparent="1" valign="top"/>

            <widget name="poster" position="1300,40" size="500,750" alphatest="blend" zPosition="2"/>

            <widget name="status" position="1280,1010" size="820,40" font="Regular;22"
                    foregroundColor="#00FF00" backgroundColor="#011a2e"
                    transparent="1" halign="left"/>

            <!-- Dugmad -->
            <ePixmap pixmap="buttons/red.png" position="0,1010" size="35,35" alphatest="blend"/>
            <eLabel text="Exit" position="50,1010" size="160,40" font="Regular;26"
                    foregroundColor="white" backgroundColor="#800000"
                    halign="center" valign="center"/>
            <ePixmap pixmap="buttons/green.png" position="220,1010" size="35,35" alphatest="blend"/>
            <eLabel text="Stats" position="270,1010" size="160,40" font="Regular;26"
                    foregroundColor="white" backgroundColor="#008000"
                    halign="center" valign="center"/>
            <ePixmap pixmap="buttons/yellow.png" position="440,1010" size="35,35" alphatest="blend"/>
            <eLabel text="EPG list" position="490,1010" size="200,40" font="Regular;26"
                    foregroundColor="white" backgroundColor="#808000"
                    halign="center" valign="center"/>
            <ePixmap pixmap="buttons/blue.png" position="700,1010" size="35,35" alphatest="blend"/>
            <eLabel text="Settings" position="750,1010" size="200,40" font="Regular;26"
                    foregroundColor="white" backgroundColor="#000080"
                    halign="center" valign="center"/>
        </screen>
    """.format(version=PLUGIN_VERSION)

    def __init__(self, session):
        Screen.__init__(self, session)
        self.session = session

        self["picon"] = Pixmap()
        self["clock"] = Label("")
        self["day"] = Label("")
        self["date"] = Label("")
        self["service_name"] = Label("")
        self["history_list"] = MenuList([])
        self["title"] = Label("")
        self["epg_title"] = Label("")
        self["duration"] = Label("")
        self["rating"] = Label("")
        self["imdb_rating"] = Label("")
        self["genres"] = Label("")
        self["director"] = Label("")
        self["plot"] = Label("")
        self["cast_header"] = Label("")
        self["cast_col1"] = Label("")
        self["cast_col2"] = Label("")
        self["poster"] = Pixmap()
        self["status"] = Label("Ready")

        self.db = get_db()
        self.picon_manager = PiconManager()
        self.channels = []
        self.current_channel = None
        self.current_media_details = None
        self.current_media_type = None
        self._loading_token = 0

        self["actions"] = ActionMap(
            ["OkCancelActions", "ColorActions", "DirectionActions",
             "MenuActions", "InfoActions"],
            {
                "cancel": self.close,
                "red": self.close,
                "green": self.open_stats,
                "yellow": self.open_epg_list,
                "blue": self.open_settings,
                "ok": self.on_ok,
                "up": self.on_up,
                "down": self.on_down,
                "left": self.on_up,
                "right": self.on_down,
                "menu": self.open_settings,
            }, -1)

        self.clock_timer = eTimer()
        self.clock_timer.callback.append(self._update_clock)
        self.clock_timer.start(1000)

        self.onLayoutFinish.append(self.on_start)
        self.onClose.append(self.__onClose)
        # Update check
        self.container = eConsoleAppContainer()
        self.container.appClosed.append(self.command_finished)
        self.container.dataAvail.append(self.version_data_avail)
        self.version_check_in_progress = False
        self.version_buffer = b''
        self.onLayoutFinish.append(self.check_for_updates)

    def __onClose(self):
        try:
            self.clock_timer.stop()
        except Exception:
            pass
        try:
            if "actions" in self:
                self["actions"].destroy()
                del self["actions"]
        except Exception:
            pass

    # ---------- START ----------
    def on_start(self):
        self._update_clock()
        self._show_placeholder()
        print("[CiefpChannelHistory] on_start, current_ref = %s" % self._get_current_ref())
        self._start_timer = eTimer()
        self._start_timer.callback.append(self.refresh_history)
        self._start_timer.start(100, True)  # singleShot=True

    def _update_clock(self):
        now = datetime.now()
        days = ["Monday", "Tuesday", "Wednesday", "Thursday",
                "Friday", "Saturday", "Sunday"]
        months = ["Jan", "Feb", "Mar", "Apr", "May", "Jun",
                  "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
        self["day"].setText(days[now.weekday()])
        self["date"].setText("%d. %s" % (now.day, months[now.month - 1]))
        self["clock"].setText(now.strftime("%H:%M"))

    def _show_placeholder(self):
        px = load_pixmap_safe(PLACEHOLDER)
        if px and self["poster"].instance:
            self["poster"].instance.setPixmap(px)
    # ---------- UPDATE CHECK ----------
    def check_for_updates(self):
        if self.version_check_in_progress:
            return
        self.version_check_in_progress = True
        self["status"].setText("Checking for updates...")
        try:
            self.container.execute("wget -q --timeout=10 -O - %s" % VERSION_URL)
        except Exception as e:
            self.version_check_in_progress = False
            self["status"].setText("Update check failed.")
            print("[CiefpChannelHistory] Update error:", e)

    def version_data_avail(self, data):
        self.version_buffer += data

    def command_finished(self, retval):
        if self.version_check_in_progress:
            self.version_check_closed(retval)
        else:
            self.update_completed(retval)

    def version_check_closed(self, retval):
        self.version_check_in_progress = False
        if retval == 0:
            try:
                remote_version = self.version_buffer.decode().strip()
                self.version_buffer = b''
                print("[CiefpChannelHistory] Local: %s, Remote: %s"
                      % (PLUGIN_VERSION, remote_version))
                if remote_version != PLUGIN_VERSION:
                    self.session.openWithCallback(
                        self.start_update,
                        MessageBox,
                        "New version: v%s\nInstall now?" % remote_version,
                        MessageBox.TYPE_YESNO
                    )
                else:
                    self["status"].setText("The plugin is up to date.")
            except Exception as e:
                self["status"].setText("Version check failed.")
                print("[CiefpChannelHistory] Parse error:", e)
        else:
            self["status"].setText("Update check failed.")

    def start_update(self, answer):
        if not answer:
            self["status"].setText("Update cancelled.")
            return
        self["status"].setText("Updating...")
        self.container.execute(UPDATE_COMMAND)

    def update_completed(self, retval):
        if retval == 0:
            self["status"].setText("Update OK! Restarting...")
            self.container.execute("sleep 2 && killall -9 enigma2")
        else:
            self["status"].setText("Update failed.")

    # ---------- HISTORY LIST ----------
    def refresh_history(self):
        limit = int(config.plugins.ciefpchannelhistory.history_size.value)
        channels = self.db.get_recent_channels(limit=limit)

        current_ref = self._get_current_ref()
        current_name = ""
        current_provider = ""
        current_type = "unknown"
        if current_ref:
            current_name = get_channel_name(current_ref) or ""
            current_provider = get_channel_provider(current_ref) or ""
            current_type = detect_service_type(current_ref)

        # === FILTER ADULT KANALA ===
        try:
            from .components.channel_info import is_parental_locked
            if config.plugins.ciefpchannelhistory.filter_adult.value:
                # Filtriraj iz baze
                channels = [c for c in channels
                            if not is_parental_locked(c.get("ref", ""))]
                # Ako je trenutni kanal adult — ne prikazuj ga na vrhu
                if current_ref and is_parental_locked(current_ref):
                    current_ref = None
                    current_name = ""
                    current_provider = ""
                    current_type = "unknown"
        except Exception as e:
            print("[CiefpChannelHistory] filter adult error:", e)

        # Uvijek pomjeri trenutni kanal na vrh
        if current_ref:
            channels = [c for c in channels if c.get("ref") != current_ref]
            current_entry = {
                "ref": current_ref,
                "name": current_name or "Current channel",
                "provider": current_provider,
                "type": current_type,
                "last_seen": int(time.time()),
                "total_seconds": 0,
                "watch_count": 0,
            }
            channels.insert(0, current_entry)
            channels = channels[:limit]

        self.channels = channels

        if not self.channels:
            self["history_list"].setList(["No history yet. Watch some channels."])
            self["status"].setText("History is empty")
            self.current_channel = None
            return

        items = []
        for idx, ch in enumerate(self.channels):
            name = ch.get("name") or "Unknown"
            prefix = "▶" if idx == 0 else "  "
            items.append("%s %s" % (prefix, name))
        self["history_list"].setList(items)
        self["history_list"].moveToIndex(0)
        self._select_channel(0)

    def _get_current_ref(self):
        """Dohvati trenutni service reference — kao CiefpEPGinfo."""
        try:
            from Screens.InfoBar import InfoBar
            if InfoBar.instance:
                playing = InfoBar.instance.session.nav.getCurrentlyPlayingServiceReference()
                if playing:
                    return playing.toString()
        except Exception as e:
            print("[CiefpChannelHistory] InfoBar ref error:", e)

        try:
            ref = self.session.nav.getCurrentlyPlayingServiceReference()
            if ref:
                return ref.toString()
        except Exception:
            pass

        return None

    def _select_channel(self, idx):
        if getattr(self, "_selecting", False):
            return
        self._selecting = True
        try:
            print("[CiefpChannelHistory] _select_channel idx=%d, total=%d" % (idx, len(self.channels)))
            if idx < 0 or idx >= len(self.channels):
                return

            self.current_channel = self.channels[idx]
            ref = self.current_channel.get("ref")
            name = self.current_channel.get("name") or "Unknown"

            self["service_name"].setText(name)
            self._load_picon(ref, name)

            self["title"].setText(name)
            self["epg_title"].setText("")
            self["duration"].setText("")
            self["rating"].setText("")
            self["imdb_rating"].setText("")
            self["genres"].setText("")
            self["director"].setText("")
            self["plot"].setText("")
            self["cast_header"].setText("")
            self["cast_col1"].setText("")
            self["cast_col2"].setText("")
            self._show_placeholder()

            self._load_epg_for_ref(ref)
        finally:
            self._selecting = False

    def _load_picon(self, ref, name):
        try:
            if not ref:
                self["picon"].hide()
                return
            p = self.picon_manager.find_picon(ref, name)
            if p:
                px = load_pixmap_safe(p)
                if px and self["picon"].instance:
                    self["picon"].instance.setPixmap(px)
                    self["picon"].show()
                    return
            self["picon"].hide()
        except Exception as e:
            print("[CiefpChannelHistory] picon error:", e)
            try:
                self["picon"].hide()
            except Exception:
                pass

    # ---------- EPG ----------
    def _load_epg_for_ref(self, ref_str):
        events = get_epg_for_ref(ref_str, max_items=10)
        if not events:
            self["status"].setText("No EPG for this channel")
            self["epg_title"].setText("No EPG data")
            return

        cur = events[0]
        name = cur.get("name", "")
        short = cur.get("short", "")
        ext = cur.get("ext", "")
        desc = (short + " " + ext).strip()

        self["epg_title"].setText("EPG: " + name)
        if cur.get("duration"):
            minutes = int(cur["duration"]) // 60
            self["duration"].setText("Duration: %d min" % minutes)

        year = None
        m = re.search(r"\b(19|20)\d{2}\b", name + " " + desc)
        if m:
            year = int(m.group(0))

        title = re.sub(r"\s*\[.*?\]|\s*\(.*?\)|\s*-\s*.+$", "", name).strip()
        title = re.sub(r"^Film[:\-]?\s*|^Movie[:\-]?\s*", "",
                       title, flags=re.I).strip()
        if title:
            self["title"].setText(title)

        if desc:
            if len(desc) > 700:
                cut = desc[:700].rfind(". ")
                if cut > 400:
                    desc = desc[:cut + 1] + " ..."
                else:
                    desc = desc[:700] + " ..."
            self["plot"].setText("Plot:\n" + desc)

        api_key = config.plugins.ciefpchannelhistory.tmdb_api_key.value.strip()
        if api_key and not is_generic_title(title):
            self._loading_token += 1
            token = self._loading_token
            self["status"].setText("Searching TMDB: %s" % title)
            threading.Thread(
                target=self._fetch_tmdb_async,
                args=(token, title, year, api_key),
                daemon=True
            ).start()
        else:
            self["status"].setText("EPG only")

    def _fetch_tmdb_async(self, token, title, year, api_key):
        try:
            result, media_type = tmdb_search_multi(title, year, api_key)
            if not result:
                return
            media_id = result.get("id")
            details = tmdb_details(media_id, media_type, api_key)
            if not details:
                return
            if token != self._loading_token:
                return
            self.current_media_details = details
            self.current_media_type = media_type
            self._update_ui_with_tmdb(token, details, media_type)
        except Exception as e:
            print("[CiefpChannelHistory] tmdb async error:", e)

    def _update_ui_with_tmdb(self, token, details, media_type):
        if token != self._loading_token:
            return

        title = details.get("title") if media_type == "movie" else details.get("name", "")
        year = (details.get("release_date") or "")[:4] if media_type == "movie" else \
               (details.get("first_air_date") or "")[:4]
        self["title"].setText(title + ((" (%s)" % year) if year else ""))

        if media_type == "movie":
            rt = details.get("runtime")
            if rt:
                self["duration"].setText("Duration: %d min" % rt)
        else:
            ert = details.get("episode_run_time")
            if ert and isinstance(ert, list) and ert:
                self["duration"].setText("Duration: ~%d min/ep" % ert[0])

        vote = details.get("vote_average", 0)
        self["rating"].setText("TMDB: %.1f/10 ★" % vote if vote else "TMDB: N/A")

        if (config.plugins.ciefpchannelhistory.show_imdb_rating.value and
                config.plugins.ciefpchannelhistory.omdb_api_key.value.strip()):
            self["imdb_rating"].setText("IMDB: Loading...")
            threading.Thread(
                target=self._fetch_imdb_async,
                args=(token, details, media_type),
                daemon=True
            ).start()

        genres = [g["name"] for g in details.get("genres", [])]
        self["genres"].setText("Genres: " + (", ".join(genres) if genres else "N/A"))

        credits = details.get("credits", {})
        crew = credits.get("crew", [])
        directors = [c["name"] for c in crew if c.get("job") == "Director"]
        if media_type == "tv":
            creators = [c["name"] for c in details.get("created_by", [])]
            if creators:
                self["director"].setText("Created by: " + ", ".join(creators[:3]))
            elif directors:
                self["director"].setText("Director: " + ", ".join(directors[:3]))
        else:
            if directors:
                self["director"].setText("Director: " + ", ".join(directors[:3]))

        overview = (details.get("overview") or "").strip()
        if overview:
            if len(overview) > 700:
                cut = overview[:700].rfind(". ")
                if cut > 400:
                    overview = overview[:cut + 1] + " ..."
                else:
                    overview = overview[:700] + " ..."
            self["plot"].setText("Plot:\n" + overview)

        cast = credits.get("cast", [])[:10]
        if cast:
            self["cast_header"].setText("Cast:")

            def fmt(a):
                name = a.get("name", "").strip()
                char = a.get("character", "").strip()
                if len(char) > 30:
                    char = char[:30] + "…"
                return "• %s as %s" % (name, char) if char else "• %s" % name

            self["cast_col1"].setText("\n".join([fmt(a) for a in cast[:5]]))
            self["cast_col2"].setText("\n".join([fmt(a) for a in cast[5:10]]))

        media_id = details.get("id")
        poster_path = details.get("poster_path")
        if poster_path and media_id:
            self._download_poster_async(token, poster_path, media_id, media_type)
        else:
            self._show_placeholder()

    def _fetch_imdb_async(self, token, details, media_type):
        try:
            rating = omdb_rating(
                details, media_type,
                config.plugins.ciefpchannelhistory.omdb_api_key.value)
            if token != self._loading_token:
                return
            if rating:
                self["imdb_rating"].setText("IMDB: %s/10 ★" % rating)
            else:
                self["imdb_rating"].setText("IMDB: N/A")
        except Exception:
            pass

    def _download_poster_async(self, token, poster_path, media_id, media_type):
        if not config.plugins.ciefpchannelhistory.cache_enabled.value:
            self._show_placeholder()
            return

        def worker():
            try:
                folder = config.plugins.ciefpchannelhistory.cache_folder.value
                ensure_folder(folder)
                fname = os.path.join(
                    folder,
                    "poster_%s_%s_%s" % (media_type, media_id,
                                         os.path.basename(poster_path)))
                if not os.path.exists(fname):
                    url = "https://image.tmdb.org/t/p/w500" + poster_path
                    ctx = ssl.create_default_context()
                    ctx.check_hostname = False
                    ctx.verify_mode = ssl.CERT_NONE
                    data = urllib.request.urlopen(url, context=ctx, timeout=12).read()
                    with open(fname, "wb") as f:
                        f.write(data)
                if token != self._loading_token:
                    return
                px = load_pixmap_safe(fname)
                if px and self["poster"].instance:
                    self["poster"].instance.setPixmap(px)
            except Exception as e:
                print("[CiefpChannelHistory] poster error:", e)

        threading.Thread(target=worker, daemon=True).start()

    # ---------- ACTIONS ----------
    def on_up(self):
        try:
            cur = self["history_list"].getSelectedIndex()
            if cur > 0:
                self["history_list"].up()
                new_idx = self["history_list"].getSelectedIndex()
                if new_idx != cur:
                    self._select_channel(new_idx)
        except Exception as e:
            print("[CiefpChannelHistory] on_up error:", e)

    def on_down(self):
        try:
            cur = self["history_list"].getSelectedIndex()
            if cur < len(self.channels) - 1:
                self["history_list"].down()
                new_idx = self["history_list"].getSelectedIndex()
                if new_idx != cur:
                    self._select_channel(new_idx)
        except Exception as e:
            print("[CiefpChannelHistory] on_down error:", e)

    def on_ok(self):
        """Prebaci na selektovani kanal."""
        if not self.current_channel:
            return
        ref_str = self.current_channel.get("ref")
        if not ref_str:
            return
        try:
            ref = eServiceReference(ref_str)
            from Screens.InfoBar import InfoBar
            if InfoBar and InfoBar.instance:
                InfoBar.instance.session.nav.playService(ref)
                self["status"].setText("Switched to %s" %
                                       (self.current_channel.get("name") or ""))
        except Exception as e:
            print("[CiefpChannelHistory] switch error:", e)
            self["status"].setText("Switch failed")

    def open_stats(self):
        self.session.open(StatsScreen)

    def open_epg_list(self):
        """Žuto — otvori FHD EPG Info ekran za trenutni kanal."""
        if not self.current_channel:
            self.session.open(MessageBox, "No channel selected",
                              MessageBox.TYPE_INFO, timeout=3)
            return
        ref = self.current_channel.get("ref")
        name = self.current_channel.get("name") or "Unknown"
        self.session.open(EPGListScreen, ref, name)

    def open_settings(self):
        self.session.openWithCallback(self._after_settings, SettingsScreen)

    def _after_settings(self, *args):
        self.refresh_history()


# ---------- STATS SCREEN ----------
class StatsScreen(Screen):
    skin = """
        <screen name="CiefpChannelHistoryStats" position="0,0" size="1920,1080"
                backgroundColor="#011a2e" title="..:: CiefpChannelHistory Statistics ::..">

            <widget name="header" position="40,30" size="1840,60" font="Regular;42"
                    foregroundColor="#00BFFF" backgroundColor="#011a2e"
                    transparent="1" halign="left"/>

            <widget name="menu" position="40,120" size="500,830"
                    scrollbarMode="showOnDemand" itemHeight="50"
                    font="Regular;28" backgroundColor="#011a2e"/>

            <widget name="content" position="580,120" size="1300,830"
                    font="Regular;26" foregroundColor="#FFFFFF"
                    backgroundColor="#011a2e" transparent="1" valign="top"/>

            <widget name="status" position="40,970" size="1840,40" font="Regular;22"
                    foregroundColor="#00FF00" backgroundColor="#011a2e"
                    transparent="1" halign="left"/>

            <ePixmap pixmap="buttons/red.png" position="0,1010" size="35,35" alphatest="blend"/>
            <eLabel text="Exit" position="50,1010" size="200,40" font="Regular;26"
                    foregroundColor="white" backgroundColor="#800000"
                    halign="center" valign="center"/>
            <ePixmap pixmap="buttons/green.png" position="260,1010" size="35,35" alphatest="blend"/>
            <eLabel text="Refresh" position="310,1010" size="200,40" font="Regular;26"
                    foregroundColor="white" backgroundColor="#008000"
                    halign="center" valign="center"/>
        </screen>
    """

    def __init__(self, session):
        Screen.__init__(self, session)
        self.session = session
        self.db = get_db()

        self["header"] = Label("Channel History Statistics")
        self["menu"] = MenuList([])
        self["content"] = Label("")
        self["status"] = Label("")

        self["actions"] = ActionMap(
            ["OkCancelActions", "ColorActions", "DirectionActions"],
            {
                "cancel": self.close,
                "red": self.close,
                "green": self.refresh,
                "ok": self.on_ok,
                "up": self.on_up,
                "down": self.on_down,
                "left": self.on_up,
                "right": self.on_down,
            }, -1)

        self.categories = [
            "Overview",
            "Top channels",
            "By service type",
            "By satellite",         # NOVO
            "By encryption",        # NOVO
            "By hour of day",
            "By weekday",
            "Currently typical",
        ]
        self.onLayoutFinish.append(self.refresh)

    def refresh(self):
        self["menu"].setList(self.categories)
        self["menu"].moveToIndex(0)
        self.show_category(0)
        self["status"].setText("Data from local database")

    def on_up(self):
        try:
            cur = self["menu"].getSelectedIndex()
            if cur > 0:
                self["menu"].up()
                new_idx = self["menu"].getSelectedIndex()
                if new_idx != cur:
                    self.show_category(new_idx)
        except Exception as e:
            print("[CiefpChannelHistory] Stats on_up error:", e)

    def on_down(self):
        try:
            cur = self["menu"].getSelectedIndex()
            if cur < len(self.categories) - 1:
                self["menu"].down()
                new_idx = self["menu"].getSelectedIndex()
                if new_idx != cur:
                    self.show_category(new_idx)
        except Exception as e:
            print("[CiefpChannelHistory] Stats on_down error:", e)

    def on_ok(self):
        self.show_category(self["menu"].getSelectedIndex())

    def show_category(self, idx):
        name = self.categories[idx] if 0 <= idx < len(self.categories) else ""
        if name == "Overview":
            self._show_overview()
        elif name == "Top channels":
            self._show_top_channels()
        elif name == "By service type":
            self._show_by_type()
        elif name == "By satellite":
            self._show_by_satellite()
        elif name == "By encryption":
            self._show_by_encryption()
        elif name == "By hour of day":
            self._show_by_hour()
        elif name == "By weekday":
            self._show_by_weekday()
        elif name == "Currently typical":
            self._show_typical()

    def _show_overview(self):
        s = self.db.get_stats_overview()
        lines = []
        lines.append("Overall:")
        lines.append("  Channels:        %d" % s["channels"])
        lines.append("  Sessions:        %d" % s["sessions"])
        lines.append("  Total watch time: %s" % format_duration(s["total_seconds"]))
        if s["sessions"] > 0:
            avg = s["total_seconds"] // max(1, s["sessions"])
            lines.append("  Average session:  %s" % format_duration(avg))
        self["content"].setText("\n".join(lines))

    def _show_top_channels(self):
        top = self.db.get_top_channels(20)
        if not top:
            self["content"].setText("No data.")
            return
        total = sum(c["total_seconds"] for c in top) or 1
        lines = ["TOP 20 CHANNELS", "-" * 88]
        for i, ch in enumerate(top, 1):
            name = (ch.get("name") or "Unknown")[:28]
            sec = ch["total_seconds"]
            pct = 100.0 * sec / total
            bar = format_bar(pct, width=12)

            # Satelit
            sat_pos = ch.get("satellite_pos") or ""
            if sat_pos:
                sat_str = sat_pos[:7]
            else:
                sat_str = ""

            # CAID
            caid = ch.get("caid") or ""
            caid_str = caid if caid else "FTA"

            # Format: broj | ime | trajanje | watch | satelit | caid | bar | pct
            lines.append("%2d. %-20s %8s %4s %7s %5s %s %5.1f%%" %
                         (i, name, format_duration(sec),
                          "%dx" % (ch.get("watch_count") or 0),
                          sat_str, caid_str, bar, pct))
        self["content"].setText("\n".join(lines))

    def _show_by_type(self):
        rows = self.db.get_stats_by_type()
        if not rows:
            self["content"].setText("No data.")
            return
        total = sum(r["total"] for r in rows) or 1
        lines = ["BY SERVICE TYPE", "─" * 60]
        for r in rows:
            t = (r.get("type") or "unknown").upper()
            sec = r["total"]
            pct = 100.0 * sec / total
            bar = format_bar(pct)
            lines.append("%-14s %10s  %s %5.1f%%  (%d channels)" %
                         (t, format_duration(sec), bar, pct, r["cnt"]))
        self["content"].setText("\n".join(lines))

    def _show_by_satellite(self):
        rows = self.db.get_stats_by_satellite()
        if not rows:
            self["content"].setText("No satellite data yet.\n\n"
                                    "Watch some DVB-S channels to collect data.")
            return
        total = sum(r["total"] for r in rows) or 1
        lines = ["BY SATELLITE", "-" * 60]
        for r in rows:
            pos = r.get("satellite_pos") or "?"
            name = r.get("satellite") or ""
            label = "%s (%s)" % (pos, name) if name else pos
            sec = r["total"]
            pct = 100.0 * sec / total
            bar = format_bar(pct)
            lines.append("%-28s %10s  %s %5.1f%%  (%d ch)" %
                         (label[:28], format_duration(sec), bar, pct, r["cnt"]))
        self["content"].setText("\n".join(lines))

    def _show_by_encryption(self):
        rows = self.db.get_stats_by_encryption()
        if not rows:
            self["content"].setText("No encryption data yet.")
            return
        total = sum(r["total"] for r in rows) or 1
        lines = ["BY ENCRYPTION", "-" * 60]
        for r in rows:
            caid = r.get("caid") or ""
            caid_name = r.get("caid_name") or ""
            if not caid:
                label = "FTA (nekriptovano)"
            elif caid_name:
                label = "%s (%s)" % (caid_name, caid)
            else:
                label = "CAID %s" % caid
            sec = r["total"]
            pct = 100.0 * sec / total
            bar = format_bar(pct)
            lines.append("%-28s %10s  %s %5.1f%%  (%d ch)" %
                         (label[:28], format_duration(sec), bar, pct, r["cnt"]))
        self["content"].setText("\n".join(lines))

    def _show_by_hour(self):
        rows = self.db.get_stats_by_hour()
        if not rows:
            self["content"].setText("No data.")
            return
        total = sum(r["total"] for r in rows) or 1
        by_hour = {r["hour"]: r["total"] for r in rows}
        lines = ["BY HOUR OF DAY (most watched)", "─" * 60]
        sorted_hours = sorted(by_hour.items(), key=lambda x: x[1], reverse=True)[:10]
        for hour, sec in sorted_hours:
            pct = 100.0 * sec / total
            bar = format_bar(pct)
            lines.append("%02d:00-%02d:00   %10s  %s %5.1f%%" %
                         (hour, hour + 1, format_duration(sec), bar, pct))
        self["content"].setText("\n".join(lines))

    def _show_by_weekday(self):
        rows = self.db.get_stats_by_weekday()
        if not rows:
            self["content"].setText("No data.")
            return
        total = sum(r["total"] for r in rows) or 1
        days = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"]
        by_wd = {r["wd"]: r["total"] for r in rows}
        lines = ["BY DAY OF WEEK", "─" * 60]
        for wd in range(7):
            sec = by_wd.get(wd, 0)
            pct = 100.0 * sec / total
            bar = format_bar(pct)
            lines.append("%-4s  %10s  %s %5.1f%%" %
                         (days[wd], format_duration(sec), bar, pct))
        self["content"].setText("\n".join(lines))

    def _show_typical(self):
        ref = self.db.get_typical_channel_for_now()
        if not ref:
            self["content"].setText("Not enough data for this time slot.")
            return
        name = get_channel_name(ref) or "Unknown"
        self["content"].setText(
            "MOST WATCHED AT THIS TIME OF DAY:\n\n"
            "  %s\n\n"
            "Reference: %s" % (name, ref))

# ---------- SETTINGS SCREEN ----------
class SettingsScreen(Screen):
    skin = """
        <screen name="CiefpChannelHistorySettings" position="center,center"
                size="1400,900" title="..:: CiefpChannelHistory Settings ::.."
                backgroundColor="#011a2e">
            <widget name="menu" position="50,50" size="1300,750"
                    scrollbarMode="showOnDemand" itemHeight="44"
                    font="Regular;24" backgroundColor="#011a2e"/>
            <widget name="status" position="50,810" size="1300,40" font="Regular;24"
                    foregroundColor="#00FF00" backgroundColor="#011a2e"/>
            <ePixmap pixmap="buttons/red.png" position="0,860" size="35,35" alphatest="blend"/>
            <eLabel text="Cancel" position="50,850" size="200,50" font="Regular;26"
                    foregroundColor="white" backgroundColor="#800000"
                    halign="center" valign="center"/>
            <ePixmap pixmap="buttons/green.png" position="260,860" size="35,35" alphatest="blend"/>
            <eLabel text="Save" position="310,850" size="200,50" font="Regular;26"
                    foregroundColor="white" backgroundColor="#008000"
                    halign="center" valign="center"/>
        </screen>
    """

    def __init__(self, session):
        Screen.__init__(self, session)
        self.session = session
        self["menu"] = MenuList([])
        self["status"] = Label("Settings")
        self["actions"] = ActionMap(
            ["OkCancelActions", "ColorActions"],
            {
                "cancel": self.close,
                "red": self.close,
                "green": self.save_all,
                "ok": self.on_ok,
            }, -1)
        self.onLayoutFinish.append(self.build_menu)

    # ---------- BUILD MENU ----------
    def build_menu(self):
        db_folder = config.plugins.ciefpchannelhistory.db_folder.value
        hist = int(config.plugins.ciefpchannelhistory.history_size.value)
        minw = int(config.plugins.ciefpchannelhistory.min_watch.value)
        deb = int(config.plugins.ciefpchannelhistory.debounce.value)

        # Retention
        retention = config.plugins.ciefpchannelhistory.history_retention.value
        retention_map = {
            "0": "Forever",
            "30": "30 days",
            "60": "60 days",
            "90": "90 days",
            "180": "180 days",
            "365": "1 year",
        }
        retention_str = retention_map.get(retention, retention)
        # Filter adult
        filter_adult = "YES" if config.plugins.ciefpchannelhistory.filter_adult.value else "NO"

        # API keys
        tmdb = "SET" if config.plugins.ciefpchannelhistory.tmdb_api_key.value else "NOT SET"
        omdb = "SET" if config.plugins.ciefpchannelhistory.omdb_api_key.value else "NOT SET"
        groq = "SET" if config.plugins.ciefpchannelhistory.groq_api_key.value else "NOT SET"

        # Toggles
        cache_on = "YES" if config.plugins.ciefpchannelhistory.cache_enabled.value else "NO"
        imdb_on = "YES" if config.plugins.ciefpchannelhistory.show_imdb_rating.value else "NO"

        # Language
        lang_code = config.plugins.ciefpchannelhistory.language.value
        lang_map = {
            "en-US": "English", "sr-RS": "Srpski", "hr-HR": "Hrvatski",
            "bs-BA": "Bosanski", "de-DE": "Deutsch", "fr-FR": "Français",
            "es-ES": "Español", "it-IT": "Italiano", "ru-RU": "Русский",
        }
        lang = lang_map.get(lang_code, lang_code)

        # DB stats
        s = self.db_stats()
        first_seen_str = ""
        if s.get("first_seen", 0) > 0:
            try:
                first_seen_str = datetime.fromtimestamp(s["first_seen"]).strftime("%d.%m.%Y")
            except Exception:
                first_seen_str = "?"

        items = [
            "=== GENERAL ===",
            "DB folder:            %s" % db_folder,
            "History size:         %d" % hist,
            "Min watch time (s):   %d" % minw,
            "Debounce (s):         %d" % deb,
            "History retention:    %s" % retention_str,
            "Filter Adult (parental): %s" % filter_adult,
            "=== API KEYS ===",
            "TMDB API Key:         %s" % tmdb,
            "OMDb API Key:         %s" % omdb,
            "GROQ API Key:         %s" % groq,
            "=== DISPLAY ===",
            "Show IMDB rating:     %s" % imdb_on,
            "Download posters:     %s" % cache_on,
            "Language:             %s" % lang,
            "=== DATABASE ===",
            "Stats: %d channels, %d sessions, %s" % (
                s["channels"], s["sessions"], format_duration(s["total_seconds"])),
            "Tracking since:       %s" % (first_seen_str or "N/A"),
            ">>> CLEANUP OLD SESSIONS (OK) <<<",
            ">>> CLEAR CACHE (OK) <<<",
            ">>> CLEAR ALL HISTORY (OK) <<<",
            "=== UPDATE ===",
            ">>> Manual Update (OK) <<<",
        ]
        self["menu"].setList(items)

    def db_stats(self):
        try:
            return get_db().get_stats_overview()
        except Exception:
            return {"channels": 0, "sessions": 0, "total_seconds": 0, "first_seen": 0}

    # ---------- OK HANDLER ----------
    def on_ok(self):
        idx = self["menu"].getSelectedIndex()
        if idx == 1:
            self._cycle_db_folder()
        elif idx == 2:
            self._edit_number("history_size", "History size (10-50)", 10, 50)
        elif idx == 3:
            self._edit_number("min_watch", "Min watch time in seconds (5-300)", 5, 300)
        elif idx == 4:
            self._edit_number("debounce", "Debounce in seconds (3-60)", 3, 60)
        elif idx == 5:
            self._cycle_retention()
        elif idx == 6:
            config.plugins.ciefpchannelhistory.filter_adult.value = \
                not config.plugins.ciefpchannelhistory.filter_adult.value
            self.build_menu()
        elif idx == 8:
            self._edit_key("tmdb_api_key", "TMDB API Key")
        elif idx == 9:
            self._edit_key("omdb_api_key", "OMDb API Key")
        elif idx == 10:
            self._edit_key("groq_api_key", "GROQ API Key")
        elif idx == 12:
            config.plugins.ciefpchannelhistory.show_imdb_rating.value = \
                not config.plugins.ciefpchannelhistory.show_imdb_rating.value
            self.build_menu()
        elif idx == 13:
            config.plugins.ciefpchannelhistory.cache_enabled.value = \
                not config.plugins.ciefpchannelhistory.cache_enabled.value
            self.build_menu()
        elif idx == 14:
            self._cycle_language()
        elif idx == 18:
            self._cleanup_now()
        elif idx == 19:
            self._clear_cache()
        elif idx == 20:
            self._clear_history()
        elif idx == 22:
            self._manual_update()
    # ---------- DB FOLDER ----------
    def _cycle_db_folder(self):
        """Ciklus kroz choices za db_folder."""
        choices = [
            "/media/hdd/CiefpChannelHistory/",
            "/media/usb/CiefpChannelHistory/",
            "/tmp/CiefpChannelHistory/",
        ]
        cur = config.plugins.ciefpchannelhistory.db_folder.value
        try:
            i = choices.index(cur)
        except ValueError:
            i = 0
        nxt = choices[(i + 1) % len(choices)]
        config.plugins.ciefpchannelhistory.db_folder.value = nxt
        config.plugins.ciefpchannelhistory.db_folder.save()
        configfile.save()
        self["status"].setText("DB folder: %s (restart needed)" % nxt)
        self.build_menu()

    # ---------- RETENTION ----------
    def _cycle_retention(self):
        """Ciklus kroz retention choices."""
        order = ["30", "60", "90", "180", "365", "0"]
        names = {
            "30": "30 days", "60": "60 days", "90": "90 days",
            "180": "180 days", "365": "1 year", "0": "Forever",
        }
        cur = config.plugins.ciefpchannelhistory.history_retention.value
        try:
            i = order.index(cur)
        except ValueError:
            i = 0
        nxt = order[(i + 1) % len(order)]
        config.plugins.ciefpchannelhistory.history_retention.value = nxt
        config.plugins.ciefpchannelhistory.history_retention.save()
        configfile.save()
        self["status"].setText("Retention: %s" % names.get(nxt, nxt))
        self.build_menu()

    # ---------- LANGUAGE ----------
    def _cycle_language(self):
        """Ciklus kroz listu jezika."""
        lang_order = [
            "en-US", "sr-RS", "hr-HR", "bs-BA", "de-DE",
            "fr-FR", "es-ES", "it-IT", "ru-RU",
        ]
        lang_names = {
            "en-US": "English", "sr-RS": "Srpski", "hr-HR": "Hrvatski",
            "bs-BA": "Bosanski", "de-DE": "Deutsch", "fr-FR": "Français",
            "es-ES": "Español", "it-IT": "Italiano", "ru-RU": "Русский",
        }
        cur = config.plugins.ciefpchannelhistory.language.value
        try:
            i = lang_order.index(cur)
        except ValueError:
            i = 0
        nxt = lang_order[(i + 1) % len(lang_order)]
        config.plugins.ciefpchannelhistory.language.value = nxt
        config.plugins.ciefpchannelhistory.language.save()
        configfile.save()
        self["status"].setText("Language: %s" % lang_names.get(nxt, nxt))
        self.build_menu()

    # ---------- EDIT NUMBER ----------
    def _edit_number(self, attr, title, lo, hi):
        cfg = getattr(config.plugins.ciefpchannelhistory, attr)
        def cb(res):
            if res is None:
                return
            try:
                v = int(res.strip())
                if v < lo:
                    v = lo
                if v > hi:
                    v = hi
                cfg.value = v
                cfg.save()
                configfile.save()
                self["status"].setText("%s = %d" % (title, v))
                self.build_menu()
            except ValueError:
                self["status"].setText("Invalid number")
        self.session.openWithCallback(
            cb, VirtualKeyBoard, title=title, text=str(cfg.value))

    # ---------- EDIT KEY ----------
    def _edit_key(self, attr, title):
        cfg = getattr(config.plugins.ciefpchannelhistory, attr)
        def cb(res):
            if res is None:
                return
            cfg.value = res.strip()
            cfg.save()
            configfile.save()
            # Sačuvaj i u txt fajl
            if attr == "tmdb_api_key":
                _save_key_to_file(TMDB_API_KEY_FILE, res)
            elif attr == "omdb_api_key":
                _save_key_to_file(OMDB_API_KEY_FILE, res)
            elif attr == "groq_api_key":
                _save_key_to_file(GROQ_API_KEY_FILE, res)
            self["status"].setText("%s saved" % title)
            self.build_menu()
        self.session.openWithCallback(
            cb, VirtualKeyBoard, title=title, text=cfg.value)

    # ---------- CLEANUP ----------
    def _cleanup_now(self):
        """Obriši sesije starije od retention dana."""
        retention = config.plugins.ciefpchannelhistory.history_retention.value
        if retention == "0":
            self["status"].setText("Retention is Forever — nothing to cleanup")
            return
        days = int(retention)
        msg = ("Delete sessions older than %d days?\n\n"
               "This will keep statistics for the last %d days." % (days, days))

        def confirm(res):
            if not res:
                return
            try:
                deleted = get_db().cleanup_old_sessions(days)
                self["status"].setText("Deleted %d old sessions" % deleted)
                self.build_menu()
            except Exception as e:
                self["status"].setText("Error: %s" % e)

        self.session.openWithCallback(
            confirm, MessageBox, msg, MessageBox.TYPE_YESNO)

    # ---------- CLEAR CACHE ----------
    def _clear_cache(self):
        def confirm(res):
            if not res:
                return
            folder = config.plugins.ciefpchannelhistory.cache_folder.value
            count = 0
            if os.path.isdir(folder):
                for fn in os.listdir(folder):
                    if fn.lower().endswith((".png", ".jpg", ".jpeg")):
                        try:
                            os.remove(os.path.join(folder, fn))
                            count += 1
                        except Exception:
                            pass
            self["status"].setText("Deleted %d cached images" % count)
        self.session.openWithCallback(
            confirm, MessageBox,
            "Delete all cached images?", MessageBox.TYPE_YESNO)

    # ---------- CLEAR HISTORY ----------
    def _clear_history(self):
        def confirm(res):
            if not res:
                return
            ok = get_db().clear_all()
            self["status"].setText("History cleared" if ok else "Error")
            self.build_menu()
        self.session.openWithCallback(
            confirm, MessageBox,
            "Delete ALL watch history? This cannot be undone!",
            MessageBox.TYPE_YESNO)

    # ---------- MANUAL UPDATE ----------
    def _manual_update(self):
        def confirm(res):
            if not res:
                return
            self["status"].setText("Updating... please wait")
            os.system(UPDATE_COMMAND)
        self.session.openWithCallback(
            confirm, MessageBox,
            "Check for updates and reinstall?",
            MessageBox.TYPE_YESNO)

    # ---------- SAVE ALL ----------
    def save_all(self):
        try:
            config.plugins.ciefpchannelhistory.history_size.save()
            config.plugins.ciefpchannelhistory.min_watch.save()
            config.plugins.ciefpchannelhistory.debounce.save()
            config.plugins.ciefpchannelhistory.history_retention.save()
            config.plugins.ciefpchannelhistory.filter_adult.save()
            config.plugins.ciefpchannelhistory.tmdb_api_key.save()
            config.plugins.ciefpchannelhistory.omdb_api_key.save()
            config.plugins.ciefpchannelhistory.groq_api_key.save()
            config.plugins.ciefpchannelhistory.cache_enabled.save()
            config.plugins.ciefpchannelhistory.show_imdb_rating.save()
            config.plugins.ciefpchannelhistory.language.save()
            config.plugins.ciefpchannelhistory.db_folder.save()
            configfile.save()
            self["status"].setText("All settings saved")
        except Exception as e:
            self["status"].setText("Error: %s" % e)

# ---------- SESSIONSTART HOOK ----------
def sessionstart(reason, **kwargs):
    if reason == 0:  # start
        try:
            # Reload parental cache
            try:
                from .components.channel_info import reload_parental_cache
                reload_parental_cache()
            except Exception as e:
                print("[CiefpChannelHistory] parental reload error:", e)

            # Cleanup starih sesija
            try:
                days = int(config.plugins.ciefpchannelhistory.history_retention.value)
                if days > 0:
                    db = get_db()
                    deleted = db.cleanup_old_sessions(days)
                    if deleted > 0:
                        print("[CiefpChannelHistory] Cleaned up %d old sessions" % deleted)
            except Exception as e:
                print("[CiefpChannelHistory] cleanup error:", e)

            # Start tracker
            tracker = get_or_create_tracker()
            tracker.start()
            print("[CiefpChannelHistory] Tracker started at sessionstart")
        except Exception as e:
            print("[CiefpChannelHistory] sessionstart error:", e)

    elif reason == 1:  # stop
        try:
            t = get_tracker()
            if t:
                t.commit_now()
                t.stop()
        except Exception:
            pass
# ---------- INIT ----------
load_all_api_keys()


# ---------- MAIN ENTRY ----------
def main(session, **kwargs):
    try:
        tracker = get_or_create_tracker()
        install_hook(tracker)
    except Exception as e:
        print("[CiefpChannelHistory] main install error:", e)
    session.open(CiefpChannelHistoryMain)


def Plugins(**kwargs):
    icon = PLUGIN_ICON if os.path.exists(PLUGIN_ICON) else None
    return [
        PluginDescriptor(
            name="%s v%s" % (PLUGIN_NAME, PLUGIN_VERSION),
            description=PLUGIN_DESC,
            icon=icon,
            where=PluginDescriptor.WHERE_PLUGINMENU,
            fnc=main
        ),
        PluginDescriptor(
            name="%s v%s" % (PLUGIN_NAME, PLUGIN_VERSION),
            where=PluginDescriptor.WHERE_SESSIONSTART,
            fnc=sessionstart
        ),
    ]