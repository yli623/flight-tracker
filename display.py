#!/usr/bin/env python3
"""Push an image at the e-ink panel — or at preview.png when there isn't one.

The same object is used either way, so run.py never has to care whether the
hardware is attached yet.
"""

from __future__ import annotations

import os

from PIL import Image

HERE = os.path.dirname(os.path.abspath(__file__))


class Display:
    def __init__(self, config: dict):
        self.cfg = config
        display_cfg = config.get("display", {}) or {}
        self.rotate = bool(display_cfg.get("rotate_180", False))
        self.module_name = display_cfg.get("epd_module", "epd7in5_V2")
        self.full_every = int(config.get("full_refresh_every", 20) or 0)
        self.preview_path = os.path.join(HERE, "preview.png")
        self.count = 0
        self.epd = None
        self.hardware = False
        self._initialised = False
        self._try_hardware()

    # ------------------------------------------------------------------
    def _try_hardware(self) -> None:
        try:
            module = __import__(f"waveshare_epd.{self.module_name}",
                                fromlist=[self.module_name])
            self.epd = module.EPD()
            self.hardware = True
        except Exception as exc:
            self.epd = None
            self.hardware = False
            self.reason = f"{type(exc).__name__}: {exc}"

    def describe(self) -> str:
        if self.hardware:
            return f"e-ink panel ({self.module_name})"
        return f"no panel attached — writing {os.path.basename(self.preview_path)}"

    # ------------------------------------------------------------------
    def _prepare(self, image: Image.Image) -> Image.Image:
        if image.mode != "1":
            image = image.convert("1")
        if self.rotate:
            image = image.transpose(Image.ROTATE_180)
        return image

    def show(self, image: Image.Image, force_full: bool = False) -> None:
        image = self._prepare(image)
        self.count += 1

        # Always keep the preview current: it is how you check the panel
        # without walking over to the wall.
        try:
            image.save(self.preview_path)
        except OSError:
            pass

        if not self.hardware:
            return

        # Every so often, a full clear-and-redraw. E-ink builds up ghosting
        # otherwise, and a clean cycle costs four seconds.
        full = force_full or (self.full_every and self.count % self.full_every == 1)

        try:
            if not self._initialised or full:
                self.epd.init()
                self._initialised = True
                if full:
                    self.epd.Clear()
            self.epd.display(self.epd.getbuffer(image))
        except Exception as exc:
            print(f"display error: {type(exc).__name__}: {exc}", flush=True)
            self._initialised = False

    def clear(self) -> None:
        if not self.hardware:
            return
        try:
            self.epd.init()
            self._initialised = True
            self.epd.Clear()
        except Exception as exc:
            print(f"display error: {type(exc).__name__}: {exc}", flush=True)

    def sleep(self) -> None:
        """Deep sleep between updates saves power and is easier on the panel."""
        if not self.hardware:
            return
        try:
            self.epd.sleep()
            self._initialised = False
        except Exception:
            pass

    def close(self) -> None:
        self.sleep()
        try:
            module = __import__("waveshare_epd.epdconfig", fromlist=["epdconfig"])
            module.module_exit()
        except Exception:
            pass
