#!/usr/bin/env python3
"""Find the aircraft currently overhead and look up who and what it is.

Three free services, no accounts, no keys:

  adsb.lol   /v2/point/{lat}/{lon}/{radius}   live positions near a point
  adsbdb.com /v0/callsign/{callsign}          airline + origin/destination
  adsbdb.com /v0/aircraft/{registration}      make, model, owner, photo

Run this file directly to print what is overhead without touching the display:

    python3 tracker.py
"""

from __future__ import annotations

import json
import os
import sys
import time
import urllib.error
import urllib.request

import geo

HERE = os.path.dirname(os.path.abspath(__file__))
USER_AGENT = "home-flight-tracker/1.0 (personal e-ink display)"

ADSB_POINT = "https://api.adsb.lol/v2/point/{lat}/{lon}/{radius}"
ADSBDB_CALLSIGN = "https://api.adsbdb.com/v0/callsign/{callsign}"
ADSBDB_AIRCRAFT = "https://api.adsbdb.com/v0/aircraft/{registration}"

ROUTE_TTL = 24 * 3600          # airlines and routes barely change
AIRFRAME_TTL = 30 * 24 * 3600  # a tail number's model never changes


# --------------------------------------------------------------------------
# config
# --------------------------------------------------------------------------

def load_config(path: str | None = None) -> dict:
    path = path or os.path.join(HERE, "config.json")
    with open(path, "r", encoding="utf-8") as fh:
        return json.load(fh)


# --------------------------------------------------------------------------
# a very small disk cache
# --------------------------------------------------------------------------

class Cache:
    """One JSON file per key. Deliberately dumb; it only has to survive reboots."""

    def __init__(self, root: str):
        self.root = root
        os.makedirs(root, exist_ok=True)

    def _path(self, namespace: str, key: str) -> str:
        safe = "".join(c if c.isalnum() or c in "-_" else "_" for c in key.upper())
        folder = os.path.join(self.root, namespace)
        os.makedirs(folder, exist_ok=True)
        return os.path.join(folder, safe + ".json")

    def get(self, namespace: str, key: str, ttl: float):
        path = self._path(namespace, key)
        try:
            if time.time() - os.path.getmtime(path) > ttl:
                return None
            with open(path, "r", encoding="utf-8") as fh:
                return json.load(fh)
        except (OSError, ValueError):
            return None

    def put(self, namespace: str, key: str, value) -> None:
        path = self._path(namespace, key)
        tmp = path + ".tmp"
        try:
            with open(tmp, "w", encoding="utf-8") as fh:
                json.dump(value, fh)
            os.replace(tmp, path)
        except OSError:
            pass

    def photo_path(self, registration: str) -> str:
        folder = os.path.join(self.root, "photos")
        os.makedirs(folder, exist_ok=True)
        safe = "".join(c if c.isalnum() else "_" for c in registration.upper())
        return os.path.join(folder, safe + ".img")


# --------------------------------------------------------------------------
# http
# --------------------------------------------------------------------------

def fetch_json(url: str, timeout: float = 8.0):
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT,
                                               "Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8", "replace"))


def fetch_bytes(url: str, timeout: float = 15.0) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read()


# --------------------------------------------------------------------------
# normalising one adsb.lol aircraft record
# --------------------------------------------------------------------------

