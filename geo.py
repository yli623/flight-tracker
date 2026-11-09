#!/usr/bin/env python3
"""Great-circle maths, so we can say how far along a flight is.

adsbdb hands us latitude and longitude for both airports. That is enough to work
out where along the route the aircraft actually is — which turns a static "SFO →
LHR" into "SFO → LHR, 62% there, 3h 40m to go".
"""

from __future__ import annotations

import math

EARTH_NM = 3440.065          # mean earth radius in nautical miles


def haversine_nm(lat1, lon1, lat2, lon2) -> float:
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = p2 - p1
    dl = math.radians(lon2 - lon1)
    a = (math.sin(dp / 2) ** 2
         + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2)
    return 2 * EARTH_NM * math.asin(min(1.0, math.sqrt(a)))


def bearing_deg(lat1, lon1, lat2, lon2) -> float:
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dl = math.radians(lon2 - lon1)
    y = math.sin(dl) * math.cos(p2)
    x = math.cos(p1) * math.sin(p2) - math.sin(p1) * math.cos(p2) * math.cos(dl)
    return (math.degrees(math.atan2(y, x)) + 360) % 360


def _coords(airport):
    """adsbdb gives latitude/longitude on each airport. Returns None if missing."""
    if not airport:
        return None
    lat, lon = airport.get("lat"), airport.get("lon")
    if lat is None or lon is None:
        return None
    try:
        return float(lat), float(lon)
    except (TypeError, ValueError):
        return None


def route_progress(origin, destination, lat, lon, ground_speed_kt=None):
    """How far along the great circle from origin to destination we are.

    Projects the aircraft onto the route line (along-track distance) rather than
    just comparing distances, so a flight that has drifted off the direct line —
    which is most of them — still reports sensibly.

    Returns None when either airport has no coordinates.
    """
    a = _coords(origin)
    b = _coords(destination)
    if not (a and b) or lat is None or lon is None:
        return None

    total = haversine_nm(a[0], a[1], b[0], b[1])
    if total < 1:
        return None

    d13 = haversine_nm(a[0], a[1], lat, lon)
    t13 = math.radians(bearing_deg(a[0], a[1], lat, lon))
    t12 = math.radians(bearing_deg(a[0], a[1], b[0], b[1]))

    # cross-track distance: how far off the direct line the aircraft sits
    cross = math.asin(math.sin(d13 / EARTH_NM) * math.sin(t13 - t12)) * EARTH_NM
    # along-track distance: how far along the line that puts it
    ratio = math.cos(d13 / EARTH_NM) / math.cos(cross / EARTH_NM)
    along = math.acos(max(-1.0, min(1.0, ratio))) * EARTH_NM
    if abs(t13 - t12) > math.pi / 2:
        along = -along                      # still short of the origin

    fraction = max(0.0, min(1.0, along / total))
    remaining = max(0.0, total - along)

    result = {
        "total_nm": total,
        "flown_nm": max(0.0, along),
        "remaining_nm": remaining,
        "off_track_nm": abs(cross),
        "fraction": fraction,
    }

    if ground_speed_kt and ground_speed_kt > 40:
        result["eta_seconds"] = remaining / ground_speed_kt * 3600.0
    return result


def format_duration(seconds) -> str:
    if seconds is None:
        return ""
    seconds = max(0, int(seconds))
    hours, minutes = divmod(seconds // 60, 60)
    if hours and minutes:
        return f"{hours}h {minutes:02d}m"
    if hours:
        return f"{hours}h"
    return f"{minutes}m"


def wind_relative(track_deg, wind_from_deg, wind_speed_kt):
    """Head or tail component of the wind, relative to where the plane is going.

    `wd` is the direction the wind blows *from*, which is the aviation
    convention and the opposite of what you would guess.
    """
    if None in (track_deg, wind_from_deg, wind_speed_kt):
        return None
    angle = math.radians((wind_from_deg - track_deg + 180) % 360)
    along = wind_speed_kt * math.cos(angle)     # positive = tailwind
    across = wind_speed_kt * math.sin(angle)
    return {
        "component_kt": along,
        "cross_kt": abs(across),
        "label": "TAILWIND" if along >= 0 else "HEADWIND",
        "magnitude_kt": abs(along),
    }
