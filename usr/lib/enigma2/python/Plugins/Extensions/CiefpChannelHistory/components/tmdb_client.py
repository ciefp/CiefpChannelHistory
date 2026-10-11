# -*- coding: utf-8 -*-
#
# CiefpChannelHistory - TMDB / OMDb klijent
#
import json
import ssl
import urllib.request
import urllib.parse

from Components.config import config


GENERIC_TITLES = {
    "vesti", "vijesti", "dnevnik", "program", "info",
    "news", "weather", "sports", "nachrichten", "wetter",
    "actualités", "météo", "notizie", "meteo", "noticias",
    "zprávy", "počasí",
}


def is_generic_title(title):
    if not title:
        return True
    t = title.lower().strip()
    if t in GENERIC_TITLES:
        return True
    if len(t) < 4:
        return True
    return False


def _ssl_ctx():
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    return ctx


def tmdb_search_multi(title, year, api_key):
    if not api_key or not title:
        return None, None
    try:
        params = {
            "api_key": api_key,
            "query": title,
            "language": config.plugins.ciefpchannelhistory.language.value,
            "include_adult": "false",
        }
        if year:
            params["year"] = str(year)
        url = "https://api.themoviedb.org/3/search/multi?" + urllib.parse.urlencode(params)
        with urllib.request.urlopen(url, context=_ssl_ctx(), timeout=12) as resp:
            data = json.loads(resp.read().decode("utf-8", errors="ignore"))
        results = [r for r in data.get("results", [])
                   if r.get("media_type") in ("movie", "tv")]
        if not results:
            return None, None
        if year:
            for c in results:
                c_year = (c.get("release_date") or c.get("first_air_date") or "")[:4]
                if c_year == str(year):
                    return c, c["media_type"]
        best = results[0]
        return best, best["media_type"]
    except Exception as e:
        print("[CiefpChannelHistory] tmdb search error:", e)
        return None, None


def tmdb_details(media_id, media_type, api_key):
    try:
        url = ("https://api.themoviedb.org/3/%s/%s?api_key=%s&language=%s"
               "&append_to_response=credits,videos") % (
            media_type, media_id, api_key,
            config.plugins.ciefpchannelhistory.language.value)
        with urllib.request.urlopen(url, context=_ssl_ctx(), timeout=12) as resp:
            return json.loads(resp.read().decode("utf-8", errors="ignore"))
    except Exception as e:
        print("[CiefpChannelHistory] tmdb details error:", e)
        return None


def omdb_rating(details, media_type, api_key):
    if not api_key or not details:
        return None
    title = details.get("title") if media_type == "movie" else details.get("name")
    year = (details.get("release_date") or "")[:4] if media_type == "movie" else \
           (details.get("first_air_date") or "")[:4]
    if not title:
        return None
    try:
        params = {"apikey": api_key, "t": title, "r": "json"}
        if year:
            params["y"] = year
        url = "http://www.omdbapi.com/?" + urllib.parse.urlencode(params)
        with urllib.request.urlopen(url, context=_ssl_ctx(), timeout=8) as resp:
            data = json.loads(resp.read().decode("utf-8", errors="ignore"))
        if data.get("Response") == "True" and data.get("imdbRating") not in ("N/A", ""):
            return data.get("imdbRating")
    except Exception:
        pass
    return None


def tmdb_trailer(media_id, media_type, api_key):
    try:
        url = "https://api.themoviedb.org/3/%s/%s/videos?api_key=%s" % (
            media_type, media_id, api_key)
        with urllib.request.urlopen(url, context=_ssl_ctx(), timeout=10) as resp:
            data = json.loads(resp.read().decode("utf-8", errors="ignore"))
        for v in data.get("results", []):
            if v.get("site") == "YouTube" and v.get("type") in ("Trailer", "Teaser"):
                return v.get("key")
    except Exception as e:
        print("[CiefpChannelHistory] trailer error:", e)
    return None


def tmdb_search_person(name, api_key):
    if not api_key:
        return None
    try:
        params = {
            "api_key": api_key,
            "query": name,
            "language": config.plugins.ciefpchannelhistory.language.value,
        }
        url = "https://api.themoviedb.org/3/search/person?" + urllib.parse.urlencode(params)
        with urllib.request.urlopen(url, context=_ssl_ctx(), timeout=12) as resp:
            data = json.loads(resp.read().decode("utf-8", errors="ignore"))
        results = data.get("results", [])
        return results[0] if results else None
    except Exception as e:
        print("[CiefpChannelHistory] person search error:", e)
        return None


def tmdb_person_details(person_id, api_key):
    try:
        url = ("https://api.themoviedb.org/3/person/%s?api_key=%s&language=%s"
               "&append_to_response=movie_credits,tv_credits,external_ids") % (
            person_id, api_key,
            config.plugins.ciefpchannelhistory.language.value)
        with urllib.request.urlopen(url, context=_ssl_ctx(), timeout=12) as resp:
            return json.loads(resp.read().decode("utf-8", errors="ignore"))
    except Exception as e:
        print("[CiefpChannelHistory] person details error:", e)
        return None