def _num(value):
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def normalise(ac: dict) -> dict:
    """adsb.lol gives us short, terse keys. Turn one into something readable.

    Keys that matter:
      hex       ICAO 24-bit address
      flight    callsign, space padded
      r         registration / tail number
      t         ICAO type code (A21N, B738 ...)
      alt_baro  barometric altitude in feet, or the string "ground"
      gs        ground speed in knots
      track     the direction the aircraft is pointing
      dst       distance from the point we queried, nautical miles
      dir       bearing from that point to the aircraft, degrees true
    """
    alt_raw = ac.get("alt_baro")
    on_ground = (alt_raw == "ground")
    altitude = None if on_ground else _num(alt_raw)
    if altitude is None and not on_ground:
        altitude = _num(ac.get("alt_geom"))

    callsign = (ac.get("flight") or "").strip().upper()
    flags = int(_num(ac.get("dbFlags")) or 0)

    nav_modes = ac.get("nav_modes")
    if isinstance(nav_modes, str):
        nav_modes = [nav_modes]

    return {
        "icao": (ac.get("hex") or "").strip().lower(),
        "callsign": callsign,
        "registration": (ac.get("r") or "").strip().upper(),
        "type_code": (ac.get("t") or "").strip().upper(),
        "altitude_ft": altitude,
        "on_ground": on_ground,
        "speed_kt": _num(ac.get("gs")),
        "track_deg": _num(ac.get("track")),
        "vertical_fpm": _num(ac.get("baro_rate")) or _num(ac.get("geom_rate")),
        "distance_nm": _num(ac.get("dst")),
        "bearing_deg": _num(ac.get("dir")),
        "squawk": (ac.get("squawk") or "").strip(),
        "lat": _num(ac.get("lat")),
        "lon": _num(ac.get("lon")),
        "seen_at": time.time(),

        # The interesting half, which the first version threw away.
        "mach": _num(ac.get("mach")),
        "ias_kt": _num(ac.get("ias")),
        "tas_kt": _num(ac.get("tas")),
        "oat_c": _num(ac.get("oat")),                  # outside air temperature
        "wind_from_deg": _num(ac.get("wd")),           # direction it blows FROM
        "wind_kt": _num(ac.get("ws")),
        "roll_deg": _num(ac.get("roll")),              # negative is a left bank
        "selected_alt_ft": (_num(ac.get("nav_altitude_mcp"))
                            or _num(ac.get("nav_altitude_fms"))),
        "nav_modes": nav_modes or [],
        "category": (ac.get("category") or "").strip().upper(),
        "emergency": (ac.get("emergency") or "").strip().lower(),
        "description": (ac.get("desc") or "").strip(),
        "operator": (ac.get("ownOp") or "").strip(),
        "year_built": (str(ac.get("year")).strip() if ac.get("year") else ""),

        # dbFlags is a bitfield: 1 military, 2 interesting, 4 PIA, 8 LADD
        "is_military": bool(flags & 1),
        "is_interesting": bool(flags & 2),
    }


# --------------------------------------------------------------------------
# what makes an aircraft worth looking up from your book
# --------------------------------------------------------------------------

# Four-engined widebodies and the genuinely unusual. Not a complete list — it is
# a list of things worth walking to the window for.
NOTABLE_TYPES = {
    "A388": "AIRBUS A380",
    "B748": "BOEING 747-8",
    "B744": "BOEING 747-400",
    "B742": "BOEING 747-200",
    "B741": "BOEING 747-100",
    "B74S": "BOEING 747SP",
    "A342": "AIRBUS A340", "A343": "AIRBUS A340",
    "A345": "AIRBUS A340-500", "A346": "AIRBUS A340-600",
    "MD11": "MD-11", "DC10": "DC-10",
    "A124": "ANTONOV AN-124", "A225": "ANTONOV AN-225", "AN22": "ANTONOV AN-22",
    "C5M": "C-5 GALAXY", "C17": "C-17 GLOBEMASTER", "B52": "B-52",
    "K35R": "KC-135 TANKER", "E3TF": "E-3 SENTRY", "P8": "P-8 POSEIDON",
    "C130": "C-130 HERCULES", "C30J": "C-130J HERCULES",
    "B462": "AVRO RJ", "CONC": "CONCORDE",
}

# Emitter categories worth calling out by name.
CATEGORY_LABELS = {
    "A5": "HEAVY",
    "A7": "HELICOPTER",
    "B1": "GLIDER",
    "B2": "BALLOON",
    "B4": "ULTRALIGHT",
    "B6": "DRONE",
    "B7": "SPACECRAFT",
}

EMERGENCY_SQUAWKS = {
    "7500": "HIJACK",
    "7600": "RADIO FAILURE",
    "7700": "EMERGENCY",
}


def classify(plane: dict) -> list:
    """Badges worth putting on the screen. Most aircraft get none."""
    notes = []

    squawk = plane.get("squawk") or ""
    if squawk in EMERGENCY_SQUAWKS:
        notes.append({"tag": EMERGENCY_SQUAWKS[squawk], "level": "alert"})
    emergency = plane.get("emergency") or ""
    if emergency and emergency not in ("none", "no_emergency"):
        notes.append({"tag": emergency.replace("_", " ").upper(), "level": "alert"})

    if plane.get("is_military"):
        notes.append({"tag": "MILITARY", "level": "rare"})
    if plane.get("is_interesting"):
        notes.append({"tag": "NOTABLE", "level": "rare"})

    type_code = plane.get("type_code") or ""
    if type_code in NOTABLE_TYPES:
        notes.append({"tag": NOTABLE_TYPES[type_code], "level": "rare"})

    label = CATEGORY_LABELS.get(plane.get("category") or "")
    if label and not any(n["tag"] == label for n in notes):
        notes.append({"tag": label, "level": "info"})

    # de-duplicate, keeping the most severe first
    order = {"alert": 0, "rare": 1, "info": 2}
    seen, unique = set(), []
    for note in sorted(notes, key=lambda n: order.get(n["level"], 9)):
        if note["tag"] not in seen:
            seen.add(note["tag"])
            unique.append(note)
    return unique[:3]


