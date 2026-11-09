#!/usr/bin/env python3
"""The loop.

    python3 run.py            # poll and drive the panel, forever
    python3 run.py --once     # one poll, one draw, exit
    python3 run.py --demo     # sample data, no internet, writes preview.png
    python3 run.py --serve    # the real loop, plus a web page on port 8080
    python3 run.py --serve --fast    # same, but check every 5s (no panel only)

--serve is the one to use before the panel arrives: open
http://localhost:8080, or http://<hostname>.local:8080 from your phone, and you
are looking at exactly the image the panel would be showing.

A note on how often it changes. This is not a video feed. It asks the sky what
is up there every `poll_seconds` (20 by default), and redraws only when
something meaningful changed, never more often than `min_redraw_seconds` (30).
Those limits exist to protect the e-ink panel, which has a finite number of
refreshes in it. Watching in a browser with no panel attached, `--fast` lifts
them. The page itself now reports when the screen last actually changed, rather
than claiming a refresh rate it does not have.
"""

from __future__ import annotations

import io
import json
import os
import sys
import threading
import time

import render
from display import Display
from logbook import Logbook
from tracker import Tracker, load_config

HERE = os.path.dirname(os.path.abspath(__file__))

_latest_png = b""
_latest_version = 0        # bumped every time the image actually changes
_latest_at = 0.0
_next_poll_at = 0.0
_latest_lock = threading.Lock()


# --------------------------------------------------------------------------
# refresh discipline
# --------------------------------------------------------------------------

def signature(plane: dict | None, card: str | None = None) -> tuple:
    """What counts as "something changed".

    Altitude rounded to 500 ft and distance to whole miles, so a climbing
    aircraft does not flash the panel on every single poll. Route progress is
    rounded to 5%, which on a long-haul flight is about twenty minutes.
    """
    if plane is None:
        return ("idle",)
    alt = plane.get("altitude_ft")
    dist = plane.get("distance_nm")
    origin = (plane.get("origin") or {}).get("iata", "")
    dest = (plane.get("destination") or {}).get("iata", "")
    progress = (plane.get("progress") or {}).get("fraction")
    return (
        card or "flight",
        plane.get("icao"),
        plane.get("callsign"),
        round(alt / 500.0) if alt else 0,
        round(dist) if dist is not None else -1,
        origin, dest,
        round(progress * 20) if progress is not None else -1,
        bool(plane.get("photo")),
        tuple(n["tag"] for n in (plane.get("notes") or [])),
    )


def pick_card(config: dict, plane, held_since: float) -> str | None:
    """Which screen to show.

    Alternating cards means an extra full-screen flash every time they swap, so
    this does it exactly once per aircraft: the flight card first, then the
    detail card after `detail_after_seconds`, and it stays there until a
    different aircraft takes the screen. Set that to 0 to never show the detail
    card at all.
    """
    if plane is None:
        return None
    if str(config.get("layout", "alternate")).lower() == "dense":
        return "dense"
    after = float(config.get("detail_after_seconds", 60) or 0)
    if after and time.time() - held_since >= after:
        return "detail"
    return "flight"


def publish(image) -> None:
    global _latest_png, _latest_version, _latest_at
    buffer = io.BytesIO()
    image.convert("L").save(buffer, format="PNG")
    with _latest_lock:
        _latest_png = buffer.getvalue()
        _latest_version += 1
        _latest_at = time.time()


def note_next_poll(when: float) -> None:
    global _next_poll_at
    with _latest_lock:
        _next_poll_at = when


# --------------------------------------------------------------------------
# the loop
# --------------------------------------------------------------------------

