# Home Flight Tracker


A small e-ink panel on the wall that shows the plane currently overhead: airline
and flight number, where it came from and where it's going, what kind of aircraft
it is, how high and how fast, a photo of that exact airframe, and a compass arrow
pointing at which part of the sky to look at.

No API keys, no accounts, no monthly fee. All three data sources are free and
open.

---

## What you need

| Part | Rough cost | Notes |
|---|---|---|
| Raspberry Pi | **you have one — a Pi 4 Model B** | Confirmed 2026-08-21. This barely uses any CPU, so a Pi 4 is more than enough. |
| microSD card, **32 GB** | $8–13 | Get a name brand from a reputable seller — SanDisk Ultra or Extreme Pro, Samsung Evo Plus, or the official Raspberry Pi card. See the note below. |
| USB-C SD card reader | $10–15 | **Plugs into your Mac, never into the Pi** — the Pi reads the card from its own slot. Your MacBook Air has no card slot and only USB-C ports, so get a USB-C reader. Check it takes microSD, or comes with the full-size adapter. Some cards ship with a reader in the box — worth checking before buying both. |
| Power supply | $10 | The Pi 4 wants **USB-C, 5 V / 3 A**. The official one is the safe choice — an underpowered supply shows up as random reboots, usually blamed on the panel. |
| Waveshare 7.5" e-Paper HAT, 800×480 black/white | **$57** direct, ~$61 US resellers | Comes with the panel, the driver HAT, and the ribbon cable. This is the one the code is written for. |
| Picture frame, 5×7" opening | $10–25 | Optional but this is what turns it into an object rather than a gadget. |

**Do not order anything yet.** Steps 1–4 below get the whole thing working and
visible on your phone with just the Pi. Order the panel once you've seen it
running and know you like the layout.

### About that card

- **32 GB is the number.** Raspberry Pi OS wants 8 GB on its own, 16 GB works but
  the price gap is a couple of dollars, and anything above 32 GB buys you nothing
  here — this project writes almost nothing to disk beyond a few cached photos.
- **Ignore the A2 badge.** A2 is a Pi 5 hardware feature; on a Pi 4 an A1 card is
  just as quick, sometimes quicker. Do not pay extra for it.
- **Buy from a seller you trust.** Counterfeit microSD cards are genuinely common
  in marketplace listings — a fake reports the right size and then corrupts once
  it fills past its real capacity, which looks exactly like a mysteriously
  unreliable Pi. Buy direct from Amazon, B&H, Best Buy, or a Pi shop like PiShop
  or Adafruit rather than a third-party seller with a suspiciously good price.
- If you want it to last: the Samsung Pro Endurance line is built for devices
  that run continuously. Not necessary for this — it barely writes — but it is
  only a dollar or two more if a wall fixture running for years appeals.

### About that panel

- Black and white only. There is a red/black/white version for about the same
  money, but it takes ~15 seconds to refresh instead of 4, and the red is a dull
  brick colour. Not worth it.
- There's also a 7-colour "Inky Impression" from Pimoroni at roughly double the
  price. Lovely for photos, much slower, and the colours are muted. The
  black/white panel with dithered photos looks sharper than you'd expect — see
  the sample images.
- Refresh times on this panel: 4s full, 1.5s fast, 0.4s partial.

---

## Which machine am I typing on?

This trips everyone up, so: two computers are involved, and every step below says
which one it belongs to in its heading.

| | |
|---|---|
| **Your Mac** | Writes the SD card (step 1), and is the terminal you SSH *from*. It also holds the code files until you copy them across. |
| **The Pi** | Has no keyboard or monitor. You reach it entirely over SSH from the Mac, so you will still be typing into a Mac terminal window — but the commands run on the Pi. |

The rule of thumb: from step 2 onward, if your prompt says something like
`pi@flighttracker`, you are on the Pi. If it says your own Mac username, you are
not. The only place after step 2 where you deliberately go back to the Mac is the
`scp` line in step 3, and it is flagged there.

---

## While you wait for the parts — run the whole thing on your Mac today

You do not need the Pi, the card, or the panel to see this working. None of the
code is Pi-specific until the moment it tries to talk to the panel, and when
there is no panel it just writes a preview image instead. So you can point it at
your actual house and watch actual planes right now, on the Mac.

