#!/usr/bin/env python3
"""Draw the 800x480 card.

Everything is drawn in PIL mode "1" — one bit per pixel, no greys — which is
exactly what the panel can show. That means the preview PNG can never flatter
the real thing.

Two layouts, chosen by `layout` in config.json:

  "alternate"  the flight card most of the time, swapping every few refreshes
               to a detail card with the photo, the telemetry and the day's
               tally. Each screen stays readable.
  "dense"      everything on one screen in smaller type.
"""

from __future__ import annotations

import math
import os
import time

from PIL import Image, ImageDraw, ImageFont

WIDTH, HEIGHT = 800, 480
BLACK, WHITE = 0, 1          # mode "1": 0 is ink, 1 is paper

MARGIN = 22

# DejaVu is what the Pi has. The macOS paths are here so the whole thing can be
# run on a Mac before any hardware exists — the layout shifts a hair because the
# metrics differ, but everything fits.
FONT_DIRS = [
    "/usr/share/fonts/truetype/dejavu",
    "/usr/share/fonts/dejavu",
    "/System/Library/Fonts/Supplemental",
    "/System/Library/Fonts",
    "/Library/Fonts",
]
FONT_FILES = {
    "regular": ["DejaVuSans.ttf", "Arial.ttf", "Helvetica.ttc"],
    "bold": ["DejaVuSans-Bold.ttf", "Arial Bold.ttf", "Arial-Bold.ttf",
             "Helvetica.ttc"],
    "condensed": ["DejaVuSansCondensed.ttf", "Arial Narrow.ttf",
                  "DejaVuSans.ttf", "Arial.ttf"],
    "mono": ["DejaVuSansMono.ttf", "Menlo.ttc", "Courier New.ttf",
             "Courier.ttc"],
}
_font_cache: dict = {}


def font(size: int, style: str = "regular"):
    key = (size, style)
    if key in _font_cache:
        return _font_cache[key]
    for directory in FONT_DIRS:
        for name in FONT_FILES.get(style, FONT_FILES["regular"]):
            path = os.path.join(directory, name)
            if os.path.exists(path):
                try:
                    f = ImageFont.truetype(path, size)
                    _font_cache[key] = f
                    return f
                except OSError:
                    continue
    f = ImageFont.load_default()
    _font_cache[key] = f
    return f


# --------------------------------------------------------------------------
# small helpers
# --------------------------------------------------------------------------

def text_size(draw, text, fnt):
    if not text:
        return 0, 0
    left, top, right, bottom = draw.textbbox((0, 0), text, font=fnt)
    return right - left, bottom - top


def draw_text(draw, xy, text, fnt, anchor="la", fill=BLACK):
    if text:
        draw.text(xy, text, font=fnt, fill=fill, anchor=anchor)


def fit_text(draw, text, style, max_width, max_size, min_size=12):
    """Shrink until it fits. Long airline names are the usual offender."""
    size = max_size
    while size > min_size:
        fnt = font(size, style)
        if text_size(draw, text, fnt)[0] <= max_width:
            return fnt
        size -= 2
    return font(min_size, style)


def truncate(draw, text, fnt, max_width):
    if not text:
        return ""
    if text_size(draw, text, fnt)[0] <= max_width:
        return text
    ell = "…"
    while text and text_size(draw, text + ell, fnt)[0] > max_width:
        text = text[:-1]
    return text.rstrip() + ell


COMPASS_POINTS = ["N", "NNE", "NE", "ENE", "E", "ESE", "SE", "SSE",
                  "S", "SSW", "SW", "WSW", "W", "WNW", "NW", "NNW"]


def compass_point(degrees) -> str:
    if degrees is None:
        return ""
    return COMPASS_POINTS[int((float(degrees) % 360) / 22.5 + 0.5) % 16]