# --------------------------------------------------------------------------
# the tracker
# --------------------------------------------------------------------------

class Tracker:
    """Holds the stickiness state between polls, so keep one instance around."""

    def __init__(self, config: dict):
        self.cfg = config
        cache_dir = config.get("cache_dir", "cache")
        if not os.path.isabs(cache_dir):
            cache_dir = os.path.join(HERE, cache_dir)
        self.cache = Cache(cache_dir)
        self.current_icao = None
        self.current_since = 0.0
        self.last_error = None

    # -- live positions ---------------------------------------------------

    def nearby_raw(self) -> list:
        home = self.cfg["home"]
        url = ADSB_POINT.format(lat=round(float(home["lat"]), 5),
                                lon=round(float(home["lon"]), 5),
                                radius=int(self.cfg.get("radius_nm", 15)))
        timeout = float(self.cfg.get("http_timeout_seconds", 8))
        data = fetch_json(url, timeout=timeout)
        return data.get("ac") or data.get("aircraft") or []

    def nearby(self) -> list:
        return [normalise(ac) for ac in self.nearby_raw()]

    def eligible(self, planes: list) -> list:
        cfg = self.cfg
        max_alt = cfg.get("max_altitude_ft")
        min_alt = cfg.get("min_altitude_ft") or 0
        out = []
        for p in planes:
            if p["distance_nm"] is None:
                continue
            if cfg.get("ignore_on_ground", True) and p["on_ground"]:
                continue
            alt = p["altitude_ft"]
            if alt is not None:
                if max_alt and alt > max_alt:
                    continue
                if alt < min_alt:
                    continue
            out.append(p)
        out.sort(key=lambda p: p["distance_nm"])
        return out

    # -- which one gets the screen ---------------------------------------

    def choose(self, planes: list):
        """Nearest wins, but an incumbent keeps the screen for a while.

        Without this two aircraft at similar distance trade places every poll,
        and every swap is a visible full-screen flash on e-ink.
        """
        if not planes:
            self.current_icao = None
            return None

        now = time.time()
        nearest = planes[0]
        hold = float(self.cfg.get("sticky_hold_seconds", 90))
        margin = float(self.cfg.get("sticky_beat_margin_nm", 3.0))

        incumbent = next((p for p in planes if p["icao"] == self.current_icao), None)
        if incumbent is not None and incumbent is not nearest:
            held_for = now - self.current_since
            beaten_by = incumbent["distance_nm"] - nearest["distance_nm"]
            if held_for < hold and beaten_by < margin:
                return incumbent

        if nearest["icao"] != self.current_icao:
            self.current_icao = nearest["icao"]
            self.current_since = now
        return nearest

    # -- who and what is it ----------------------------------------------

    def route_for(self, callsign: str):
        if not callsign:
            return None
        cached = self.cache.get("routes", callsign, ROUTE_TTL)
        if cached is not None:
            return cached or None

        timeout = float(self.cfg.get("http_timeout_seconds", 8))
        try:
            data = fetch_json(ADSBDB_CALLSIGN.format(callsign=callsign), timeout)
        except urllib.error.HTTPError as exc:
            if exc.code == 404:
                self.cache.put("routes", callsign, {})  # remember the miss too
            return None
        except Exception:
            return None

        fr = ((data or {}).get("response") or {})
        fr = fr.get("flightroute") if isinstance(fr, dict) else None
        if not fr:
            self.cache.put("routes", callsign, {})
            return None

        def airport(node):
            node = node or {}
            return {
                "iata": node.get("iata_code") or "",
                "icao": node.get("icao_code") or "",
                "name": node.get("name") or "",
                "city": node.get("municipality") or "",
                "country": node.get("country_name") or node.get("country_iso_name") or "",
                # These are what make route progress and ETA possible.
                "lat": node.get("latitude"),
                "lon": node.get("longitude"),
                "elevation_ft": node.get("elevation"),
            }

        airline = fr.get("airline") or {}
        route = {
            "airline": (airline.get("name") or "").strip(),
            "airline_iata": (airline.get("iata") or "").strip(),
            "airline_country": (airline.get("country") or "").strip(),
            # The name air traffic control actually says out loud: BAW286 is
            # "Speedbird 286". Much better on a wall than an ICAO code.
            "radio_callsign": (airline.get("callsign") or "").strip().title(),
            "flight_number": (fr.get("callsign_iata") or "").strip(),
            "origin": airport(fr.get("origin")),
            "destination": airport(fr.get("destination")),
        }
        self.cache.put("routes", callsign, route)
        return route

    def airframe_for(self, registration: str):
        if not registration:
            return None
        cached = self.cache.get("airframes", registration, AIRFRAME_TTL)
        if cached is not None:
            return cached or None

        timeout = float(self.cfg.get("http_timeout_seconds", 8))
        try:
            data = fetch_json(ADSBDB_AIRCRAFT.format(registration=registration), timeout)
        except urllib.error.HTTPError as exc:
            if exc.code == 404:
                self.cache.put("airframes", registration, {})
            return None
        except Exception:
            return None

        ac = ((data or {}).get("response") or {})
        ac = ac.get("aircraft") if isinstance(ac, dict) else None
        if not ac:
            self.cache.put("airframes", registration, {})
            return None

        airframe = {
            "type": (ac.get("type") or "").strip(),
            "manufacturer": (ac.get("manufacturer") or "").strip(),
            "icao_type": (ac.get("icao_type") or "").strip(),
            "owner": (ac.get("registered_owner") or "").strip(),
            "owner_country": (ac.get("registered_owner_country_name") or "").strip(),
            "photo_url": (ac.get("url_photo_thumbnail") or ac.get("url_photo") or ""),
        }
        self.cache.put("airframes", registration, airframe)
        return airframe

    def photo_for(self, registration: str, url: str):
        """Download once per tail number, then it lives on disk forever."""
        if not (registration and url and self.cfg.get("show_photo", True)):
            return None
        path = self.cache.photo_path(registration)
        if os.path.exists(path) and os.path.getsize(path) > 0:
            return path
        try:
            blob = fetch_bytes(url, timeout=float(self.cfg.get("http_timeout_seconds", 8)) * 2)
        except Exception:
            return None
        if not blob:
            return None
        try:
            with open(path, "wb") as fh:
                fh.write(blob)
        except OSError:
            return None
        return path

    def enrich(self, plane: dict) -> dict:
        route = self.route_for(plane["callsign"])
        airframe = self.airframe_for(plane["registration"])

        plane = dict(plane)
        plane["airline"] = (route or {}).get("airline", "")
        plane["airline_country"] = (route or {}).get("airline_country", "")
        plane["radio_callsign"] = (route or {}).get("radio_callsign", "")
        plane["flight_number"] = (route or {}).get("flight_number", "")
        plane["origin"] = (route or {}).get("origin")
        plane["destination"] = (route or {}).get("destination")

        # How far along the route it is, and roughly when it lands.
        plane["progress"] = geo.route_progress(
            plane.get("origin"), plane.get("destination"),
            plane.get("lat"), plane.get("lon"), plane.get("speed_kt"))

        # Head or tail component of the wind up there.
        plane["wind"] = geo.wind_relative(
            plane.get("track_deg"), plane.get("wind_from_deg"), plane.get("wind_kt"))

        plane["notes"] = classify(plane)

        if airframe:
            model = " ".join(x for x in (airframe.get("manufacturer"),
                                         airframe.get("type")) if x).strip()
            plane["model"] = model or plane["type_code"]
            plane["owner"] = airframe.get("owner", "")
            plane["photo"] = self.photo_for(plane["registration"],
                                            airframe.get("photo_url", ""))
        else:
            plane["model"] = plane["type_code"]
            plane["owner"] = ""
            plane["photo"] = None

        if not plane["airline"] and plane["owner"]:
            plane["airline"] = plane["owner"]
        return plane

    # -- the one call run.py makes ---------------------------------------

    def current(self):
        """Returns (plane_or_None, count_in_sky). Never raises."""
        try:
            planes = self.eligible(self.nearby())
            self.last_error = None
        except Exception as exc:                     # network flakiness is normal
            self.last_error = f"{type(exc).__name__}: {exc}"
            return None, 0

        chosen = self.choose(planes)
        if chosen is None:
            return None, 0
        return self.enrich(chosen), len(planes)