This is worth doing before the parts arrive, because it answers the two questions
that decide the settings: *are my coordinates right*, and *is 15 nm the right
radius for where I live*.

**1. Get the code and set your coordinates.**

```bash
git clone https://github.com/yli623/flight-tracker.git ~/flight-tracker-mac
cd ~/flight-tracker-mac
```

Open `config.json` and edit the first block:

```json
"home": { "lat": 41.9786, "lon": -87.9048, "label": "HOME" }
```

Right-click your house in Google Maps and click the lat/long pair at the top of
the menu — it copies to the clipboard. Latitude first. In the Americas,
longitude is negative.

**2. Set up Python.**

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install Pillow
```

If `python3` is not found, macOS will offer to install the developer command line
tools — accept, wait, and run it again.

`pip` will almost certainly finish by warning that it is out of date and offering
an upgrade command. **Ignore it.** The version macOS ships is old but works fine
for this, and the warning appears whether or not the install succeeded, so it is
easy to mistake for an error. The line that matters is the one above it saying
`Successfully installed Pillow-...`. To confirm:

```bash
python3 -c "import PIL; print(PIL.__version__)"
```

A version number means you are good. (Running the suggested `pip install
--upgrade pip` is harmless too, if the warning bothers you — it only touches this
throwaway virtual environment, not your system.)

**3. Run it.**

```bash
python3 tracker.py        # prints what is overhead, as text
python3 run.py --serve    # then open http://localhost:8080
```

macOS may ask whether Python should accept incoming network connections. Allow it
if you want to view the page from your phone; deny is fine if you only look at it
on the Mac.

Leave `--serve` running for an afternoon. If it is nearly always empty, raise
`radius_nm`. If a plane is always on screen and it feels like noise, lower it.
Whatever number you settle on, put it in the Pi's `config.json` too.

One cosmetic caveat: the Mac does not have the DejaVu font the Pi uses, so it
falls back to Arial and the spacing shifts very slightly. Everything fits; it
just is not pixel-identical to what the panel will show.

When you are done, `deactivate` leaves the virtual environment. The
`~/flight-tracker-mac` folder is disposable — delete it whenever.

### See it at its real size before you spend $57

The browser preview proves the layout is right. It does not tell you whether 7.5
inches is big enough to read from the sofa — your laptop is showing the card two
or three times larger than the panel ever will.

So print it at actual size:

```bash
python3 mockup.py          # uses the sky over your house right now
python3 mockup.py --demo   # or sample data
```

That writes `panel-mockup.pdf`. Print it **at 100%** — in the macOS print dialog
that means Scale: 100%, *not* "Scale to Fit", which silently shrinks everything
by a few percent and defeats the point. The page has a 100 mm ruler on it; check
it with a real ruler before trusting the rest.

Then cut along the dashed line, tape it to the wall where the frame will hang,
and go sit where you normally sit. The solid line is the active area — the part
that lights up — and the dashed line is the glass, which is what has to fit
behind the mat.

This is the cheapest possible version of the decision. If the flight number is
too small to read from the sofa, no panel fixes that; the layout needs bigger
type or less on screen, and you can change that in `render.py` today for free.

Two things a paper print cannot show you:

- **Contrast.** E-ink is closer to newsprint than to laser-white paper — light
  grey background, dark grey ink. Slightly less crisp than your print. Squint a
  little.
- **The refresh.** Every update flashes the whole panel black and back over about
  four seconds. It is genuinely eye-catching in a quiet room, which is exactly
  why `min_redraw_seconds` and the stickiness rules exist.

---

## Step 0 — which Pi do you actually have?

**Answered: a Raspberry Pi 4 Model B.** That is the easy case — it takes the
64-bit OS, it has the standard 40-pin header the HAT needs, and nothing else in
this guide changes. Carry on to step 1.

(For reference, if you ever need to check a board again: `cat /proc/device-tree/model`
on a running Pi, or read the label printed on the top surface near the GPIO pins.)

---

## Step 1 — put an OS on the SD card  ·  *on your Mac*

**All five substeps below happen on your Mac, in one app.** Nothing goes near the
Pi until the very end of this step, when you physically move the card across.

Get **Raspberry Pi Imager** from raspberrypi.com/software, or in a terminal:

```bash
brew install --cask raspberry-pi-imager
```

Put the microSD card in your USB-C reader and plug the reader into the **Mac**.
(The reader is a Mac accessory only — the Pi has its own microSD slot on the
underside of the board and never needs one.) macOS will
probably pop up *"The disk you inserted was not readable"* — click **Ignore**.
That is normal for a blank or Linux-formatted card, and Imager can still see it.
Imager will also ask for your Mac password when it writes; that is expected, it
needs raw access to the disk.

Then, in the app: 

1. **Choose Device** → *Raspberry Pi 4*.
2. **Choose OS** → *Raspberry Pi OS (other)* → **Raspberry Pi OS Lite (64-bit)**.
   Lite means no desktop. You want that: this thing never shows a desktop, and
   Lite boots faster and uses less power. The 64-bit build is the right one on a
   Pi 4 — the 32-bit caveat you may read elsewhere applies to the Zero 2 W and
   the Pi 3, not to yours.
3. **Choose Storage** → your SD card.
4. Click the **gear / Edit Settings** button before writing. This is the part
   that saves you from needing a keyboard and monitor:
   - Set hostname: `flighttracker`
   - Set username and password — use `pi` as the username so the service file in
     this repo works unchanged
   - Configure wireless LAN: your WiFi name and password, and your country
   - Set locale/timezone
   - Services tab → **Enable SSH** → *use password authentication*
5. Click **Write** and confirm. It takes a few minutes, then verifies. When it
   says it is done, macOS may complain about the disk again — click **Eject**,
   pull the reader out, move the card to the Pi, and power the Pi on. Give it two
   minutes to boot and join your WiFi.

That gear/Edit Settings screen in substep 4 is the whole reason this works
without a keyboard and monitor: the WiFi details and the SSH switch get baked
onto the card, so the Pi comes up already on your network and already accepting
logins. If you skip it, the Pi boots to a login prompt you have no way of
reaching.

---

## Step 2 — get in  ·  *typed on your Mac, running on the Pi*

Open Terminal on your Mac (⌘-space, type "terminal") and:

```bash
ssh pi@flighttracker.local
```

The first time, it will ask about an unknown host fingerprint — type `yes` and
press return. Then the password you set in step 1. Your prompt changes to
`pi@flighttracker:~ $`, and from that moment everything you type is running on
the Pi, not on the Mac.

If `.local` doesn't resolve, find the Pi's IP address in your router's admin
page and use `ssh pi@192.168.x.x` instead. If it hangs with no response at all,
the Pi is not on your WiFi — almost always a typo in the WiFi password back in
step 1's gear screen. Re-write the card; it is faster than debugging it.

First thing, always:

```bash
sudo apt update && sudo apt full-upgrade -y
```

---

## Step 3 — install the code  ·  *both machines*

This is the one step that hops between the two, so watch which is which.

**On the Pi** (in the SSH session you just opened):

```bash
sudo apt install -y python3-pil git
mkdir -p ~/flight-tracker
```

**Still on the Pi**, fetch the code, then copy over the `config.json` you edited on your Mac
(or edit it again on the Pi with `nano ~/flight-tracker/config.json`):

```bash
git clone https://github.com/yli623/flight-tracker.git ~/flight-tracker
```

---

## Step 4 — see it working (no panel needed)  ·  *on the Pi*

Open `config.json` and set your home coordinates:

```json
"home": { "lat": 37.7749, "lon": -122.4194, "label": "HOME" }
```

To find yours: right-click your house in Google Maps and click the lat/long pair
at the top of the menu — it copies to your clipboard. Latitude first, and
longitude is negative in the Americas.

Then, on the Pi:

```bash
cd ~/flight-tracker