def units_for(config: dict):
    if str(config.get("units", "imperial")).lower().startswith("met"):
        return {"dist": (1.852, "km"), "speed": (1.852, "km/h")}
    return {"dist": (1.15078, "mi"), "speed": (1.15078, "mph")}


def flight_number(plane: dict) -> str:
    """UAL1287 -> 1287. Used with the radio callsign: "United 1287"."""
    iata = plane.get("flight_number") or ""
    source = iata or plane.get("callsign") or ""
    digits = "".join(c for c in source if c.isdigit()).lstrip("0")
    return digits


# --------------------------------------------------------------------------
# reusable pieces
# --------------------------------------------------------------------------

def draw_badges(draw, xy, notes, size=15, anchor_right=False):
    """Alert chips. Inverted for anything urgent, outlined otherwise."""
    if not notes:
        return 0
    x, y = xy
    fnt = font(size, "bold")
    height = size + 10
    drawn = []
    for note in notes:
        label = note["tag"]
        width = text_size(draw, label, fnt)[0] + 18
        drawn.append((label, width, note.get("level", "info")))

    if anchor_right:
        x -= sum(w for _, w, _ in drawn) + 8 * (len(drawn) - 1)

    for label, width, level in drawn:
        box = (x, y, x + width, y + height)
        if level == "alert":
            draw.rectangle(box, fill=BLACK)
            draw_text(draw, (x + width / 2, y + height / 2), label, fnt,
                      anchor="mm", fill=WHITE)
        else:
            draw.rectangle(box, outline=BLACK, width=2)
            draw_text(draw, (x + width / 2, y + height / 2), label, fnt,
                      anchor="mm")
        x += width + 8
    return height


def draw_progress(draw, box, fraction):
    """The route as a line, with a marker showing how far along it is."""
    x0, y, x1, _ = box
    draw.line((x0, y, x1, y), fill=BLACK, width=2)
    for end in (x0, x1):
        draw.line((end, y - 7, end, y + 7), fill=BLACK, width=3)

    if fraction is None:
        return
    marker = x0 + (x1 - x0) * max(0.0, min(1.0, fraction))
    draw.line((x0, y, marker, y), fill=BLACK, width=6)

    # a small aeroplane-ish wedge at the marker, pointing along the route
    size = 11
    draw.polygon([(marker + size, y),
                  (marker - size * 0.7, y - size * 0.8),
                  (marker - size * 0.2, y),
                  (marker - size * 0.7, y + size * 0.8)], fill=BLACK)


def draw_photo(image, draw, box, path):
    """Floyd-Steinberg dithered aircraft photo, cropped to fill the box."""
    x0, y0, x1, y1 = box
    w, h = x1 - x0, y1 - y0
    try:
        photo = Image.open(path)
        photo.load()
        photo = photo.convert("L")
    except Exception:
        return False

    scale = max(w / photo.width, h / photo.height)
    new = (max(1, int(photo.width * scale)), max(1, int(photo.height * scale)))
    photo = photo.resize(new, Image.LANCZOS)
    left = (photo.width - w) // 2
    top = (photo.height - h) // 2
    photo = photo.crop((left, top, left + w, top + h))
    photo = photo.convert("1", dither=Image.FLOYDSTEINBERG)

    image.paste(photo, (x0, y0))
    draw.rectangle(box, outline=BLACK, width=2)
    return True


