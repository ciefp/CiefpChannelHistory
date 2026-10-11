# -*- coding: utf-8 -*-
#
# CiefpChannelHistory - praćenje promjena kanala
# Koristi eTimer polling + periodični UPDATE aktivne sesije
#
import time
import threading
from enigma import eTimer


class ChannelTracker:
    """
    Prati promjene kanala preko polling-a (eTimer).
    Sesija se kreira ODMAH kad kanal postane stabilan,
    a zatim se periodično produžava dok je kanal aktivan.

    Prednosti:
    - Nema gubitka podataka pri hard kill-u (max 30s)
    - Nema duplih sesija
    - Minimalno opterećenje (SQLite UPDATE je <30ms)
    """

    def __init__(self, db, min_watch_seconds=30, debounce_seconds=10,
                 poll_interval_seconds=5, periodic_update_seconds=30,
                 name_resolver=None, session=None):
        self.db = db
        self.min_watch = int(min_watch_seconds)
        self.debounce = int(debounce_seconds)
        self.poll_interval = int(poll_interval_seconds)
        self.periodic_update = int(periodic_update_seconds)
        self.name_resolver = name_resolver
        self.session = session

        # Aktivna sesija
        self.current_ref = None
        self.current_session_id = None
        self.current_start = None
        self.current_name = ""
        self.current_provider = ""
        self.current_type = "unknown"

        # Pending (kanal još nije stabilan)
        self.pending_ref = None
        self.pending_start = None
        self.pending_name = ""
        self.pending_provider = ""
        self.pending_type = "unknown"

        # Timeri
        self.commit_timer = eTimer()
        self.commit_timer.callback.append(self._commit_pending)

        self.update_timer = eTimer()
        self.update_timer.callback.append(self._periodic_update)

        self.poll_timer = eTimer()
        self.poll_timer.callback.append(self._poll_service)

    def start(self):
        try:
            self.poll_timer.start(self.poll_interval * 1000, False)
            self.update_timer.start(self.periodic_update * 1000, False)
            print("[CiefpChannelHistory] Tracker started (poll=%ds, update=%ds)"
                  % (self.poll_interval, self.periodic_update))
        except Exception as e:
            print("[CiefpChannelHistory] start error:", e)

    def stop(self):
        """Zaustavi trackere i finalizuj aktivnu sesiju."""
        self.commit_now()
        try:
            self.poll_timer.stop()
            self.commit_timer.stop()
            self.update_timer.stop()
        except Exception:
            pass

    # ---------------- TIMER CALLBACKS ----------------
    def _poll_service(self):
        """Polling trenutnog servisa svakih N sekundi."""
        try:
            ref_str = self._get_current_ref()
            if ref_str:
                self.on_channel_change(ref_str)
        except Exception as e:
            print("[CiefpChannelHistory] poll error:", e)

    def _periodic_update(self):
        """Produži aktivnu sesiju svakih N sekundi."""
        if not self.current_session_id or not self.current_ref:
            return
        if not self.current_start:
            return
        now = int(time.time())
        duration = now - self.current_start
        if duration < self.min_watch:
            return
        threading.Thread(
            target=self.db.update_session,
            args=(self.current_session_id, self.current_ref, now),
            daemon=True
        ).start()

    def _commit_pending(self):
        """Commit timer callback."""
        self._try_commit(int(time.time()))

    # ---------------- CORE LOGIC ----------------
    def _get_current_ref(self):
        """Dohvati trenutni service reference."""
        try:
            if self.session and self.session.nav:
                ref = self.session.nav.getCurrentlyPlayingServiceReference()
                if ref and hasattr(ref, "toString"):
                    return ref.toString()
        except Exception:
            pass
        try:
            from Screens.InfoBar import InfoBar
            if InfoBar.instance:
                ref = InfoBar.instance.session.nav.getCurrentlyPlayingServiceReference()
                if ref and hasattr(ref, "toString"):
                    return ref.toString()
        except Exception:
            pass
        return None

    def on_channel_change(self, ref_str):
        """Poziva se iz polling-a pri svakoj promjeni kanala."""
        if not ref_str:
            return
        now = int(time.time())

        # Isti kanal kao pending — resetuj commit timer
        if self.pending_ref == ref_str and self.pending_start:
            try:
                self.commit_timer.stop()
            except Exception:
                pass
            self.commit_timer.start(self.debounce * 1000, False)
            return

        # Isti kanal kao aktivna sesija — ne diraj
        if self.current_ref == ref_str:
            return

        # Prethodni pending — finalizuj aktivnu sesiju
        self._try_commit(now)

        # Novi pending
        self.pending_ref = ref_str
        self.pending_start = now
        self.pending_name = ""
        self.pending_provider = ""
        self.pending_type = "unknown"

        if self.name_resolver:
            try:
                name, provider, stype = self.name_resolver(ref_str)
                self.pending_name = name or ""
                self.pending_provider = provider or ""
                self.pending_type = stype or "unknown"
            except Exception as e:
                print("[CiefpChannelHistory] resolver error:", e)

        # Reset commit timer
        try:
            self.commit_timer.stop()
        except Exception:
            pass
        self.commit_timer.start(self.debounce * 1000, False)

    def _try_commit(self, now):
        """
        Finalizuj aktivnu sesiju ako postoji.
        Pending ostaje netaknut (čeka debounce).
        """
        # Finalizuj aktivnu sesiju (ako postoji)
        if self.current_session_id and self.current_ref:
            try:
                self.db.update_session(
                    self.current_session_id, self.current_ref, now)
                duration = now - (self.current_start or now)
                print("[CiefpChannelHistory] Session finalized: %s (%ds)"
                      % (self.current_name or self.current_ref, duration))
            except Exception as e:
                print("[CiefpChannelHistory] finalize error:", e)

        # Ako imamo pending i trajao je dovoljno — kreiraj novu sesiju
        if self.pending_ref and self.pending_start:
            duration = now - self.pending_start
            if duration >= self.min_watch:
                # === PRIKUPI METAPODATKE ===
                sat_pos = ""
                sat_name = ""
                try:
                    from .satellite_info import get_satellite_for_ref
                    sat_pos, sat_name = get_satellite_for_ref(self.pending_ref)
                except Exception as e:
                    print("[CiefpChannelHistory] satellite error:", e)

                caid = ""
                caid_name = ""
                caids_str = ""
                is_crypted = 0
                try:
                    from .caid_info import get_caids_for_service
                    ca = get_caids_for_service()
                    caid = ca.get("caid", "")
                    caid_name = ca.get("caid_name", "")
                    caids_str = ca.get("caids_str", "")
                    is_crypted = 1 if ca.get("is_crypted") else 0
                    print("[CiefpChannelHistory] CAID info: active=%s, all=%s, crypted=%s"
                          % (caid, caids_str, is_crypted))
                except Exception as e:
                    print("[CiefpChannelHistory] caid error:", e)

                # === KREIRAJ SESIJU ===
                sid = self.db.start_session(
                    self.pending_ref,
                    self.pending_name,
                    self.pending_provider,
                    self.pending_type,
                    self.pending_start,
                    satellite=sat_name,
                    satellite_pos=sat_pos,
                    caid=caid,
                    caid_name=caid_name,
                    caids_str=caids_str,
                    is_crypted=is_crypted,
                )
                if sid:
                    self.current_ref = self.pending_ref
                    self.current_session_id = sid
                    self.current_start = self.pending_start
                    self.current_name = self.pending_name
                    self.current_provider = self.pending_provider
                    self.current_type = self.pending_type
                    print("[CiefpChannelHistory] Session started: %s (id=%s, sat=%s, caid=%s)"
                          % (self.current_name or self.current_ref, sid, sat_pos, caid))

                # === PROVJERA PARENTAL LOCK ===
                try:
                    from .channel_info import is_parental_locked
                    from Components.config import config
                    if config.plugins.ciefpchannelhistory.filter_adult.value:
                        if is_parental_locked(self.pending_ref):
                            print("[CiefpChannelHistory] Skipping parental-locked channel: %s"
                                  % self.pending_ref)
                            self.pending_ref = None
                            self.pending_start = None
                            return
                except Exception as e:
                    print("[CiefpChannelHistory] parental check error:", e)

            # Reset pending
            self.pending_ref = None
            self.pending_start = None

    def commit_now(self):
        """Pozovi pri gašenju — finalizuj sve aktivno."""
        now = int(time.time())

        # Finalizuj aktivnu sesiju
        if self.current_session_id and self.current_ref:
            try:
                self.db.update_session(
                    self.current_session_id, self.current_ref, now)
                duration = now - (self.current_start or now)
                print("[CiefpChannelHistory] commit_now: %s (%ds)"
                      % (self.current_name or self.current_ref, duration))
            except Exception as e:
                print("[CiefpChannelHistory] commit_now error:", e)

        # Ako imamo pending >= min_watch — kreiraj sesiju
        if self.pending_ref and self.pending_start:
            duration = now - self.pending_start
            if duration >= self.min_watch:
                sat_pos = ""
                sat_name = ""
                try:
                    from .satellite_info import get_satellite_for_ref
                    sat_pos, sat_name = get_satellite_for_ref(self.pending_ref)
                except Exception:
                    pass

                caid = ""
                caid_name = ""
                caids_str = ""
                is_crypted = 0
                try:
                    from .caid_info import get_caids_for_service
                    ca = get_caids_for_service()
                    caid = ca.get("caid", "")
                    caid_name = ca.get("caid_name", "")
                    caids_str = ca.get("caids_str", "")
                    is_crypted = 1 if ca.get("is_crypted") else 0
                except Exception:
                    pass

                self.db.start_session(
                    self.pending_ref,
                    self.pending_name,
                    self.pending_provider,
                    self.pending_type,
                    self.pending_start,
                    satellite=sat_name,
                    satellite_pos=sat_pos,
                    caid=caid,
                    caid_name=caid_name,
                    caids_str=caids_str,
                    is_crypted=is_crypted,
                )
                # === PROVJERA PARENTAL LOCK ===
                try:
                    from .channel_info import is_parental_locked
                    from Components.config import config
                    if config.plugins.ciefpchannelhistory.filter_adult.value:
                        if is_parental_locked(self.pending_ref):
                            print("[CiefpChannelHistory] Skipping parental-locked channel (commit): %s"
                                  % self.pending_ref)
                            # Reset pending
                            self.pending_ref = None
                            self.pending_start = None
                            return
                except Exception as e:
                    print("[CiefpChannelHistory] parental check error:", e)

        # Reset
        self.current_ref = None
        self.current_session_id = None
        self.current_start = None
        self.pending_ref = None
        self.pending_start = None


# ---------------- STUB (kompatibilnost) ----------------
_tracker = None


def install_hook(tracker):
    if tracker:
        tracker.start()
    return True


def uninstall_hook():
    t = get_tracker()
    if t:
        t.stop()


def get_tracker():
    return _tracker


def set_tracker(t):
    global _tracker
    _tracker = t