def loop(config: dict, display: Display, once: bool = False) -> None:
    tracker = Tracker(config)
    poll = float(config.get("poll_seconds", 20))
    min_redraw = float(config.get("min_redraw_seconds", 30))

    book = Logbook(config) if config.get("logbook", True) else None

    last_signature = None
    last_draw = 0.0
    on_screen_icao = None
    held_since = time.time()

    while True:
        started = time.time()
        plane, count = tracker.current()
        note = None
        if tracker.last_error and plane is None:
            note = "NO DATA"

        if plane is not None and plane.get("icao") != on_screen_icao:
            on_screen_icao = plane.get("icao")
            held_since = started

        sighting = book.record(plane) if (book and plane is not None) else None
        stats = book.stats() if book else None

        card = pick_card(config, plane, held_since)
        sig = signature(plane, card)
        due = (sig != last_signature) and (started - last_draw >= min_redraw)

        if due or last_signature is None or once:
            image = render.render(plane, config, count=count, note=note,
                                  book=sighting, stats=stats, card=card)
            display.show(image)
            publish(image)
            last_signature = sig
            last_draw = started

            if plane is not None:
                origin = (plane.get("origin") or {}).get("iata") or "???"
                dest = (plane.get("destination") or {}).get("iata") or "???"
                extra = ""
                progress = plane.get("progress")
                if progress:
                    extra += f"  {progress['fraction'] * 100:.0f}%"
                if sighting and sighting.get("new_airframe"):
                    extra += "  NEW"
                if plane.get("notes"):
                    extra += "  " + "/".join(n["tag"] for n in plane["notes"])
                print(f"{time.strftime('%H:%M:%S')}  [{card}]  "
                      f"{plane.get('callsign') or plane.get('registration') or '?'}  "
                      f"{origin}->{dest}  "
                      f"{(plane.get('distance_nm') or 0):.1f} nm  "
                      f"{(plane.get('altitude_ft') or 0):,.0f} ft"
                      f"   ({count} in range){extra}", flush=True)
            else:
                print(f"{time.strftime('%H:%M:%S')}  "
                      f"{note or 'quiet skies'}"
                      f"{'  ' + tracker.last_error if tracker.last_error else ''}",
                      flush=True)

        if once:
            display.sleep()
            return

        elapsed = time.time() - started
        wait = max(1.0, poll - elapsed)
        note_next_poll(time.time() + wait)
        time.sleep(wait)


# --------------------------------------------------------------------------
# the web preview
# --------------------------------------------------------------------------

PAGE = """<!doctype html>
<html><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Flight tracker</title>
<style>
  html,body{margin:0;height:100%;background:#111;color:#888;
            font:14px -apple-system,system-ui,sans-serif;
            display:flex;flex-direction:column;align-items:center;
            justify-content:center;gap:12px}
  img{width:min(96vw,800px);image-rendering:pixelated;background:#fff;
      border-radius:4px;box-shadow:0 8px 40px #0008}
  #s{font-variant-numeric:tabular-nums;text-align:center;line-height:1.6}
  b{color:#ccc;font-weight:600}
</style></head><body>
<img id="p" src="/panel.png" alt="panel">
<div id="s">starting…</div>
<script>
// The image only changes when the tracker redraws, which is far less often
// than any polling interval. So watch a version number and swap the image
// only when it really changed — and say plainly when that last happened.
var version = null, drawnAt = null, nextPoll = null, poll = null, redraw = null;

function ago(t){ return Math.max(0, Math.round(Date.now()/1000 - t)); }

function tick(){
  if (drawnAt === null) return;
  var bits = ['screen last changed <b>' + ago(drawnAt) + 's</b> ago'];
  if (nextPoll !== null) {
    var due = Math.max(0, Math.round(nextPoll - Date.now()/1000));
    bits.push('next check in <b>' + due + 's</b>');
  }
  var note = 'checks the sky every ' + poll + 's';
  if (redraw) note += ', redraws at most every ' + redraw + 's';
  document.getElementById('s').innerHTML = bits.join(' &middot; ') +
      '<br><span style="color:#666">' + note + '</span>';
}

function check(){
  fetch('/status.json', {cache: 'no-store'}).then(function(r){ return r.json(); })
    .then(function(d){
      poll = d.poll_seconds; redraw = d.min_redraw_seconds;
      nextPoll = d.next_poll_at; drawnAt = d.updated_at;
      if (d.version !== version) {
        version = d.version;
        document.getElementById('p').src = '/panel.png?v=' + d.version;
      }
      tick();
    }).catch(function(){});
}

check();
setInterval(check, 2000);
setInterval(tick, 1000);
</script>
</body></html>""".encode("utf-8")