# 1. Does the layout look right? Sample data, no internet needed.
python3 run.py --demo

# 2. Is the data source working, and are your coordinates right?
python3 tracker.py

# 3. The real thing, viewable from any browser on your WiFi.
python3 run.py --serve
```

With `--serve` running, open **http://flighttracker.local:8080** on your phone.
That's the exact image that will go on the e-ink panel, refreshing itself every
few seconds. Leave it running for an afternoon and see whether the radius feels
right.

If `tracker.py` says nothing is in the sky, raise `radius_nm` in `config.json`.
15 nm (~17 miles) is a good default in a city; try 30 somewhere rural.

**This is a good moment to order the panel.**

---

## Step 5 — attach the panel  ·  *hands on the Pi, commands over SSH*

Power the Pi down first (`sudo shutdown -h now`, wait for the LED to stop).

1. Push the driver HAT onto the Pi's 40-pin header, pin 1 to pin 1. It only
   fits one way round if you seat it fully.
2. Set the two switches on the HAT to **B** (display config) and **0** (interface
   config). That's the setting for the 7.5" V2 panel.
3. Connect the ribbon cable from the panel to the HAT. The connector has a small
   dark flap — flip it up, slide the ribbon in with the metal contacts facing
   down, flip the flap back down. It should not pull out with gentle tugging.

Power back on and enable SPI:

```bash
sudo raspi-config
```

→ *Interface Options* → *SPI* → *Yes* → Finish → reboot.

Then install the driver libraries:

```bash
sudo apt install -y python3-numpy python3-spidev python3-lgpio python3-gpiozero
cd ~
git clone https://github.com/waveshareteam/e-Paper.git
cd e-Paper/RaspberryPi_JetsonNano/python
sudo python3 setup.py install
```

Now:

```bash
cd ~/flight-tracker
python3 run.py --once
```

The panel should flash white, flash black, and then settle with the flight card
on it. If it stays blank, see Troubleshooting.

---

## Step 6 — run it forever  ·  *on the Pi*

```bash
sudo cp ~/flight-tracker/flighttracker.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now flighttracker
```

Check on it:

```bash
systemctl status flighttracker
journalctl -u flighttracker -f     # live log, Ctrl-C to stop watching
```

It now starts on boot and restarts itself if it ever crashes. The Pi can be
unplugged and replugged with no ceremony — although note that e-ink keeps
showing its last image with the power off, which is either charming or
confusing depending on your mood.

---

## Step 7 — put it in a frame  ·  *neither, just scissors*

The panel is 170×111 mm of glass with a ribbon cable coming off one edge. A 5×7"
frame with a mat is about right. The usual approach:

- Cut the opening in the mat to the *active area* (163×97 mm), not the glass.
- The panel is thin enough to sit behind the mat with a couple of pieces of
  double-sided foam tape.
- The Pi and the HAT go behind the backing board. A deep-set "shadow box" frame
  gives you the room; otherwise cut a hole in the backing board for the Pi to
  poke through.
- Run the USB power cable out of the bottom edge.

Two things specific to the Pi 4 here. It is the bulkiest of the Pis for this
job — the board plus the HAT stacks to about 25 mm, and the USB and Ethernet
sockets stand proud of the edge, so measure the frame's rebate depth before
buying one. And it idles at roughly 3 W, which is real warmth in a sealed box.
The workload is nearly nothing, so it will not throttle, but leave the back of
the frame open or drill a few holes rather than taping it up airtight.

---

## How it works

Three free services, none of which need an account:

| Service | What it gives us | Cached for |
|---|---|---|
| **adsb.lol** `/v2/point/lat/lon/radius` | Every aircraft near you, with distance and bearing already calculated. Community-run network of volunteer ADS-B receivers. | not cached (this is the live bit) |
| **adsbdb.com** `/v0/callsign/X` | Airline name, origin and destination airports | 24 hours |
| **adsbdb.com** `/v0/aircraft/N12345` | Make, model, owner, photo URL | 30 days |

Photos are downloaded once per tail number and kept in `cache/photos/`.

The files:

- `tracker.py` — fetches, filters, picks the plane, looks up the details.
  Run it directly to print what's overhead without touching the display.
- `render.py` — draws the 800×480 image. Pure black and white, exactly what the
  panel shows, so the preview PNG never lies to you.
- `display.py` — pushes an image to the panel, or writes `preview.png` if no
  panel is attached.
- `run.py` — the loop, plus the `--demo` / `--serve` / `--once` modes.
- `config.json` — all the knobs.

Two details worth knowing about, because they're the difference between a nice
object and an annoying one:

**Stickiness.** Two planes at nearly the same distance will otherwise trade
places every poll, and on e-ink every change is a visible full-screen flash. So
once a plane is on screen it holds the slot for `sticky_hold_seconds` unless a
rival is more than `sticky_beat_margin_nm` closer.

**Refresh discipline.** The screen only redraws when something meaningful
changed — altitude is rounded to 500 ft and distance to whole miles before
comparing. E-ink panels have a finite number of refreshes in them, and constant
flashing on a wall is genuinely irritating. Every 20th refresh does a full
clear-and-redraw cycle, which is what keeps ghosting from building up.

---

## Knobs in `config.json`

| Key | What it does |
|---|---|
| `radius_nm` | How far out to look, nautical miles. 15 is ~17 miles. |
| `units` | `imperial` (miles, mph, feet) or `metric`. Altitude is always feet — that's how aviation works. |
| `poll_seconds` | How often to ask the API. 20 is polite and plenty. |
| `min_redraw_seconds` | Never flash the panel more often than this. |
| `ignore_on_ground` | Hide taxiing aircraft. Turn this off if you live near an airport and want to watch the ground traffic. |
| `max_altitude_ft` | Filter out the very high overflights that aren't really "above you". Try 30000 if you're under a busy airway and only want the interesting low stuff. |
| `sticky_hold_seconds` | How long a plane keeps the screen. |
| `layout` | `hero` (nearest aircraft large, four more below — the default), `board` (six equal rows), or the older single-aircraft cards `alternate` and `dense`. |
| `rows` | How many aircraft to look up and show. 5 is the default; more means smaller type and more API lookups per poll. |
| `detail_after_seconds` | In `alternate`, how long the flight card shows before swapping to the detail card. Set to 0 to never show it. Each swap is a full-screen flash, so this deliberately happens once per aircraft rather than on a timer. |
| `logbook` | Keeps a record of every airframe seen, which drives the "31st visit" line and the quiet-skies stats. Set false to disable. |
| `verify_routes` | Checks the filed route against where the aircraft actually is, and shows "route unconfirmed" rather than a route it cannot be flying. Set false to trust the database blindly. |
| `show_photo` | Set false for a cleaner, more typographic layout. |
| `display.rotate_180` | Flip the image if the panel ends up upside-down in the frame. |
| `display.epd_module` | Change if you buy a different panel — e.g. `epd7in5b_V2` for the red/black/white one. |

---

## Troubleshooting

**Panel stays completely blank.** Nine times out of ten it's SPI. Check
`ls /dev/spidev*` returns something; if not, redo the raspi-config step and
reboot. After that, check the two switches on the HAT are on **B** and **0**,
and reseat the ribbon cable.

**Panel flashes but shows nothing.** Usually the wrong driver module. If you
bought the V1 rather than the V2 panel, set `"epd_module": "epd7in5"` in
`config.json`.

**`No module named waveshare_epd`.** The `setup.py install` step in step 5
didn't take. Re-run it, and check for errors about `lgpio`.

**Nothing in the sky, ever.** Run `python3 tracker.py`. If it prints an error,
it's the network. If it prints "nothing in the sky", your radius is too small or
your latitude and longitude are swapped — longitude should be the one near ±122
if you're on the US west coast.

**The route is wrong — it says a flight number goes somewhere it doesn't.**
Not your setup, and not a bug: the free route databases key on callsign alone,
and airlines reuse flight numbers, so a stale route comes back looking
authoritative. Since we know both airports' coordinates and where the aircraft
actually is, the code now checks — anything that fails shows "route unconfirmed"
instead of a route and a bogus progress bar. `python3 tracker.py` explains its
reasoning for whatever is overhead right now. Turn the check off with
`"verify_routes": false` if you would rather see the database's best guess.

**Everything worked and now it doesn't.** `journalctl -u flighttracker -n 50`
will tell you what it's complaining about. The free APIs occasionally go down;
the code handles that by carrying on and drawing the "quiet skies" screen rather
than crashing.

---

## Ideas for later

- **Your own antenna.** A $30 RTL-SDR USB dongle plugged into the Pi receives
  ADS-B transmissions directly from the aircraft. No API, no rate limit,
  sub-second updates, works with the internet down — and there's something
  genuinely different about a display that's listening to the planes rather than
  looking them up. `readsb` or `dump1090-fa` on the Pi produces a local
  `aircraft.json` in the same shape as the adsb.lol response, so it's close to a
  drop-in swap in `tracker.py`.
- **Interesting-plane alerts.** Watch for rare aircraft types, military
  callsigns, or emergency squawks (7500/7600/7700) and push a phone
  notification.
- **A "seen" logbook.** Keep a running tally of every distinct aircraft that has
  passed overhead. This gets addictive quickly.
- **Second screen at a different scale** — a small panel showing just the count,
  a big one showing the card.
