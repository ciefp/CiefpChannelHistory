# -*- coding: utf-8 -*-
#
# CiefpChannelHistory - EPGListScreen (FHD EPG Info)
#
import os
import re
import ssl
import time
import threading
import subprocess
import urllib.request

from Components.Pixmap import Pixmap
from Components.ActionMap import ActionMap
from Components.Label import Label
from Components.MenuList import MenuList
from Screens.Screen import Screen
from Screens.MessageBox import MessageBox
from Screens.ChoiceBox import ChoiceBox
from enigma import eTimer, eServiceReference
from Tools.LoadPixmap import LoadPixmap

from Components.config import config

from ..picon_manager import PiconManager
from ..epg_reader import get_epg_for_ref
from ..tmdb_client import (tmdb_search_multi, tmdb_details, omdb_rating,
                           tmdb_trailer, tmdb_search_person, tmdb_person_details,
                           is_generic_title)
from ..utils import ensure_folder, load_pixmap_safe
from ..channel_info import get_channel_name  # za filmografiju


PLUGIN_DIR = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
PLACEHOLDER = os.path.join(PLUGIN_DIR, "placeholder.png")


class EPGListScreen(Screen):
    """FHD EPG Info ekran — lista EPG događaja + detalji + TMDB + cast."""

    skin = """
        <screen name="CiefpChannelHistoryEPGList" position="0,0" size="1920,1080"
                backgroundColor="#011a2e" title="..:: EPG Info ::..">

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

            <widget name="epg_list" position="30,260" size="610,720"
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

            <ePixmap pixmap="buttons/red.png" position="0,1010" size="35,35" alphatest="blend"/>
            <eLabel text="Exit" position="50,1010" size="180,40" font="Regular;26"
                    foregroundColor="white" backgroundColor="#800000"
                    halign="center" valign="center"/>
            <ePixmap pixmap="buttons/green.png" position="240,1010" size="35,35" alphatest="blend"/>
            <eLabel text="Filmography" position="290,1010" size="180,40" font="Regular;26"
                    foregroundColor="white" backgroundColor="#008000"
                    halign="center" valign="center"/>
            <ePixmap pixmap="buttons/yellow.png" position="480,1010" size="35,35" alphatest="blend"/>
            <eLabel text="Cast explore" position="530,1010" size="220,40" font="Regular;26"
                    foregroundColor="white" backgroundColor="#808000"
                    halign="center" valign="center"/>
            <ePixmap pixmap="buttons/blue.png" position="760,1010" size="35,35" alphatest="blend"/>
            <eLabel text="Trailer" position="810,1010" size="180,40" font="Regular;26"
                    foregroundColor="white" backgroundColor="#000080"
                    halign="center" valign="center"/>
        </screen>
    """

    def __init__(self, session, channel_ref, channel_name):
        Screen.__init__(self, session)
        self.session = session
        self.channel_ref = channel_ref
        self.channel_name = channel_name or "Unknown"

        self["picon"] = Pixmap()
        self["clock"] = Label("")
        self["day"] = Label("")
        self["date"] = Label("")
        self["service_name"] = Label(self.channel_name)
        self["epg_list"] = MenuList([])
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
        self["status"] = Label("Loading EPG...")

        self.epg_events = []
        self.current_event = None
        self.current_media_details = None
        self.current_media_type = None
        self.current_trailer_id = None
        self._loading_token = 0
        self._saved_media_state = None
        self.current_person_details = None

        self["actions"] = ActionMap(
            ["OkCancelActions", "ColorActions", "DirectionActions", "InfoActions"],
            {
                "cancel": self.close,
                "red": self.close,
                "green": self.filmography_browser,
                "yellow": self.cast_explore,
                "blue": self.show_trailer,
                "ok": self.on_ok,
                "up": self.on_up,
                "down": self.on_down,
                "left": self.on_up,
                "right": self.on_down,
                "info": self.show_trailer,
            }, -1)

        self.clock_timer = eTimer()
        self.clock_timer.callback.append(self._update_clock)
        self.clock_timer.start(1000)

        self.onLayoutFinish.append(self.on_start)
        self.onClose.append(self.__onClose)

    def __onClose(self):
        try:
            self.clock_timer.stop()
        except Exception:
            pass

    def _update_clock(self):
        from datetime import datetime
        now = datetime.now()
        days = ["Monday", "Tuesday", "Wednesday", "Thursday",
                "Friday", "Saturday", "Sunday"]
        months = ["Jan", "Feb", "Mar", "Apr", "May", "Jun",
                  "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
        self["day"].setText(days[now.weekday()])
        self["date"].setText("%d. %s" % (now.day, months[now.month - 1]))
        self["clock"].setText(now.strftime("%H:%M"))

    def on_start(self):
        self._update_clock()
        self._load_picon()
        self.refresh_epg()

    def _load_picon(self):
        try:
            pm = PiconManager()
            p = pm.find_picon(self.channel_ref, self.channel_name)
            if p:
                px = LoadPixmap(p)
                if px and self["picon"].instance:
                    self["picon"].instance.setPixmap(px)
                    self["picon"].show()
                    return
            self["picon"].hide()
        except Exception as e:
            print("[EPGListScreen] picon error:", e)

    def refresh_epg(self):
        self.epg_events = get_epg_for_ref(self.channel_ref, max_items=20)
        if not self.epg_events:
            self["epg_list"].setList(["No EPG data"])
            self["status"].setText("No EPG data for this channel")
            return

        items = []
        for idx, ev in enumerate(self.epg_events):
            b = ev.get("begin")
            hhmm = time.strftime("%H:%M", time.localtime(int(b))) if b else "--:--"
            name = ev.get("name", "") or "(no title)"
            if len(name) > 55:
                name = name[:55] + "…"
            prefix = "▶" if idx == 0 else "  "
            items.append("%s %s  %s" % (prefix, hhmm, name))

        self["epg_list"].setList(items)
        self["epg_list"].moveToIndex(0)
        self._process_event(0)

    def _process_event(self, idx):
        if idx < 0 or idx >= len(self.epg_events):
            return
        self.current_event = self.epg_events[idx]
        ev = self.current_event

        raw_title = ev.get("name", "")
        short = ev.get("short", "")
        ext = ev.get("ext", "")
        desc = (short + " " + ext).strip()

        title = re.sub(r"\s*\[.*?\]|\s*\(.*?\)|\s*-\s*.+$", "", raw_title).strip()
        title = re.sub(r"^Film[:\-]?\s*|^Movie[:\-]?\s*", "", title, flags=re.I).strip()

        year = None
        m = re.search(r"\b(19|20)\d{2}\b", raw_title + " " + desc)
        if m:
            year = int(m.group(0))

        self["title"].setText(title or raw_title)
        self["epg_title"].setText("EPG: " + raw_title)

        if ev.get("duration"):
            self["duration"].setText("Duration: %d min (EPG)" % (int(ev["duration"]) // 60))

        self["rating"].setText("")
        self["imdb_rating"].setText("")
        self["genres"].setText("")
        self["director"].setText("")
        self["cast_header"].setText("")
        self["cast_col1"].setText("")
        self["cast_col2"].setText("")
        self.current_trailer_id = None
        self.current_media_details = None
        self.current_media_type = None
        self._show_placeholder()

        if desc:
            if len(desc) > 700:
                cut = desc[:700].rfind(". ")
                desc = desc[:cut + 1] + " ..." if cut > 400 else desc[:700] + " ..."
            self["plot"].setText("Plot:\n" + desc)
        else:
            self["plot"].setText("Plot:\nNo description available.")

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
            print("[EPGListScreen] tmdb async error:", e)

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
                overview = overview[:cut + 1] + " ..." if cut > 400 else overview[:700] + " ..."
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

        # Trailer
        media_id = details.get("id")
        if media_id:
            threading.Thread(
                target=self._fetch_trailer_async,
                args=(media_id, media_type, config.plugins.ciefpchannelhistory.tmdb_api_key.value.strip()),
                daemon=True
            ).start()

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

    def _fetch_trailer_async(self, media_id, media_type, api_key):
        try:
            key = tmdb_trailer(media_id, media_type, api_key)
            self.current_trailer_id = key
        except Exception:
            self.current_trailer_id = None

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
                print("[EPGListScreen] poster error:", e)

        threading.Thread(target=worker, daemon=True).start()

    def _show_placeholder(self):
        px = load_pixmap_safe(PLACEHOLDER)
        if px and self["poster"].instance:
            self["poster"].instance.setPixmap(px)

    def on_up(self):
        try:
            cur = self["epg_list"].getSelectedIndex()
            if cur > 0:
                self["epg_list"].up()
                new_idx = self["epg_list"].getSelectedIndex()
                if new_idx != cur:
                    self._process_event(new_idx)
        except Exception as e:
            print("[EPGListScreen] on_up error:", e)

    def on_down(self):
        try:
            cur = self["epg_list"].getSelectedIndex()
            if cur < len(self.epg_events) - 1:
                self["epg_list"].down()
                new_idx = self["epg_list"].getSelectedIndex()
                if new_idx != cur:
                    self._process_event(new_idx)
        except Exception as e:
            print("[EPGListScreen] on_down error:", e)

    def on_ok(self):
        """OK — prebaci na ovaj kanal."""
        try:
            ref = eServiceReference(self.channel_ref)
            from Screens.InfoBar import InfoBar
            if InfoBar and InfoBar.instance:
                InfoBar.instance.session.nav.playService(ref)
                self["status"].setText("Switched to %s" % self.channel_name)
                self.close()
        except Exception as e:
            print("[EPGListScreen] switch error:", e)

    def show_trailer(self):
        if not self.current_trailer_id:
            self["status"].setText("No trailer available")
            return
        title = ""
        if self.current_media_details:
            title = self.current_media_details.get("title") or \
                    self.current_media_details.get("name", "")
        self["status"].setText("Playing trailer...")
        try:
            url = "https://www.youtube.com/watch?v=%s" % self.current_trailer_id
            cmd = ["yt-dlp", "-g", "-f", "best", url]
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
            if result.returncode != 0:
                cmd = ["yt-dlp", "-g", url]
                result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
            if result.returncode != 0:
                self["status"].setText("yt-dlp failed")
                return
            video_url = result.stdout.strip().split("\n")[0]
            if not video_url:
                self["status"].setText("No stream URL")
                return
            ref = eServiceReference(4097, 0, video_url)
            try:
                if title:
                    ref.setName("%s - Trailer" % title)
            except Exception:
                pass
            from Screens.InfoBar import InfoBar
            if InfoBar and InfoBar.instance:
                InfoBar.instance.session.nav.playService(ref)
                self.close()
        except Exception as e:
            print("[EPGListScreen] play youtube error:", e)
            self["status"].setText("Trailer error")

    def cast_explore(self):
        if not self.current_media_details:
            self["status"].setText("No TMDB info loaded")
            return
        credits = self.current_media_details.get("credits", {})
        cast = credits.get("cast", [])
        crew = credits.get("crew", [])
        directors = [c for c in crew if c.get("job") == "Director"]

        menu = []
        for d in directors[:2]:
            menu.append(("Director: %s" % d.get("name", ""), d))
        for i, a in enumerate(cast[:20]):
            name = a.get("name", "")
            char = a.get("character", "")
            if len(char) > 30:
                char = char[:30] + "…"
            menu.append(("%d. %s (%s)" % (i + 1, name, char), a))

        if not menu:
            self["status"].setText("No cast info")
            return

        def cb(choice):
            if choice and choice[1]:
                person = choice[1]
                name = person.get("name", "")
                if name:
                    self["status"].setText("Loading: %s..." % name)
                    threading.Thread(
                        target=self._load_person_async,
                        args=(name,),
                        daemon=True
                    ).start()

        title = self.current_media_details.get("title") or \
                self.current_media_details.get("name", "")
        self.session.openWithCallback(cb, ChoiceBox,
                                      title="Cast & Crew: %s" % title,
                                      list=menu)

    def _load_person_async(self, name):
        api_key = config.plugins.ciefpchannelhistory.tmdb_api_key.value.strip()
        if not api_key:
            self["status"].setText("TMDB API key not set")
            return
        result = tmdb_search_person(name, api_key)
        if not result:
            self["status"].setText("Person not found: %s" % name)
            return
        person_id = result.get("id")
        details = tmdb_person_details(person_id, api_key)
        if not details:
            self["status"].setText("Person details error: %s" % name)
            return
        # Sačuvaj film da se možemo vratiti
        self._saved_media_state = {
            "media_details": self.current_media_details,
            "media_type": self.current_media_type,
            "trailer_id": self.current_trailer_id,
        }
        self.current_person_details = details
        self.current_person_name = details.get("name", name)
        self._display_person_info(details)

    def _display_person_info(self, details):
        person_id = details.get("id")
        name = details.get("name", "N/A")
        known_for = details.get("known_for_department", "")
        birthday = details.get("birthday", "")
        deathday = details.get("deathday", "")
        place_of_birth = details.get("place_of_birth", "")
        biography = details.get("biography", "").strip()

        movie_credits = details.get("movie_credits", {}).get("cast", [])
        tv_credits = details.get("tv_credits", {}).get("cast", [])
        movie_ids = set()
        unique_movies = []
        for m in movie_credits:
            if m.get("id") not in movie_ids:
                movie_ids.add(m.get("id"))
                unique_movies.append(m)
        tv_ids = set()
        unique_tv = []
        for t in tv_credits:
            if t.get("id") not in tv_ids:
                tv_ids.add(t.get("id"))
                unique_tv.append(t)

        self["title"].setText(name + (("  (%s)" % known_for) if known_for else ""))
        self["epg_title"].setText("Actor Profile")

        if birthday:
            try:
                y, m, d = birthday.split("-")
                pretty_birth = "%s.%s.%s" % (int(d), int(m), y)
            except Exception:
                pretty_birth = birthday
        else:
            pretty_birth = "N/A"

        self["duration"].setText("Born: %s" % pretty_birth)
        self["rating"].setText("Place: %s" % place_of_birth if place_of_birth else "")
        self["imdb_rating"].setText(
            "Movies: %d  |  TV Series: %d" % (len(unique_movies), len(unique_tv)))
        self["director"].setText("")

        if deathday:
            try:
                y, m, d = deathday.split("-")
                pretty_death = "%s.%s.%s" % (int(d), int(m), y)
            except Exception:
                pretty_death = deathday
            self["genres"].setText("Died: %s" % pretty_death)
        else:
            self["genres"].setText("")

        if biography:
            biography = re.sub(r"\n{2,}", "\n", biography).strip()
            MAX_BIO = 700
            if len(biography) > MAX_BIO:
                cut = biography[:MAX_BIO].rfind(". ")
                if cut > 400:
                    biography = biography[:cut + 1] + " ..."
                else:
                    biography = biography[:MAX_BIO] + " ..."
            self["plot"].setText("Biography:\n" + biography)

        self["cast_header"].setText("Known For:")

        def score(x):
            pop = x.get("popularity", 0) or 0
            votes = x.get("vote_count", 0) or 0
            return votes * 10 + pop

        unique_movies.sort(key=score, reverse=True)
        unique_tv.sort(key=score, reverse=True)

        def fmt_movie(m):
            title = m.get("title", "N/A")
            year = (m.get("release_date") or "")[:4]
            rating = m.get("vote_average", 0) or 0
            ys = " (%s)" % year if year else ""
            rs = " %.1f★" % rating if rating > 0 else ""
            return "• %s%s%s" % (title, ys, rs)

        def fmt_tv(t):
            name = t.get("name", "N/A")
            year = (t.get("first_air_date") or "")[:4]
            rating = t.get("vote_average", 0) or 0
            ys = " (%s)" % year if year else ""
            rs = " %.1f★" % rating if rating > 0 else ""
            return "• %s%s%s" % (name, ys, rs)

        self["cast_col1"].setText("Movies:\n" + "\n".join([fmt_movie(m) for m in unique_movies[:5]]))
        self["cast_col2"].setText("TV Series:\n" + "\n".join([fmt_tv(t) for t in unique_tv[:5]]))

        profile_path = details.get("profile_path")
        if profile_path:
            self._download_person_photo_async(profile_path, person_id)
        else:
            self._show_placeholder()

        self["status"].setText("Profile: %s  (BACK to return to movie)" % name)

    def _download_person_photo_async(self, profile_path, person_id):
        if not profile_path or not person_id:
            self._show_placeholder()
            return
        if not config.plugins.ciefpchannelhistory.cache_enabled.value:
            self._show_placeholder()
            return

        def worker():
            try:
                folder = config.plugins.ciefpchannelhistory.cache_folder.value
                ensure_folder(folder)
                fname = os.path.join(
                    folder,
                    "person_%s_%s" % (person_id, os.path.basename(profile_path))
                )
                if not os.path.exists(fname):
                    url = "https://image.tmdb.org/t/p/w500" + profile_path
                    ctx = ssl.create_default_context()
                    ctx.check_hostname = False
                    ctx.verify_mode = ssl.CERT_NONE
                    data = urllib.request.urlopen(url, context=ctx, timeout=12).read()
                    with open(fname, "wb") as f:
                        f.write(data)
                px = load_pixmap_safe(fname)
                if px and self["poster"].instance:
                    self["poster"].instance.setPixmap(px)
            except Exception as e:
                print("[EPGListScreen] person photo error:", e)

        threading.Thread(target=worker, daemon=True).start()

    def filmography_browser(self):
        """Zeleno — filmografija."""
        if self.current_person_details:
            self._show_person_filmography()
            return

        if not self.current_media_details:
            self["status"].setText("No TMDB info loaded")
            return

        credits = self.current_media_details.get("credits", {})
        cast = credits.get("cast", [])
        crew = credits.get("crew", [])
        directors = [c for c in crew if c.get("job") == "Director"]

        # TUPLE LISTA
        menu = []
        for d in directors[:3]:
            menu.append(("Director: %s" % d.get("name", ""), d))
        for i, a in enumerate(cast[:25]):
            name = a.get("name", "")
            char = a.get("character", "")
            if len(char) > 30:
                char = char[:30] + "..."
            menu.append(("%d. %s (%s)" % (i + 1, name, char), a))

        if not menu:
            self["status"].setText("No cast info")
            return

        def cb(choice):
            if choice and choice[1]:
                person = choice[1]
                name = person.get("name", "")
                if name:
                    self["status"].setText("Loading filmography: %s..." % name)
                    threading.Thread(
                        target=self._load_person_for_filmography,
                        args=(name,),
                        daemon=True
                    ).start()

        title = self.current_media_details.get("title") or \
                self.current_media_details.get("name", "")
        self.session.openWithCallback(
            cb, ChoiceBox,
            title="Filmography Browser: %s" % title,
            list=menu
        )

    def _show_person_filmography(self):
        """Prikaži filmografiju kroz ChoiceBox — TUPLE LISTA (kao cast_explore)."""
        if not self.current_person_details:
            self["status"].setText("No person loaded")
            return

        person = self.current_person_details
        person_name = person.get("name", "Unknown")

        movie_credits = person.get("movie_credits", {}).get("cast", [])
        tv_credits = person.get("tv_credits", {}).get("cast", [])

        seen_m = set()
        unique_movies = []
        for m in movie_credits:
            if m.get("id") not in seen_m:
                seen_m.add(m.get("id"))
                unique_movies.append(m)

        seen_t = set()
        unique_tv = []
        for t in tv_credits:
            if t.get("id") not in seen_t:
                seen_t.add(t.get("id"))
                unique_tv.append(t)

        def score(x):
            pop = x.get("popularity", 0) or 0
            votes = x.get("vote_count", 0) or 0
            return votes * 10 + pop

        unique_movies.sort(key=score, reverse=True)
        unique_tv.sort(key=score, reverse=True)

        top_movies = unique_movies[:15]
        top_tv = unique_tv[:15]

        # TUPLE LISTA (kao cast_explore)
        menu = []

        if top_movies:
            menu.append(("-- MOVIES (%d) --" % len(top_movies), None))
            for m in top_movies:
                t = m.get("title", "N/A")
                year = (m.get("release_date") or "")[:4]
                rating = m.get("vote_average", 0) or 0
                ys = " (%s)" % year if year else ""
                rs = " %.1f" % rating if rating > 0 else ""
                menu.append((
                    "M: %s%s%s" % (t, ys, rs),
                    ("movie", m)
                ))

        if top_tv:
            menu.append(("-- TV SERIES (%d) --" % len(top_tv), None))
            for t in top_tv:
                n = t.get("name", "N/A")
                year = (t.get("first_air_date") or "")[:4]
                rating = t.get("vote_average", 0) or 0
                ys = " (%s)" % year if year else ""
                rs = " %.1f" % rating if rating > 0 else ""
                menu.append((
                    "T: %s%s%s" % (n, ys, rs),
                    ("tv", t)
                ))

        if not menu:
            self["status"].setText("No filmography for %s" % person_name)
            return

        def media_selected(choice):
            if not choice:
                return
            # choice je tuple (text, value)
            value = choice[1]
            if value is None:
                return
            media_type, media_data = value
            media_id = media_data.get("id")
            title = media_data.get("title") or media_data.get("name", "Unknown")
            if media_id:
                self["status"].setText("Loading %s..." % title)
                threading.Thread(
                    target=self._load_media_from_filmography,
                    args=(media_id, media_type, title),
                    daemon=True
                ).start()

        self.session.openWithCallback(
            media_selected, ChoiceBox,
            title="Filmography: %s" % person_name,
            list=menu
        )

    def _load_media_from_filmography(self, media_id, media_type, media_title):
        """Učitaj film/seriju iz filmografije i prikaži u glavnom ekranu."""
        api_key = config.plugins.ciefpchannelhistory.tmdb_api_key.value.strip()
        if not api_key:
            self["status"].setText("TMDB API key not set")
            return

        try:
            details = tmdb_details(media_id, media_type, api_key)
            if not details:
                self["status"].setText("Error loading media details")
                return

            # Sačuvaj prethodno stanje
            if not self._saved_media_state:
                self._saved_media_state = {
                    "media_details": self.current_media_details,
                    "media_type": self.current_media_type,
                    "trailer_id": self.current_trailer_id,
                }

            self.current_media_details = details
            self.current_media_type = media_type

            # Prikaži u glavnom ekranu
            self._update_ui_with_tmdb(self._loading_token, details, media_type)

            # Ažuriraj epg_title
            person_name = getattr(self, 'current_person_name', '')
            if person_name:
                self["epg_title"].setText("From filmography: %s" % person_name)

            self["status"].setText("Loaded: %s ✓" % media_title)

        except Exception as e:
            print("[EPGListScreen] load media from filmography error:", e)
            self["status"].setText("Error loading media")

    def keyBack(self):
        """BACK — ako smo na profilu osobe, vrati se na film."""
        if self._saved_media_state and self._saved_media_state.get("media_details"):
            self.current_media_details = self._saved_media_state["media_details"]
            self.current_media_type = self._saved_media_state["media_type"]
            self.current_trailer_id = self._saved_media_state.get("trailer_id")
            self._saved_media_state = None
            self._update_ui_with_tmdb(self._loading_token,
                                      self.current_media_details,
                                      self.current_media_type)
            self["status"].setText("Returned to movie")
            return
        self.close()