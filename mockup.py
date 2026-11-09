#!/usr/bin/env python3
"""Print the panel at its exact physical size, before you own a panel.

The browser preview tells you the layout is right. It does not tell you whether
7.5 inches is big enough to read from the sofa — a laptop screen shows the card
two or three times larger than the real thing. This makes a PDF with the card at
exactly the panel's real dimensions, so you can print it, cut it out, and tape it
where the frame will hang.

    python3 mockup.py            # live data — the sky over your house right now
    python3 mockup.py --demo     # sample data, no internet needed
    python3 mockup.py --compare  # one page per layout, to pick between them
    python3 mockup.py --from=preview.png

Then print it **at 100% / Actual Size**. In the macOS print dialog that means
Scale: 100%, *not* "Scale to Fit". Check it with the ruler printed on the page.

Uses Pillow only — the same dependency the rest of the project already has.
"""

from __future__ import annotations

import os
import sys

from PIL import Image, ImageDraw

import render
from tracker import Tracker, load_config

HERE = os.path.dirname(os.path.abspath(__file__))

DPI = 300

# Waveshare 7.5" V2, from the datasheet. The active area is the part that shows
# pixels; the outline is the whole piece of glass, which is what has to fit
# behind the mat.
ACTIVE_MM = (163.2, 97.92)
OUTLINE_MM = (170.2, 111.2)

PAGE_MM = (215.9, 279.4)          # US Letter portrait
A4_MM = (210.0, 297.0)


def mm(value: float) -> int:
    """Millimetres to pixels at our print resolution."""
    return int(round(value / 25.4 * DPI))


def build_page(card: Image.Image, page_mm=PAGE_MM, label: str = "") -> Image.Image:
    page = Image.new("L", (mm(page_mm[0]), mm(page_mm[1])), 255)
    draw = ImageDraw.Draw(page)

    active_w, active_h = mm(ACTIVE_MM[0]), mm(ACTIVE_MM[1])
    outline_w, outline_h = mm(OUTLINE_MM[0]), mm(OUTLINE_MM[1])

    # NEAREST, not LANCZOS: the panel really does have 800x480 discrete pixels
    # at this size, and smoothing them would flatter it.
    scaled = card.convert("L").resize((active_w, active_h), Image.NEAREST)

    top = mm(45)
    active_x = (page.width - active_w) // 2
    page.paste(scaled, (active_x, top))

    # the active area, hard edge — this is what you actually see
    draw.rectangle((active_x, top, active_x + active_w, top + active_h),
                   outline=0, width=3)

    # the glass outline, dashed — this is what has to fit behind the mat
    gx = (page.width - outline_w) // 2
    gy = top - (outline_h - active_h) // 2
    for x in range(gx, gx + outline_w, 24):
        draw.line((x, gy, min(x + 12, gx + outline_w), gy), fill=110, width=2)
        draw.line((x, gy + outline_h, min(x + 12, gx + outline_w),
                   gy + outline_h), fill=110, width=2)
    for y in range(gy, gy + outline_h, 24):
        draw.line((gx, y, gx, min(y + 12, gy + outline_h)), fill=110, width=2)
        draw.line((gx + outline_w, y, gx + outline_w,
                   min(y + 12, gy + outline_h)), fill=110, width=2)

    # Point sizes, converted to pixels at print resolution — a 19px font would
    # come out as 4.5pt on paper, which is unreadable.
    def pt(points: float) -> int:
        return int(round(points / 72 * DPI))

    title = render.font(pt(17), "bold")
    body = render.font(pt(10))
    small = render.font(pt(9))

    margin = mm(20)
    text_width = page.width - 2 * margin

    def wrap(text: str, fnt) -> list:
        words, lines, current = text.split(), [], ""
        for word in words:
            trial = f"{current} {word}".strip()
            if draw.textlength(trial, font=fnt) <= text_width:
                current = trial
            else:
                lines.append(current)
                current = word
        if current:
            lines.append(current)
        return lines

    draw.text((margin, mm(13)), "Waveshare 7.5\" e-Paper — actual size",
              font=title, fill=0)
    note_y = mm(23)
    if label:
        # On its own line — appended to the title it runs off the page edge.
        draw.text((margin, note_y), label, font=render.font(pt(12), "bold"), fill=0)
        note_y += mm(7)
    draw.text((margin, note_y),
              "Print at 100%. In the macOS print dialog: Scale 100%, "
              "not \"Scale to Fit\".", font=body, fill=60)

    caption_y = top + outline_h + mm(14)
    paragraphs = [
        f"Solid line — the active area, {ACTIVE_MM[0]:.1f} x {ACTIVE_MM[1]:.1f} mm. "
        f"That is the whole visible image: 800 x 480 pixels, about 125 per inch.",
        f"Dashed line — the glass, {OUTLINE_MM[0]:.1f} x {OUTLINE_MM[1]:.1f} mm. "
        f"Cut the mat opening to the solid line; the glass hides behind it.",
        "",
        "Cut along the dashed line, tape it where the frame will hang, and look "
        "at it from where you normally sit.",
        "If the flight number is not readable from the sofa, no panel will fix "
        "that — change the layout instead.",
    ]
    line_step = int(pt(9) * 1.55)
    y = caption_y
    for paragraph in paragraphs:
        if not paragraph:
            y += line_step
            continue
        for line in wrap(paragraph, small):
            draw.text((margin, y), line, font=small, fill=40)
            y += line_step
        y += int(line_step * 0.45)

    # A ruler, so the print scale is self-checking.
    ruler_y = y + mm(16)
    ruler_x = margin
    draw.text((ruler_x, ruler_y - mm(8)),
              "Check the print: this line must measure exactly 100 mm.",
              font=small, fill=40)
    draw.line((ruler_x, ruler_y, ruler_x + mm(100), ruler_y), fill=0, width=3)
    for cm_mark in range(0, 11):
        x = ruler_x + mm(cm_mark * 10)
        tick = mm(4) if cm_mark % 5 == 0 else mm(2)
        draw.line((x, ruler_y, x, ruler_y - tick), fill=0, width=3)
    draw.text((ruler_x, ruler_y + mm(2)), "0", font=small, fill=0)
    draw.text((ruler_x + mm(100) - mm(8), ruler_y + mm(2)), "100 mm",
              font=small, fill=0)

    return page


