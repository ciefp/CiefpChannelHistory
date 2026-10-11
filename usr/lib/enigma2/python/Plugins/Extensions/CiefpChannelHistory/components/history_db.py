# -*- coding: utf-8 -*-
#
# CiefpChannelHistory - SQLite storage for channel watch history
#
import os
import sqlite3
import threading
import time
from datetime import datetime


DB_VERSION = 2


class HistoryDB:
    """SQLite baza za praćenje gledanosti kanala.

    Optimizacije:
    - PRAGMA synchronous = NORMAL (brz commit)
    - PRAGMA journal_mode = WAL (bolji concurrent pristup)
    - Sessions se kreiraju odmah i periodično UPDATE-uju
    """

    def __init__(self, db_path):
        self.db_path = db_path
        self.lock = threading.Lock()
        self._ensure_folder()
        self.conn = sqlite3.connect(db_path, check_same_thread=False, timeout=10)
        self.conn.row_factory = sqlite3.Row
        # Optimizacije
        try:
            self.conn.execute("PRAGMA synchronous = NORMAL")
            self.conn.execute("PRAGMA journal_mode = WAL")
            self.conn.execute("PRAGMA temp_store = MEMORY")
            self.conn.execute("PRAGMA cache_size = -2000")  # 2MB cache
        except Exception as e:
            print("[CiefpChannelHistory] PRAGMA error:", e)
        self._init_schema()

    def _ensure_folder(self):
        folder = os.path.dirname(self.db_path)
        if folder and not os.path.exists(folder):
            try:
                os.makedirs(folder)
            except Exception as e:
                print("[CiefpChannelHistory] mkdir error:", e)

    def _init_schema(self):
        with self.lock:
            c = self.conn.cursor()
            c.execute("PRAGMA user_version")
            v = c.fetchone()[0]

            c.execute("""
                CREATE TABLE IF NOT EXISTS channels (
                    ref TEXT PRIMARY KEY,
                    name TEXT,
                    provider TEXT,
                    type TEXT,
                    first_seen INTEGER,
                    last_seen INTEGER,
                    total_seconds INTEGER DEFAULT 0,
                    watch_count INTEGER DEFAULT 0
                )
            """)
            c.execute("""
                CREATE TABLE IF NOT EXISTS sessions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    ref TEXT,
                    start_time INTEGER,
                    end_time INTEGER,
                    duration INTEGER
                )
            """)
            c.execute("""
                CREATE INDEX IF NOT EXISTS idx_sessions_ref
                ON sessions(ref)
            """)
            c.execute("""
                CREATE INDEX IF NOT EXISTS idx_sessions_start
                ON sessions(start_time)
            """)
            c.execute("""
                CREATE INDEX IF NOT EXISTS idx_sessions_end
                ON sessions(end_time)
            """)

            # Migracija — dodaj nove kolone ako ne postoje
            for col_name, col_type in [
                ("satellite", "TEXT"),
                ("satellite_pos", "TEXT"),
                ("caid", "TEXT"),
                ("caid_name", "TEXT"),
                ("caids", "TEXT"),            # ← NOVO
                ("is_crypted", "INTEGER DEFAULT 0"),
            ]:
                try:
                    c.execute("ALTER TABLE channels ADD COLUMN %s %s" % (col_name, col_type))
                    print("[CiefpChannelHistory] Added column: %s" % col_name)
                except Exception:
                    # Kolona već postoji — ignoriši
                    pass

            if v < DB_VERSION:
                c.execute("PRAGMA user_version = %d" % DB_VERSION)
            self.conn.commit()

    # ---------------- SESSION LIFECYCLE ----------------
    def start_session(self, ref_str, name, provider, stype, start_time,
                      satellite="", satellite_pos="", caid="", caid_name="",
                      caids_str="", is_crypted=0):
        """
        Kreira novu sesiju odmah. Vraća ID sesije.
        Kanal se upsert-uje u channels tabelu sa svim metapodacima.
        """
        with self.lock:
            try:
                c = self.conn.cursor()
                # Upsert channel — sve kolone
                c.execute("""
                    INSERT INTO channels
                        (ref, name, provider, type, first_seen, last_seen,
                         total_seconds, watch_count,
                         satellite, satellite_pos, caid, caid_name, is_crypted)
                    VALUES (?, ?, ?, ?, ?, ?, 0, 1, ?, ?, ?, ?, ?)
                    ON CONFLICT(ref) DO UPDATE SET
                        last_seen = excluded.last_seen,
                        watch_count = watch_count + 1,
                        type = excluded.type,
                        satellite = CASE
                            WHEN excluded.satellite != '' THEN excluded.satellite
                            ELSE channels.satellite END,
                        satellite_pos = CASE
                            WHEN excluded.satellite_pos != '' THEN excluded.satellite_pos
                            ELSE channels.satellite_pos END,
                        caid = CASE
                            WHEN excluded.caid != '' THEN excluded.caid
                            ELSE channels.caid END,
                        caid_name = CASE
                            WHEN excluded.caid_name != '' THEN excluded.caid_name
                            ELSE channels.caid_name END,
                        is_crypted = CASE
                            WHEN excluded.is_crypted = 1 THEN 1
                            ELSE channels.is_crypted END,
                        name = CASE
                            WHEN channels.name IS NULL OR channels.name = ''
                            THEN excluded.name ELSE channels.name END,
                        provider = CASE
                            WHEN channels.provider IS NULL OR channels.provider = ''
                            THEN excluded.provider ELSE channels.provider END
                """, (ref_str, name, provider, stype,
                      int(start_time), int(start_time),
                      satellite, satellite_pos, caid, caid_name, is_crypted))
                c.execute("""
                    INSERT INTO channels
                        (ref, name, provider, type, first_seen, last_seen,
                         total_seconds, watch_count,
                         satellite, satellite_pos, caid, caid_name, caids, is_crypted)
                    VALUES (?, ?, ?, ?, ?, ?, 0, 1, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(ref) DO UPDATE SET
                        last_seen = excluded.last_seen,
                        watch_count = watch_count + 1,
                        type = excluded.type,
                        satellite = CASE
                            WHEN excluded.satellite != '' THEN excluded.satellite
                            ELSE channels.satellite END,
                        satellite_pos = CASE
                            WHEN excluded.satellite_pos != '' THEN excluded.satellite_pos
                            ELSE channels.satellite_pos END,
                        caid = CASE
                            WHEN excluded.caid != '' THEN excluded.caid
                            ELSE channels.caid END,
                        caid_name = CASE
                            WHEN excluded.caid_name != '' THEN excluded.caid_name
                            ELSE channels.caid_name END,
                        caids = CASE
                            WHEN excluded.caids != '' THEN excluded.caids
                            ELSE channels.caids END,
                        is_crypted = CASE
                            WHEN excluded.is_crypted = 1 THEN 1
                            ELSE channels.is_crypted END,
                        name = CASE
                            WHEN channels.name IS NULL OR channels.name = ''
                            THEN excluded.name ELSE channels.name END,
                        provider = CASE
                            WHEN channels.provider IS NULL OR channels.provider = ''
                            THEN excluded.provider ELSE channels.provider END
                """, (ref_str, name, provider, stype,
                      int(start_time), int(start_time),
                      satellite, satellite_pos, caid, caid_name,
                      caids_str, is_crypted))

                # Insert session
                c.execute("""
                    INSERT INTO sessions (ref, start_time, end_time, duration)
                    VALUES (?, ?, ?, 0)
                """, (ref_str, int(start_time), int(start_time)))
                self.conn.commit()
                return c.lastrowid
            except Exception as e:
                print("[CiefpChannelHistory] start_session error:", e)
                return None

    def update_session(self, session_id, ref_str, end_time):
        """
        Produži sesiju — UPDATE end_time i duration.
        Takođe rekalkuliše channels.total_seconds za taj ref.
        """
        with self.lock:
            try:
                c = self.conn.cursor()
                # Uzmi start_time
                c.execute("SELECT start_time FROM sessions WHERE id = ?",
                          (session_id,))
                row = c.fetchone()
                if not row:
                    return
                start_time = row["start_time"]
                duration = int(end_time) - int(start_time)
                if duration <= 0:
                    return

                # Update session
                c.execute("""
                    UPDATE sessions SET end_time = ?, duration = ?
                    WHERE id = ?
                """, (int(end_time), duration, session_id))

                # Recompute channel totals (samo za ovaj ref)
                c.execute("""
                    UPDATE channels SET
                        total_seconds = COALESCE((
                            SELECT SUM(duration) FROM sessions
                            WHERE sessions.ref = channels.ref
                        ), 0),
                        last_seen = ?
                    WHERE ref = ?
                """, (int(end_time), ref_str))
                self.conn.commit()
            except Exception as e:
                print("[CiefpChannelHistory] update_session error:", e)

    def finalize_session(self, session_id, ref_str, end_time):
        """Finalni update sesije pri promjeni kanala ili gašenju."""
        self.update_session(session_id, ref_str, end_time)

    # ---------------- WRITE (staro, zadržano za kompatibilnost) ----------------
    def add_session(self, ref_str, name, provider, stype, start, end):
        """Direktan upis kompletne sesije (za slučaj kad znamo start i end)."""
        duration = max(0, int(end) - int(start))
        if duration <= 0:
            return

        with self.lock:
            try:
                c = self.conn.cursor()
                c.execute("""
                    INSERT INTO channels
                        (ref, name, provider, type, first_seen, last_seen,
                         total_seconds, watch_count)
                    VALUES (?, ?, ?, ?, ?, ?, ?, 1)
                    ON CONFLICT(ref) DO UPDATE SET
                        last_seen = excluded.last_seen,
                        total_seconds = total_seconds + excluded.total_seconds,
                        watch_count = watch_count + 1,
                        type = excluded.type,
                        name = CASE
                            WHEN channels.name IS NULL OR channels.name = ''
                            THEN excluded.name ELSE channels.name END,
                        provider = CASE
                            WHEN channels.provider IS NULL OR channels.provider = ''
                            THEN excluded.provider ELSE channels.provider END
                """, (ref_str, name, provider, stype,
                      int(start), int(end), duration))

                c.execute("""
                    INSERT INTO sessions (ref, start_time, end_time, duration)
                    VALUES (?, ?, ?, ?)
                """, (ref_str, int(start), int(end), duration))
                self.conn.commit()
            except Exception as e:
                print("[CiefpChannelHistory] add_session error:", e)

    # ---------------- CLEANUP ----------------
    def cleanup_old_sessions(self, days=90):
        """Obriši sesije starije od N dana i rekalkuliši totals."""
        cutoff = int(time.time()) - days * 86400
        with self.lock:
            try:
                c = self.conn.cursor()
                c.execute("DELETE FROM sessions WHERE end_time < ?", (cutoff,))
                # Recompute totals za sve kanale
                c.execute("""
                    UPDATE channels SET
                        total_seconds = COALESCE((
                            SELECT SUM(duration) FROM sessions
                            WHERE sessions.ref = channels.ref
                        ), 0),
                        watch_count = COALESCE((
                            SELECT COUNT(*) FROM sessions
                            WHERE sessions.ref = channels.ref
                        ), 0)
                """)
                self.conn.commit()
                return c.rowcount
            except Exception as e:
                print("[CiefpChannelHistory] cleanup error:", e)
                return 0

    def clear_all(self):
        with self.lock:
            try:
                c = self.conn.cursor()
                c.execute("DELETE FROM sessions")
                c.execute("DELETE FROM channels")
                self.conn.commit()
                return True
            except Exception as e:
                print("[CiefpChannelHistory] clear_all error:", e)
                return False

    def delete_channel(self, ref_str):
        with self.lock:
            try:
                c = self.conn.cursor()
                c.execute("DELETE FROM sessions WHERE ref = ?", (ref_str,))
                c.execute("DELETE FROM channels WHERE ref = ?", (ref_str,))
                self.conn.commit()
                return True
            except Exception:
                return False

    # ---------------- READ ----------------
    def get_recent_channels(self, limit=15):
        with self.lock:
            try:
                c = self.conn.cursor()
                c.execute("""
                    SELECT ref, name, provider, type, last_seen,
                           total_seconds, watch_count
                    FROM channels
                    ORDER BY last_seen DESC
                    LIMIT ?
                """, (int(limit),))
                return [dict(row) for row in c.fetchall()]
            except Exception as e:
                print("[CiefpChannelHistory] get_recent error:", e)
                return []

    def get_active_session(self):
        """Vraća aktivnu sesiju (end_time == start_time ili najnovija)."""
        with self.lock:
            try:
                c = self.conn.cursor()
                c.execute("""
                    SELECT id, ref, start_time, end_time, duration
                    FROM sessions
                    ORDER BY id DESC
                    LIMIT 1
                """)
                row = c.fetchone()
                return dict(row) if row else None
            except Exception:
                return None

    def get_stats_overview(self):
        with self.lock:
            try:
                c = self.conn.cursor()
                c.execute("SELECT COUNT(*) as cnt, "
                          "COALESCE(SUM(total_seconds),0) as total FROM channels")
                row = c.fetchone()
                c.execute("SELECT COUNT(*) as scnt, "
                          "COALESCE(SUM(duration),0) as stotal FROM sessions")
                srow = c.fetchone()
                c.execute("SELECT MIN(first_seen) as first FROM channels")
                frow = c.fetchone()
                return {
                    "channels": row["cnt"] or 0,
                    "total_seconds": row["total"] or 0,
                    "sessions": srow["scnt"] or 0,
                    "sessions_seconds": srow["stotal"] or 0,
                    "first_seen": frow["first"] or 0,
                }
            except Exception:
                return {"channels": 0, "total_seconds": 0,
                        "sessions": 0, "sessions_seconds": 0,
                        "first_seen": 0}

    def get_top_channels(self, limit=10):
        with self.lock:
            try:
                c = self.conn.cursor()
                c.execute("""
                    SELECT ref, name, provider, type,
                           total_seconds, watch_count,
                           satellite, satellite_pos, caid, caid_name, is_crypted
                    FROM channels
                    ORDER BY total_seconds DESC
                    LIMIT ?
                """, (int(limit),))
                return [dict(row) for row in c.fetchall()]
            except Exception:
                return []

    def get_stats_by_type(self):
        with self.lock:
            try:
                c = self.conn.cursor()
                c.execute("""
                    SELECT type,
                           SUM(total_seconds) as total,
                           COUNT(*) as cnt,
                           SUM(watch_count) as sessions
                    FROM channels
                    GROUP BY type
                    ORDER BY total DESC
                """)
                return [dict(row) for row in c.fetchall()]
            except Exception:
                return []

    def get_stats_by_hour(self):
        with self.lock:
            try:
                c = self.conn.cursor()
                c.execute("""
                    SELECT CAST(strftime('%H', start_time,
                              'unixepoch', 'localtime') AS INTEGER) as hour,
                           SUM(duration) as total,
                           COUNT(*) as sessions
                    FROM sessions
                    GROUP BY hour
                    ORDER BY hour
                """)
                return [dict(row) for row in c.fetchall()]
            except Exception:
                return []

    def get_stats_by_weekday(self):
        with self.lock:
            try:
                c = self.conn.cursor()
                c.execute("""
                    SELECT CAST(strftime('%w', start_time,
                              'unixepoch', 'localtime') AS INTEGER) as wd,
                           SUM(duration) as total,
                           COUNT(*) as sessions
                    FROM sessions
                    GROUP BY wd
                    ORDER BY wd
                """)
                return [dict(row) for row in c.fetchall()]
            except Exception:
                return []

    def get_timeline_days(self, days=7):
        """Vraća listu (date_str, total_seconds, sessions) za zadnjih N dana."""
        with self.lock:
            try:
                c = self.conn.cursor()
                c.execute("""
                    SELECT date(start_time, 'unixepoch', 'localtime') as day,
                           SUM(duration) as total,
                           COUNT(*) as sessions
                    FROM sessions
                    WHERE start_time >= ?
                    GROUP BY day
                    ORDER BY day DESC
                """, (int(time.time()) - days * 86400,))
                return [dict(row) for row in c.fetchall()]
            except Exception:
                return []

    def get_typical_channel_for_now(self):
        now = datetime.now()
        wd = (now.weekday() + 1) % 7
        hour = now.hour
        with self.lock:
            try:
                c = self.conn.cursor()
                c.execute("""
                    SELECT ref, COUNT(*) as freq
                    FROM sessions
                    WHERE CAST(strftime('%w', start_time,
                              'unixepoch', 'localtime') AS INTEGER) = ?
                      AND CAST(strftime('%H', start_time,
                              'unixepoch', 'localtime') AS INTEGER)
                          BETWEEN ? AND ?
                    GROUP BY ref
                    ORDER BY freq DESC
                    LIMIT 1
                """, (wd, max(0, hour - 1), min(23, hour + 1)))
                row = c.fetchone()
                if row:
                    return row["ref"]
            except Exception:
                pass
        return None

    def get_typical_channels_for_now(self, limit=3):
        """Vraća top N kanala za trenutni dan i sat."""
        now = datetime.now()
        wd = (now.weekday() + 1) % 7
        hour = now.hour
        with self.lock:
            try:
                c = self.conn.cursor()
                c.execute("""
                    SELECT ref, COUNT(*) as freq
                    FROM sessions
                    WHERE CAST(strftime('%w', start_time,
                              'unixepoch', 'localtime') AS INTEGER) = ?
                      AND CAST(strftime('%H', start_time,
                              'unixepoch', 'localtime') AS INTEGER)
                          BETWEEN ? AND ?
                    GROUP BY ref
                    ORDER BY freq DESC
                    LIMIT ?
                """, (wd, max(0, hour - 1), min(23, hour + 1), int(limit)))
                return [dict(row) for row in c.fetchall()]
            except Exception:
                return []
    def get_stats_by_satellite(self):
        """Statistika po satelitu (samo DVB-S/T)."""
        with self.lock:
            try:
                c = self.conn.cursor()
                c.execute("""
                    SELECT satellite_pos, satellite,
                           SUM(total_seconds) as total,
                           COUNT(*) as cnt,
                           SUM(watch_count) as sessions
                    FROM channels
                    WHERE satellite_pos != '' AND satellite_pos IS NOT NULL
                    GROUP BY satellite_pos
                    ORDER BY total DESC
                """)
                return [dict(row) for row in c.fetchall()]
            except Exception as e:
                print("[CiefpChannelHistory] get_stats_by_satellite error:", e)
                return []
    def get_stats_by_encryption(self):
        """Statistika po CAID-u (FTA vs kriptovano)."""
        with self.lock:
            try:
                c = self.conn.cursor()
                c.execute("""
                    SELECT 
                        CASE 
                            WHEN is_crypted = 1 AND caid != '' THEN caid
                            ELSE ''
                        END as caid,
                        CASE 
                            WHEN is_crypted = 1 AND caid_name != '' THEN caid_name
                            ELSE ''
                        END as caid_name,
                        MAX(is_crypted) as is_crypted,
                        SUM(total_seconds) as total,
                        COUNT(*) as cnt,
                        SUM(watch_count) as sessions
                    FROM channels
                    GROUP BY caid
                    ORDER BY total DESC
                """)
                return [dict(row) for row in c.fetchall()]
            except Exception as e:
                print("[CiefpChannelHistory] get_stats_by_encryption error:", e)
                return []

    def close(self):
        try:
            with self.lock:
                self.conn.close()
        except Exception:
            pass