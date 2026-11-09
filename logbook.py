#!/usr/bin/env python3
"""A record of everything that has passed over the house.

This is the part that makes the thing addictive rather than merely informative.
Nothing here needs anything extra from the APIs — it is all just remembering what
we have already seen.

    python3 logbook.py           # today, and the all-time highlights
    python3 logbook.py --all     # every airframe, most-seen first
"""

from __future__ import annotations

import os
import sqlite3
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))

# One pass overhead can span several polls. Anything sooner than this from the
# same airframe is the same visit, not a new one.
SAME_VISIT_SECONDS = 30 * 60

SCHEMA = """
CREATE TABLE IF NOT EXISTS sightings (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    icao          TEXT NOT NULL,
    registration  TEXT,
    callsign      TEXT,
    type_code     TEXT,
    model         TEXT,
    airline       TEXT,
    origin        TEXT,
    destination   TEXT,
    dest_name     TEXT,
    dest_nm_home  REAL,
    seen_at       REAL NOT NULL,
    day           TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_icao ON sightings (icao);
CREATE INDEX IF NOT EXISTS idx_day  ON sightings (day);
CREATE INDEX IF NOT EXISTS idx_airline ON sightings (airline);
"""


def _today() -> str:
    return time.strftime("%Y-%m-%d")


class Logbook:
    def __init__(self, config: dict):
        cache_dir = config.get("cache_dir", "cache")
        if not os.path.isabs(cache_dir):
            cache_dir = os.path.join(HERE, cache_dir)
        os.makedirs(cache_dir, exist_ok=True)
        self.path = os.path.join(cache_dir, "logbook.db")
        self.home = config.get("home", {})
        self.db = sqlite3.connect(self.path)
        self.db.row_factory = sqlite3.Row
        self.db.executescript(SCHEMA)
        self.db.commit()

    # ------------------------------------------------------------------
    def _distance_home(self, airport) -> float | None:
        if not airport:
            return None
        lat, lon = airport.get("lat"), airport.get("lon")
        if lat is None or lon is None:
            return None
        try:
            import geo
            return geo.haversine_nm(float(self.home["lat"]), float(self.home["lon"]),
                                    float(lat), float(lon))
        except Exception:
            return None

    def record(self, plane: dict) -> dict:
        """Log a sighting and return what is interesting about it.

        Safe to call on every poll — repeat calls inside SAME_VISIT_SECONDS are
        treated as the same pass and do not inflate the counts.
        """
        icao = plane.get("icao")
        if not icao:
            return {}

        now = time.time()
        cur = self.db.execute(
            "SELECT seen_at FROM sightings WHERE icao=? ORDER BY seen_at DESC LIMIT 1",
            (icao,))
        row = cur.fetchone()
        same_visit = bool(row and now - row["seen_at"] < SAME_VISIT_SECONDS)

        airline = (plane.get("airline") or "").strip()
        dest = plane.get("destination") or {}
        origin = plane.get("origin") or {}

        # Work these out *before* inserting, so "first ever" means first ever.
        #
        # Rows belonging to the visit already in progress are excluded, so the
        # answers stay stable for as long as this aircraft holds the screen. Get
        # this wrong and a "FIRST TIME" badge appears on one poll and vanishes on
        # the next, while the same plane is still up there.
        cutoff = now - SAME_VISIT_SECONDS
        not_this_visit = "AND NOT (icao = ? AND seen_at > ?)"
        exclude = (icao, cutoff)

        visits = self.db.execute(
            "SELECT COUNT(*) c FROM sightings WHERE icao=?", (icao,)).fetchone()["c"]
        airline_seen = 0
        if airline:
            airline_seen = self.db.execute(
                f"SELECT COUNT(*) c FROM sightings WHERE airline=? {not_this_visit}",
                (airline,) + exclude).fetchone()["c"]
        type_seen = 0
        if plane.get("type_code"):
            type_seen = self.db.execute(
                f"SELECT COUNT(*) c FROM sightings WHERE type_code=? {not_this_visit}",
                (plane["type_code"],) + exclude).fetchone()["c"]

        if not same_visit:
            self.db.execute(
                "INSERT INTO sightings (icao, registration, callsign, type_code, "
                "model, airline, origin, destination, dest_name, dest_nm_home, "
                "seen_at, day) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                (icao, plane.get("registration"), plane.get("callsign"),
                 plane.get("type_code"), plane.get("model"), airline,
                 origin.get("iata"), dest.get("iata"),
                 dest.get("city") or dest.get("name"),
                 self._distance_home(dest), now, _today()))
            self.db.commit()
            visits += 1

        return {
            "visit_number": visits,
            "new_airframe": visits == 1,
            "new_airline": bool(airline) and airline_seen == 0,
            "new_type": bool(plane.get("type_code")) and type_seen == 0,
            "same_visit": same_visit,
        }

    # ------------------------------------------------------------------
    def stats(self) -> dict:
        day = _today()
        q = self.db.execute

        today = q("SELECT COUNT(*) c FROM sightings WHERE day=?", (day,)).fetchone()["c"]
        types = q("SELECT COUNT(DISTINCT type_code) c FROM sightings "
                  "WHERE day=? AND type_code IS NOT NULL AND type_code<>''",
                  (day,)).fetchone()["c"]
        airlines = q("SELECT COUNT(DISTINCT airline) c FROM sightings "
                     "WHERE day=? AND airline IS NOT NULL AND airline<>''",
                     (day,)).fetchone()["c"]
        total = q("SELECT COUNT(*) c FROM sightings").fetchone()["c"]
        airframes = q("SELECT COUNT(DISTINCT icao) c FROM sightings").fetchone()["c"]

        furthest = q(
            "SELECT destination, dest_name, dest_nm_home FROM sightings "
            "WHERE day=? AND dest_nm_home IS NOT NULL "
            "ORDER BY dest_nm_home DESC LIMIT 1", (day,)).fetchone()

        busiest = q(
            "SELECT airline, COUNT(*) c FROM sightings "
            "WHERE day=? AND airline IS NOT NULL AND airline<>'' "
            "GROUP BY airline ORDER BY c DESC LIMIT 1", (day,)).fetchone()

        regular = q(
            "SELECT registration, type_code, COUNT(*) c FROM sightings "
            "WHERE registration IS NOT NULL AND registration<>'' "
            "GROUP BY icao ORDER BY c DESC LIMIT 1").fetchone()

        last = q("SELECT callsign, destination, seen_at FROM sightings "
                 "ORDER BY seen_at DESC LIMIT 1").fetchone()

        return {
            "today": today,
            "today_types": types,
            "today_airlines": airlines,
            "total": total,
            "airframes": airframes,
            "furthest": dict(furthest) if furthest else None,
            "busiest_airline": dict(busiest) if busiest else None,
            "most_regular": dict(regular) if regular else None,
            "last": dict(last) if last else None,
        }

    def close(self) -> None:
        try:
            self.db.close()
        except Exception:
            pass