# --------------------------------------------------------------------------
# command line
# --------------------------------------------------------------------------

def probe_fields(tracker: Tracker) -> int:
    """Which fields does your sky actually deliver?

    The API documents plenty of optional fields; which ones arrive depends on
    the aircraft's equipment and on what the receivers near you picked up. This
    counts them over the aircraft currently in range so we build against what is
    really there rather than what is theoretically possible.
    """
    try:
        raw = tracker.nearby_raw()
    except Exception as exc:
        print(f"could not reach the data source: {type(exc).__name__}: {exc}")
        return 1

    if not raw:
        print("nothing in range — try again in a few minutes, or raise radius_nm")
        return 0

    counts, examples = {}, {}
    for ac in raw:
        for key, value in ac.items():
            if value in (None, "", []):
                continue
            counts[key] = counts.get(key, 0) + 1
            examples.setdefault(key, value)

    print(f"{len(raw)} aircraft in range. Fields present, and in how many:\n")
    for key in sorted(counts, key=lambda k: (-counts[k], k)):
        sample = str(examples[key])
        if len(sample) > 42:
            sample = sample[:39] + "..."
        share = counts[key] / len(raw)
        print(f"  {key:20s} {counts[key]:3d}/{len(raw)} "
              f"{'█' * int(share * 10):<10s} e.g. {sample}")

    wanted = ["mach", "oat", "ws", "wd", "nav_altitude_mcp", "nav_modes",
              "category", "dbFlags", "desc", "ownOp", "year", "ias", "tas", "roll"]
    missing = [w for w in wanted if w not in counts]
    if missing:
        print(f"\nNot seen in this sample: {', '.join(missing)}")
        print("Some of these only appear at cruise altitude, or on newer "
              "transponders.\nRun it again when something big is overhead "
              "before concluding they never arrive.")
    return 0