def draw_compass(draw, centre, radius, bearing, label_font):
    cx, cy = centre
    draw.ellipse((cx - radius, cy - radius, cx + radius, cy + radius),
                 outline=BLACK, width=2)

    for i in range(16):
        angle = math.radians(i * 22.5 - 90)
        inner = radius - (11 if i == 0 else 5)
        draw.line((cx + inner * math.cos(angle), cy + inner * math.sin(angle),
                   cx + (radius - 2) * math.cos(angle),
                   cy + (radius - 2) * math.sin(angle)),
                  fill=BLACK, width=3 if i % 4 == 0 else 1)
    draw_text(draw, (cx, cy - radius - 13), "N", label_font, anchor="mm")

    if bearing is None:
        draw_text(draw, (cx, cy), "?", font(28, "bold"), anchor="mm")
        return

    angle = math.radians(float(bearing) - 90)
    tip = (cx + (radius - 16) * math.cos(angle), cy + (radius - 16) * math.sin(angle))
    tail = (cx - (radius - 34) * math.cos(angle), cy - (radius - 34) * math.sin(angle))
    draw.line((tail[0], tail[1], tip[0], tip[1]), fill=BLACK, width=5)

    head = math.radians(24)
    for sign in (1, -1):
        a = angle + math.pi + sign * head
        draw.line((tip[0], tip[1],
                   tip[0] + 20 * math.cos(a), tip[1] + 20 * math.sin(a)),
                  fill=BLACK, width=5)
    draw.ellipse((tail[0] - 4, tail[1] - 4, tail[0] + 4, tail[1] + 4), fill=BLACK)


def draw_stat(draw, box, label, value, unit, value_size=42, label_size=14):
    """Label on top, then the number and its unit sharing one baseline."""
    x0, y0, x1, y1 = box
    cx = (x0 + x1) // 2
    unit_font = font(max(11, int(value_size * 0.38)))
    unit_w = draw.textlength(" " + unit, font=unit_font) if unit else 0

    value_font = fit_text(draw, value, "bold", (x1 - x0) - 20 - unit_w,
                          value_size, 18)
    value_w = draw.textlength(value, font=value_font)

    draw_text(draw, (cx, y0), label, font(label_size, "bold"), anchor="ma")

    left = cx - (value_w + unit_w) / 2
    draw_text(draw, (left, y1), value, value_font, anchor="ls")
    if unit:
        draw_text(draw, (left + value_w + 5, y1), unit, unit_font, anchor="ls")


# --------------------------------------------------------------------------
# the values that go in the cells
# --------------------------------------------------------------------------

def main_stats(plane: dict, config: dict) -> list:
    units = units_for(config)
    d_factor, d_unit = units["dist"]
    s_factor, s_unit = units["speed"]

    alt = plane.get("altitude_ft")
    speed = plane.get("speed_kt")
    dist = plane.get("distance_nm")
    return [
        ("ALTITUDE", f"{alt:,.0f}" if alt else "GROUND", "ft" if alt else ""),
        ("SPEED", f"{speed * s_factor:,.0f}" if speed else "—",
         s_unit if speed else ""),
        ("DISTANCE", f"{dist * d_factor:.1f}" if dist is not None else "—",
         d_unit if dist is not None else ""),
    ]


def telemetry_cells(plane: dict) -> list:
    """The flight-nerd numbers. Only the ones this aircraft actually reports."""
    cells = []

    if plane.get("mach"):
        cells.append(("MACH", f"{plane['mach']:.2f}", ""))

    oat = plane.get("oat_c")
    if oat is not None:
        cells.append(("OUTSIDE AIR", f"{oat:.0f}°", "C"))

    wind = plane.get("wind")
    if wind and wind["magnitude_kt"] >= 5:
        cells.append((wind["label"], f"{wind['magnitude_kt']:.0f}", "kt"))

    rate = plane.get("vertical_fpm")
    if rate and abs(rate) >= 200:
        arrow = "▲" if rate > 0 else "▼"
        cells.append(("CLIMBING" if rate > 0 else "DESCENDING",
                      f"{arrow}{abs(rate):,.0f}", "fpm"))

    selected = plane.get("selected_alt_ft")
    altitude = plane.get("altitude_ft")
    if selected and altitude and abs(selected - altitude) > 400:
        cells.append(("LEVELLING AT", f"{selected:,.0f}", "ft"))

    if not cells and plane.get("tas_kt"):
        cells.append(("TRUE AIRSPEED", f"{plane['tas_kt']:,.0f}", "kt"))
    return cells