# --------------------------------------------------------------------------

def main(argv: list) -> int:
    from tracker import load_config

    book = Logbook(load_config())
    s = book.stats()

    print(f"Today: {s['today']} aircraft, {s['today_types']} different types, "
          f"{s['today_airlines']} airlines")
    if s["furthest"]:
        f = s["furthest"]
        print(f"  furthest bound for {f['dest_name'] or f['destination']} "
              f"({(f['dest_nm_home'] or 0) * 1.15078:,.0f} miles away)")
    if s["busiest_airline"]:
        b = s["busiest_airline"]
        print(f"  most seen: {b['airline']} x{b['c']}")

    print(f"\nAll time: {s['total']} sightings, {s['airframes']} distinct airframes")
    if s["most_regular"]:
        r = s["most_regular"]
        print(f"  the regular: {r['registration']} ({r['type_code']}) x{r['c']}")

    if "--all" in argv[1:]:
        print("\nEvery airframe, most seen first:")
        rows = book.db.execute(
            "SELECT registration, type_code, model, airline, COUNT(*) c, "
            "MAX(seen_at) last FROM sightings GROUP BY icao ORDER BY c DESC")
        for row in rows:
            when = time.strftime("%d %b %H:%M", time.localtime(row["last"]))
            print(f"  {row['c']:4d}x  {row['registration'] or '?':10s} "
                  f"{row['type_code'] or '?':6s} {(row['airline'] or '')[:28]:28s} "
                  f"last {when}")

    book.close()
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