def source_plane(args: set, config: dict):
    """Live data if we can get it, sample data if we cannot."""
    if "--demo" in args:
        return render.demo_plane(), 6, render.demo_book(), render.demo_stats()

    tracker = Tracker(config)
    plane, count = tracker.current()
    if tracker.last_error:
        print(f"could not reach the data source ({tracker.last_error}) — "
              f"falling back to sample data")
        return render.demo_plane(), 6, render.demo_book(), render.demo_stats()
    if plane is None:
        print("nothing overhead right now — printing the quiet-skies screen")

    book, stats = None, None
    if config.get("logbook", True):
        try:
            from logbook import Logbook
            shelf = Logbook(config)
            book = shelf.record(plane) if plane is not None else None
            stats = shelf.stats()
            shelf.close()
        except Exception:
            pass
    return plane, count, book, stats


def cards(args: set, config: dict) -> list:
    """One (label, image) per page."""
    for arg in args:
        if arg.startswith("--from=") or arg.startswith("--from:"):
            return [("", Image.open(arg.split("=", 1)[-1].split(":", 1)[-1]))]

    plane, count, book, stats = source_plane(args, config)
    kwargs = dict(count=count, book=book, stats=stats)

    if "--compare" not in args:
        layout = str(config.get("layout", "alternate")).lower()
        card = "dense" if layout == "dense" else "flight"
        return [(layout, render.render(plane, config, card=card, **kwargs))]

    alternate = dict(config, layout="alternate")
    dense = dict(config, layout="dense")
    return [
        ("alternate — flight card",
         render.render(plane, alternate, card="flight", **kwargs)),
        ("alternate — detail card",
         render.render(plane, alternate, card="detail", **kwargs)),
        ("dense — everything on one screen",
         render.render(plane, dense, **kwargs)),
    ]


def main(argv: list) -> int:
    args = set(argv[1:])
    if "--help" in args or "-h" in args:
        print(__doc__)
        return 0

    config = load_config()
    page_mm = A4_MM if "--a4" in args else PAGE_MM
    pages = [build_page(card, page_mm, label) for label, card in cards(args, config)]

    pdf_path = os.path.join(HERE, "panel-mockup.pdf")
    png_path = os.path.join(HERE, "panel-mockup.png")

    # resolution= is what makes the page come out physically correct: Pillow
    # divides the pixel dimensions by it to get the PDF page size in points.
    pages[0].save(pdf_path, "PDF", resolution=DPI,
                  save_all=True, append_images=pages[1:])
    pages[0].save(png_path, "PNG", dpi=(DPI, DPI))

    print(f"wrote {pdf_path}  ({len(pages)} page{'s' if len(pages) > 1 else ''})")
    print(f"      {png_path}  (first page only)")
    print(f"\nPrint the PDF at 100% (not 'Scale to Fit'), check the 100 mm "
          f"ruler with a real ruler,\nthen cut it out and put it on the wall.")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