def main() -> int:
    cfg = load_config()
    tracker = Tracker(cfg)
    home = cfg["home"]

    if "--fields" in sys.argv[1:]:
        return probe_fields(tracker)
    print(f"Looking {cfg.get('radius_nm', 15)} nm around "
          f"{home['lat']}, {home['lon']} ...\n")

    plane, count = tracker.current()
    if tracker.last_error:
        print("Could not reach the data source.")
        print("  " + tracker.last_error)
        print("\nCheck the Pi is on the network: ping -c1 api.adsb.lol")
        return 1

    if plane is None:
        print("Nothing in the sky.")
        print("If that keeps happening, raise radius_nm in config.json, or check")
        print("your latitude and longitude are not swapped.")
        return 0

    origin = plane.get("origin") or {}
    dest = plane.get("destination") or {}
    print(f"{count} aircraft in range. Showing the one that would be on screen:\n")
    print(f"  callsign     {plane['callsign'] or '—'}")
    print(f"  airline      {plane['airline'] or '—'}")
    print(f"  route        {origin.get('iata') or '???'} → {dest.get('iata') or '???'}"
          f"   {origin.get('city') or ''} → {dest.get('city') or ''}")
    print(f"  aircraft     {plane['model'] or '—'}  ({plane['registration'] or '—'})")
    print(f"  altitude     {plane['altitude_ft'] or 0:,.0f} ft")
    print(f"  speed        {plane['speed_kt'] or 0:,.0f} kt")
    print(f"  distance     {plane['distance_nm']:.1f} nm")
    print(f"  bearing      {plane['bearing_deg'] or 0:.0f}°")
    print(f"  photo        {plane.get('photo') or 'none'}")

    if plane.get("radio_callsign"):
        print(f"  on the radio {plane['radio_callsign']} "
              f"{(plane.get('flight_number') or plane['callsign'])[-4:].lstrip('0')}")

    progress = plane.get("progress")
    if progress:
        print(f"  progress     {progress['fraction'] * 100:.0f}% of "
              f"{progress['total_nm']:,.0f} nm, {progress['remaining_nm']:,.0f} nm left"
              + (f", {geo.format_duration(progress.get('eta_seconds'))} to run"
                 if progress.get("eta_seconds") else ""))

    extras = []
    if plane.get("mach"):
        extras.append(f"M{plane['mach']:.2f}")
    if plane.get("oat_c") is not None:
        extras.append(f"{plane['oat_c']:.0f}°C outside")
    if plane.get("wind"):
        w = plane["wind"]
        extras.append(f"{w['magnitude_kt']:.0f} kt {w['label'].lower()}")
    if plane.get("selected_alt_ft"):
        extras.append(f"set for {plane['selected_alt_ft']:,.0f} ft")
    if plane.get("year_built"):
        extras.append(f"built {plane['year_built']}")
    if extras:
        print(f"  telemetry    {' · '.join(extras)}")

    if plane.get("notes"):
        print(f"  flags        {', '.join(n['tag'] for n in plane['notes'])}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