def serve(config: dict) -> None:
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):        # the access log is just noise here
            pass

        def do_GET(self):
            if self.path.startswith("/status.json"):
                with _latest_lock:
                    payload = {
                        "version": _latest_version,
                        "updated_at": _latest_at,
                        "next_poll_at": _next_poll_at,
                        "poll_seconds": float(config.get("poll_seconds", 20)),
                        "min_redraw_seconds": float(
                            config.get("min_redraw_seconds", 30)),
                    }
                body = json.dumps(payload).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.send_header("Cache-Control", "no-store")
                self.end_headers()
                self.wfile.write(body)
                return

            if self.path.startswith("/panel.png"):
                with _latest_lock:
                    body = _latest_png
                    etag = f'"{_latest_version}"'
                if not body:
                    self.send_error(503, "nothing rendered yet")
                    return
                if self.headers.get("If-None-Match") == etag:
                    self.send_response(304)
                    self.end_headers()
                    return
                self.send_response(200)
                self.send_header("Content-Type", "image/png")
                self.send_header("Content-Length", str(len(body)))
                self.send_header("ETag", etag)
                self.send_header("Cache-Control", "no-cache")
                self.end_headers()
                self.wfile.write(body)
                return

            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(PAGE)))
            self.end_headers()
            self.wfile.write(PAGE)

    server_cfg = config.get("server", {}) or {}
    host = server_cfg.get("host", "0.0.0.0")
    port = int(server_cfg.get("port", 8080))
    httpd = ThreadingHTTPServer((host, port), Handler)

    # macOS already reports the hostname with .local on the end; the Pi does
    # not. Appending one unconditionally produces "....local.local", which
    # resolves to nothing.
    node = os.uname().nodename
    mdns = node if node.endswith(".local") else f"{node}.local"

    print(f"preview at http://localhost:{port}", flush=True)
    print(f"  from another device on this network: http://{mdns}:{port}",
          flush=True)
    httpd.serve_forever()


# --------------------------------------------------------------------------

def main(argv: list) -> int:
    config = load_config()
    args = set(argv[1:])

    if "--help" in args or "-h" in args:
        print(__doc__)
        return 0

    display = Display(config)
    print(f"flight tracker starting — {display.describe()}", flush=True)

    if "--fast" in args:
        # The poll and redraw limits exist to be kind to the e-ink panel. With
        # no panel attached there is nothing to be kind to, so while you are
        # sitting there watching it in a browser, go quicker.
        if display.hardware:
            print("--fast ignored: a panel is attached, and flashing it this "
                  "hard shortens its life", flush=True)
        else:
            config["poll_seconds"] = 5
            config["min_redraw_seconds"] = 0
            print("fast mode — polling every 5s, no redraw limit", flush=True)

    if "--once" not in args and "--demo" not in args and "--clear" not in args:
        print(f"checking the sky every {config.get('poll_seconds', 20)}s; "
              f"redrawing at most every {config.get('min_redraw_seconds', 30)}s "
              f"and only when something changed", flush=True)

    if "--demo" in args:
        card = "detail" if "--detail" in args else "flight"
        if "--idle" in args:
            image = render.render(None, config, stats=render.demo_stats())
        else:
            image = render.render(render.demo_plane(), config, count=6,
                                  book=render.demo_book(),
                                  stats=render.demo_stats(), card=card)
        display.show(image, force_full=True)
        publish(image)
        print(f"wrote {os.path.join(HERE, 'preview.png')}")
        if "--serve" in args:
            serve(config)
        display.sleep()
        return 0

    if "--clear" in args:
        display.clear()
        display.sleep()
        return 0

    if "--serve" in args:
        worker = threading.Thread(target=loop, args=(config, display), daemon=True)
        worker.start()
        try:
            serve(config)
        except KeyboardInterrupt:
            pass
        return 0

    try:
        loop(config, display, once="--once" in args)
    except KeyboardInterrupt:
        print("\nstopping", flush=True)
        display.sleep()
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