def aircraft_line(plane: dict) -> str:
    parts = [plane.get("registration") or "", plane.get("type_code") or ""]
    if plane.get("year_built"):
        parts.append(plane["year_built"])
    return "  ·  ".join(p for p in parts if p)


def logbook_line(book: dict | None, stats: dict | None) -> str:
    """One line of context: is this a stranger, and how busy has today been."""
    if not book:
        return ""
    bits = []
    if book.get("new_airframe"):
        bits.append("FIRST SIGHTING of this airframe")
    else:
        n = book.get("visit_number") or 0
        suffix = "th" if 10 <= n % 100 <= 20 else {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th")
        bits.append(f"{n}{suffix} visit")
    if book.get("new_airline"):
        bits.append("new airline")
    elif book.get("new_type"):
        bits.append("new type")
    if stats and stats.get("today"):
        bits.append(f"{stats['today']} today")
    return "  ·  ".join(bits)


# --------------------------------------------------------------------------
# card 1 — the flight
# --------------------------------------------------------------------------

def draw_header(image, draw, plane, count, note, right_limit=WIDTH - MARGIN):
    callsign = plane.get("callsign") or plane.get("registration") or "UNKNOWN"
    cs_font = fit_text(draw, callsign, "bold", 300, 52, 30)
    draw_text(draw, (MARGIN, 14), callsign, cs_font)

    radio = plane.get("radio_callsign") or ""
    if radio:
        spoken = f"{radio} {flight_number(plane)}".strip()
        draw_text(draw, (MARGIN + 3, 66), f"“{spoken}”", font(17))

    airline = plane.get("airline") or plane.get("operator") or ""
    if airline:
        al_font = font(21)
        airline = truncate(draw, airline, al_font, right_limit - MARGIN - 330)
        draw_text(draw, (right_limit, 16), airline, al_font, anchor="ra")

    stamp = time.strftime("%H:%M")
    if count > 1:
        stamp += f"   ·   {count} in range"
    if note:
        stamp += f"   ·   {note}"
    draw_text(draw, (right_limit, 46), stamp, font(14), anchor="ra")

    if plane.get("notes"):
        draw_badges(draw, (right_limit, 66), plane["notes"], anchor_right=True)

    draw.line((MARGIN, 92, WIDTH - MARGIN, 92), fill=BLACK, width=3)


def draw_route(draw, plane, top, left=MARGIN, right=WIDTH - MARGIN,
               code_size=40, show_detail=True):
    """Origin and destination either side of a progress bar."""
    origin = plane.get("origin") or {}
    dest = plane.get("destination") or {}
    o_code = (origin.get("iata") or origin.get("icao") or "").upper()
    d_code = (dest.get("iata") or dest.get("icao") or "").upper()

    if not (o_code or d_code):
        draw_text(draw, (left, top + 6), "ROUTE UNKNOWN", font(32, "bold"))
        draw_text(draw, (left, top + 48),
                  "no filed route for this callsign", font(16))
        return top + 76

    code_font = font(code_size, "bold")
    o_w = draw.textlength(o_code or "???", font=code_font)
    d_w = draw.textlength(d_code or "???", font=code_font)

    draw_text(draw, (left, top), o_code or "???", code_font)
    draw_text(draw, (right, top), d_code or "???", code_font, anchor="ra")

    bar_left = left + o_w + 24
    bar_right = right - d_w - 24
    bar_y = top + code_size * 0.55

    progress = plane.get("progress") or {}
    if bar_right - bar_left > 60:
        draw_progress(draw, (bar_left, bar_y, bar_right, bar_y),
                      progress.get("fraction"))

    if not show_detail:
        return int(top + code_size + 10)

    city_font = font(16)
    o_city = truncate(draw, origin.get("city") or origin.get("name") or "",
                      city_font, 190)
    d_city = truncate(draw, dest.get("city") or dest.get("name") or "",
                      city_font, 190)
    city_y = int(top + code_size + 8)
    draw_text(draw, (left, city_y), o_city, city_font)
    draw_text(draw, (right, city_y), d_city, city_font, anchor="ra")

    if progress:
        import geo
        bits = [f"{progress['fraction'] * 100:.0f}%"]
        eta = progress.get("eta_seconds")
        if eta:
            bits.append(f"{geo.format_duration(eta)} to run")
            lands = time.localtime(time.time() + eta)
            bits.append(f"lands {time.strftime('%H:%M', lands)}")
        draw_text(draw, ((bar_left + bar_right) / 2, city_y),
                  "   ·   ".join(bits), font(16, "bold"), anchor="ma")

    return city_y + 26


def render_flight(plane, config, count=0, note=None, book=None, stats=None):
    image = Image.new("1", (WIDTH, HEIGHT), WHITE)
    draw = ImageDraw.Draw(image)

    draw_header(image, draw, plane, count, note)
    y = draw_route(draw, plane, 106)

    compass_x, compass_r = 690, 62
    text_right = compass_x - compass_r - 24

    model = plane.get("model") or plane.get("description") or \
        plane.get("type_code") or "Unknown type"
    model_font = fit_text(draw, model, "bold", text_right - MARGIN, 27, 16)
    draw_text(draw, (MARGIN, y + 8), model, model_font)
    draw_text(draw, (MARGIN, y + 44), aircraft_line(plane), font(18, "mono"))

    owner = plane.get("owner") or plane.get("operator") or ""
    if owner and owner.strip().lower() != (plane.get("airline") or "").strip().lower():
        owner_font = font(15)
        draw_text(draw, (MARGIN, y + 72),
                  truncate(draw, owner, owner_font, text_right - MARGIN), owner_font)

    line = logbook_line(book, stats)
    if line:
        draw_text(draw, (MARGIN, y + 98), line, font(16, "bold"))

    bearing = plane.get("bearing_deg")
    draw_compass(draw, (compass_x, 268), compass_r, bearing, font(14, "bold"))
    if bearing is not None:
        draw_text(draw, (compass_x, 268 + compass_r + 12),
                  f"LOOK {compass_point(bearing)}", font(18, "bold"), anchor="ma")

    draw_stats_strip(draw, main_stats(plane, config))
    return image


# --------------------------------------------------------------------------
# card 2 — the detail
# --------------------------------------------------------------------------

def render_detail(plane, config, count=0, note=None, book=None, stats=None):
    image = Image.new("1", (WIDTH, HEIGHT), WHITE)
    draw = ImageDraw.Draw(image)

    callsign = plane.get("callsign") or plane.get("registration") or "UNKNOWN"
    draw_text(draw, (MARGIN, 14), callsign, font(34, "bold"))
    model = plane.get("model") or plane.get("description") or ""
    if model:
        draw_text(draw, (WIDTH - MARGIN, 22),
                  truncate(draw, model, font(20), 420), font(20), anchor="ra")
    draw.line((MARGIN, 64, WIDTH - MARGIN, 64), fill=BLACK, width=3)

    photo_box = (MARGIN, 78, MARGIN + 360, 78 + 202)
    has_photo = bool(plane.get("photo")) and draw_photo(image, draw, photo_box,
                                                        plane["photo"])
    if not has_photo:
        draw.rectangle(photo_box, outline=BLACK, width=2)
        draw_text(draw, ((photo_box[0] + photo_box[2]) / 2,
                         (photo_box[1] + photo_box[3]) / 2),
                  "no photo of\nthis airframe", font(19), anchor="mm")

    cells = telemetry_cells(plane)
    right_x, right_w = MARGIN + 388, WIDTH - MARGIN - (MARGIN + 388)
    if cells:
        rows = min(3, len(cells))
        row_h = 202 // rows
        for i, (label, value, unit) in enumerate(cells[:rows]):
            top = 78 + i * row_h
            draw_stat(draw, (right_x, top + 4, right_x + right_w, top + row_h - 10),
                      label, value, unit, value_size=min(46, row_h - 26))
            if i:
                draw.line((right_x + 16, top, right_x + right_w - 16, top),
                          fill=BLACK, width=1)
    else:
        draw_text(draw, (right_x + right_w / 2, 179),
                  "this aircraft is not\nreporting telemetry", font(20),
                  anchor="mm")

    # the day, along the bottom
    draw.line((MARGIN, 300, WIDTH - MARGIN, 300), fill=BLACK, width=3)
    draw_text(draw, (MARGIN, 310), "TODAY", font(15, "bold"))

    stats = stats or {}
    tiles = [
        ("AIRCRAFT", f"{stats.get('today', 0)}", ""),
        ("TYPES", f"{stats.get('today_types', 0)}", ""),
        ("AIRLINES", f"{stats.get('today_airlines', 0)}", ""),
    ]
    furthest = stats.get("furthest") or {}
    if furthest.get("destination"):
        d_factor, d_unit = units_for(config)["dist"]
        miles = (furthest.get("dest_nm_home") or 0) * d_factor
        tiles.append(("FURTHEST", furthest["destination"], f"{miles:,.0f} {d_unit}"))

    cell_w = (WIDTH - 2 * MARGIN) // len(tiles)
    for i, (label, value, unit) in enumerate(tiles):
        x0 = MARGIN + i * cell_w
        draw_stat(draw, (x0, 340, x0 + cell_w, 412), label, value, unit,
                  value_size=52)
        if i:
            draw.line((x0, 344, x0, 412), fill=BLACK, width=1)

    line = logbook_line(book, None)
    if line:
        draw_text(draw, (WIDTH / 2, 438), line, font(18, "bold"), anchor="ma")

    regular = stats.get("most_regular") or {}
    if regular.get("registration") and not line:
        draw_text(draw, (WIDTH / 2, 438),
                  f"the regular: {regular['registration']} "
                  f"({regular.get('type_code') or '?'}) seen {regular['c']}x",
                  font(18), anchor="ma")
    return image


# --------------------------------------------------------------------------
# the dense single card
# --------------------------------------------------------------------------

def render_dense(plane, config, count=0, note=None, book=None, stats=None):
    image = Image.new("1", (WIDTH, HEIGHT), WHITE)
    draw = ImageDraw.Draw(image)

    compass_x, compass_r = 706, 46
    text_right = compass_x - compass_r - 20

    draw_header(image, draw, plane, count, note)
    # The route has to stop short of the compass column here, or the
    # right-aligned destination city lands on top of the compass rose.
    y = draw_route(draw, plane, 104, right=text_right, code_size=36)

    model = plane.get("model") or plane.get("description") or \
        plane.get("type_code") or "Unknown type"
    draw_text(draw, (MARGIN, y + 4),
              truncate(draw, model, font(23, "bold"), text_right - MARGIN),
              font(23, "bold"))
    draw_text(draw, (MARGIN, y + 34), aircraft_line(plane), font(17, "mono"))

    line = logbook_line(book, stats)
    if line:
        draw_text(draw, (MARGIN, y + 60),
                  truncate(draw, line, font(15, "bold"), text_right - MARGIN),
                  font(15, "bold"))

    bearing = plane.get("bearing_deg")
    draw_compass(draw, (compass_x, y + 40), compass_r, bearing, font(13, "bold"))
    if bearing is not None:
        draw_text(draw, (compass_x, y + 40 + compass_r + 8),
                  f"LOOK {compass_point(bearing)}", font(16, "bold"), anchor="ma")

    # telemetry band
    cells = telemetry_cells(plane)[:4]
    band_top = 296
    if cells:
        draw.line((MARGIN, band_top, WIDTH - MARGIN, band_top), fill=BLACK, width=1)
        cell_w = (WIDTH - 2 * MARGIN) // len(cells)
        for i, (label, value, unit) in enumerate(cells):
            x0 = MARGIN + i * cell_w
            draw_stat(draw, (x0, band_top + 8, x0 + cell_w, band_top + 64),
                      label, value, unit, value_size=34, label_size=13)
            if i:
                draw.line((x0, band_top + 10, x0, band_top + 64), fill=BLACK, width=1)

    draw_stats_strip(draw, main_stats(plane, config))
    return image


def draw_stats_strip(draw, cells, top=396):
    draw.line((MARGIN, top, WIDTH - MARGIN, top), fill=BLACK, width=3)
    cell_w = (WIDTH - 2 * MARGIN) // len(cells)
    for i, (label, value, unit) in enumerate(cells):
        x0 = MARGIN + i * cell_w
        draw_stat(draw, (x0, top + 8, x0 + cell_w, HEIGHT - 16), label, value, unit)
        if i:
            draw.line((x0, top + 12, x0, HEIGHT - 18), fill=BLACK, width=1)


# --------------------------------------------------------------------------
# nothing overhead
# --------------------------------------------------------------------------

def render_idle(config: dict, count: int = 0, note: str | None = None,
                stats: dict | None = None) -> Image.Image:
    """Quiet skies. Rather than an empty screen, show the day so far."""
    image = Image.new("1", (WIDTH, HEIGHT), WHITE)
    draw = ImageDraw.Draw(image)

    d_factor, d_unit = units_for(config)["dist"]
    radius = float(config.get("radius_nm", 15)) * d_factor

    headline = note or "QUIET SKIES"
    draw_text(draw, (MARGIN, 24), headline, font(46, "bold"))
    draw_text(draw, (MARGIN, 82),
              f"nothing within {radius:.0f} {d_unit} of "
              f"{config.get('home', {}).get('label', 'home')}",
              font(20))
    draw_text(draw, (WIDTH - MARGIN, 32), time.strftime("%H:%M  ·  %a %d %b"),
              font(18), anchor="ra")
    draw.line((MARGIN, 122, WIDTH - MARGIN, 122), fill=BLACK, width=3)

    stats = stats or {}
    if not stats.get("total"):
        draw_text(draw, (WIDTH / 2, 260),
                  "the logbook starts filling up\nas soon as something flies over",
                  font(22), anchor="mm")
        return image

    draw_text(draw, (MARGIN, 138), "TODAY", font(16, "bold"))
    tiles = [
        ("AIRCRAFT", f"{stats.get('today', 0)}", ""),
        ("TYPES", f"{stats.get('today_types', 0)}", ""),
        ("AIRLINES", f"{stats.get('today_airlines', 0)}", ""),
    ]
    furthest = stats.get("furthest") or {}
    if furthest.get("destination"):
        miles = (furthest.get("dest_nm_home") or 0) * d_factor
        tiles.append(("FURTHEST", furthest["destination"], f"{miles:,.0f} {d_unit}"))

    cell_w = (WIDTH - 2 * MARGIN) // len(tiles)
    for i, (label, value, unit) in enumerate(tiles):
        x0 = MARGIN + i * cell_w
        draw_stat(draw, (x0, 172, x0 + cell_w, 252), label, value, unit,
                  value_size=58)
        if i:
            draw.line((x0, 176, x0, 252), fill=BLACK, width=1)

    draw.line((MARGIN, 286, WIDTH - MARGIN, 286), fill=BLACK, width=1)
    draw_text(draw, (MARGIN, 300), "ALL TIME", font(16, "bold"))

    lines = []
    lines.append(f"{stats.get('total', 0):,} sightings   ·   "
                 f"{stats.get('airframes', 0):,} distinct aircraft")
    regular = stats.get("most_regular") or {}
    if regular.get("registration"):
        lines.append(f"the regular:  {regular['registration']} "
                     f"({regular.get('type_code') or '?'})   ·   seen {regular['c']}x")
    busiest = stats.get("busiest_airline") or {}
    if busiest.get("airline"):
        lines.append(f"most today:  {busiest['airline']}   ·   {busiest['c']}x")
    last = stats.get("last") or {}
    if last.get("seen_at"):
        ago = max(0, int((time.time() - last["seen_at"]) / 60))
        lines.append(f"last seen:  {last.get('callsign') or '?'}   ·   "
                     f"{ago} min ago")

    for i, text in enumerate(lines[:4]):
        draw_text(draw, (MARGIN, 332 + i * 34), text, font(21))
    return image


# --------------------------------------------------------------------------
# dispatch
# --------------------------------------------------------------------------

def render(plane, config, count=0, note=None, book=None, stats=None, card=None):
    """`card` picks the screen in alternate mode: "flight" or "detail"."""
    if plane is None:
        return render_idle(config, count=count, note=note, stats=stats)

    layout = str(config.get("layout", "alternate")).lower()
    if layout == "dense":
        return render_dense(plane, config, count, note, book, stats)
    if card == "detail":
        return render_detail(plane, config, count, note, book, stats)
    return render_flight(plane, config, count, note, book, stats)


# --------------------------------------------------------------------------
# sample data, so the layout can be checked with no internet
# --------------------------------------------------------------------------

def demo_plane() -> dict:
    return {
        "icao": "a1b2c3",
        "callsign": "UAL1287",
        "flight_number": "UA1287",
        "radio_callsign": "United",
        "registration": "N77296",
        "type_code": "B738",
        "altitude_ft": 12750.0,
        "on_ground": False,
        "speed_kt": 341.0,
        "track_deg": 118.0,
        "vertical_fpm": 1408.0,
        "distance_nm": 4.3,
        "bearing_deg": 47.0,
        "mach": 0.62,
        "oat_c": -18.0,
        "wind": {"label": "TAILWIND", "magnitude_kt": 41.0, "cross_kt": 12.0,
                 "component_kt": 41.0},
        "selected_alt_ft": 34000.0,
        "category": "A3",
        "year_built": "1998",
        "airline": "United Airlines",
        "model": "Boeing 737-824",
        "owner": "United Airlines Inc",
        "photo": None,
        "notes": [],
        "origin": {"iata": "SFO", "icao": "KSFO", "name": "San Francisco Intl",
                   "city": "San Francisco", "lat": 37.619, "lon": -122.375},
        "destination": {"iata": "EWR", "icao": "KEWR", "name": "Newark Liberty Intl",
                        "city": "Newark", "lat": 40.6925, "lon": -74.1687},
        "progress": {"total_nm": 2237.0, "flown_nm": 190.0, "remaining_nm": 2047.0,
                     "fraction": 0.085, "off_track_nm": 4.0,
                     "eta_seconds": 6 * 3600 + 2 * 60},
    }


def demo_stats() -> dict:
    return {
        "today": 43, "today_types": 11, "today_airlines": 9,
        "total": 5821, "airframes": 1904,
        "furthest": {"destination": "SIN", "dest_name": "Singapore",
                     "dest_nm_home": 7327.0},
        "busiest_airline": {"airline": "United Airlines", "c": 14},
        "most_regular": {"registration": "N77296", "type_code": "B738", "c": 31},
        "last": {"callsign": "ASA1200", "destination": "SEA",
                 "seen_at": time.time() - 7 * 60},
    }


def demo_book() -> dict:
    return {"visit_number": 31, "new_airframe": False, "new_airline": False,
            "new_type": False, "same_visit": False}


if __name__ == "__main__":
    import json

    here = os.path.dirname(os.path.abspath(__file__))
    with open(os.path.join(here, "config.json"), encoding="utf-8") as fh:
        cfg = json.load(fh)
    out = os.path.join(here, "preview.png")
    render(demo_plane(), cfg, count=6, book=demo_book(), stats=demo_stats()).save(out)
    print("wrote", out)
