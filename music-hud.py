
#!/usr/bin/env python3

from ctypes import CDLL
CDLL("libgtk4-layer-shell.so")

import gi
gi.require_version("Gtk", "4.0")
gi.require_version("Gtk4LayerShell", "1.0")

from gi.repository import Gtk, GLib, Gtk4LayerShell as LayerShell

import cairo
import math
import time
import subprocess
import os
import hashlib
import socket
import threading
import json
import re
from pathlib import Path


def rounded_rectangle(cr, x, y, width, height, radius):
    """Draw a rounded rectangle using Cairo primitives."""
    radius = min(radius, width / 2, height / 2)

    cr.new_sub_path()
    cr.arc(x + width - radius, y + radius, radius, -math.pi / 2, 0)
    cr.arc(x + width - radius, y + height - radius, radius, 0, math.pi / 2)
    cr.arc(x + radius, y + height - radius, radius, math.pi / 2, math.pi)
    cr.arc(x + radius, y + radius, radius, math.pi, 3 * math.pi / 2)
    cr.close_path()


# Default physical display size.
# Skins keep their own native/design canvas size; the HUD scales that canvas
# proportionally so the same skin behaves consistently on different systems.
DEFAULT_DISPLAY_WIDTH = 900
DEFAULT_DISPLAY_HEIGHT = 300

MUSIC_DIR = os.path.expanduser(os.environ.get("MUSIC_HUD_MUSIC_DIR", "~/Music"))
CACHE_DIR = os.path.expanduser("~/.cache/music-hud")
SOCKET = os.path.expanduser("~/.cache/music-hud/control.sock")
CAVA_FIFO = os.path.expanduser("~/.cache/music-hud/cava-hud.fifo")
CAVA_CONFIG = os.path.expanduser("~/.config/music-hud/cava.conf")

SKIN_DIR = os.path.expanduser("~/.config/music-hud/skins")
ACTIVE_SKIN_FILE = os.path.expanduser("~/.config/music-hud/active-skin")
SKIN_PNG = os.path.expanduser("~/.config/music-hud/skins/night-city-cyberdeck.png")

os.makedirs(SKIN_DIR, exist_ok=True)

os.makedirs(CACHE_DIR, exist_ok=True)

try:
    os.unlink(SOCKET)
except FileNotFoundError:
    pass


def _hex_rgba(value, alpha=1.0):
    value = value.lstrip("#")
    if len(value) == 6:
        r = int(value[0:2], 16) / 255.0
        g = int(value[2:4], 16) / 255.0
        b = int(value[4:6], 16) / 255.0
        return r, g, b, alpha
    return 1.0, 1.0, 1.0, alpha


def _load_json(path, fallback):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return fallback


DEFAULT_SKIN = {
    "name": "CyberShip",
    "canvas": {"width": 620, "height": 190},
    "colors": {
        "primary": "#00f6ff",
        "secondary": "#ff00e6",
        "accent": "#7dff00",
        "body": "#030912",
        "body_alpha": 0.88,
        "panel": "#081423",
        "panel_alpha": 0.62,
        "text": "#d8ffff",
        "muted": "#8da7b5"
    },
    "geometry": {
        "art": [42, 51, 88],
        "text": [155, 70],
        "controls": [[405, 137], [466, 137], [527, 137]],
        "status": [531, 63],
        "shape": "spaceship"
    }
}


def ensure_cava_config():
    os.makedirs(os.path.dirname(CAVA_CONFIG), exist_ok=True)

    config = """[general]
framerate = 60
bars = 42
sensitivity = 100
autosens = 1
sleep_timer = 0

[input]
method = pipewire
source = auto

[output]
method = raw
raw_target = %s
data_format = ascii
ascii_max_range = 1000
bar_delimiter = 59
frame_delimiter = 10

[smoothing]
noise_reduction = 55

[eq]
1 = 1
2 = 1
3 = 1
4 = 1
""" % CAVA_FIFO

    Path(CAVA_CONFIG).write_text(config)


def metadata_from_path(filename):
    """
    Derive useful metadata from a conventional music path.

    Example:
        Highly Suspect/MCID/Upperdrugs - Highly Suspect.flac
    becomes:
        artist = Highly Suspect
        album  = MCID
        title  = Upperdrugs
    """
    parts = [p for p in filename.replace("\\", "/").split("/") if p]
    stem = Path(parts[-1]).stem if parts else "Unknown Track"

    artist = parts[0] if len(parts) >= 1 else ""
    album = parts[1] if len(parts) >= 2 else ""
    title = stem

    # Strip the common " - Artist" suffix from a filename.
    if artist:
        suffix = " - " + artist
        if title.lower().endswith(suffix.lower()):
            title = title[:-len(suffix)].rstrip(" -")

    # Also handle "Artist - Title" if the folder structure is unusual.
    if not title and " - " in stem:
        title = stem.split(" - ", 1)[-1].strip()

    return artist, album, title


def load_active_skin():
    try:
        with open(ACTIVE_SKIN_FILE, "r", encoding="utf-8") as f:
            name = f.read().strip()
    except Exception:
        name = "cybership"

    path = os.path.join(SKIN_DIR, name + ".json")
    skin = _load_json(path, DEFAULT_SKIN.copy())

    # Merge missing keys from the default.
    merged = json.loads(json.dumps(DEFAULT_SKIN))
    for section in ("colors", "geometry", "canvas", "display"):
        merged.setdefault(section, {})
        merged[section].update(skin.get(section, {}))
    merged.update({k: v for k, v in skin.items() if k not in ("colors", "geometry", "canvas", "display")})
    return merged


def get_display_size(skin, ui_scale=1.0):
    """Return (display_width, display_height, scale) for a skin."""
    canvas = skin.get("canvas", {})

    try:
        native_width = float(canvas.get("width", DEFAULT_DISPLAY_WIDTH))
    except (TypeError, ValueError):
        native_width = float(DEFAULT_DISPLAY_WIDTH)

    try:
        native_height = float(canvas.get("height", DEFAULT_DISPLAY_HEIGHT))
    except (TypeError, ValueError):
        native_height = float(DEFAULT_DISPLAY_HEIGHT)

    if native_width <= 0:
        native_width = float(DEFAULT_DISPLAY_WIDTH)
    if native_height <= 0:
        native_height = float(DEFAULT_DISPLAY_HEIGHT)

    display = skin.get("display", {})
    display_width = display.get("width", DEFAULT_DISPLAY_WIDTH)

    # GTK window sizes are logical pixels. Convert the desired physical
    # display width to logical pixels on scaled/HiDPI displays.
    try:
        ui_scale = float(ui_scale)
        if ui_scale <= 0:
            ui_scale = 1.0
    except (TypeError, ValueError):
        ui_scale = 1.0

    try:
        display_width = float(display_width) / ui_scale
    except (TypeError, ValueError):
        display_width = float(DEFAULT_DISPLAY_WIDTH)

    # An explicit skin scale overrides the default display width.
    if "scale" in display:
        try:
            requested_scale = float(display["scale"])
            if requested_scale > 0:
                display_width = native_width * requested_scale
        except (TypeError, ValueError):
            pass

    if display_width <= 0:
        display_width = float(DEFAULT_DISPLAY_WIDTH)

    scale = display_width / native_width
    display_height = native_height * scale

    return round(display_width), round(display_height), scale


def draw_neon_line(cr, x1, y1, x2, y2, color, width=2.0, glow=10):
    r, g, b, a = _hex_rgba(color, 1.0)
    cr.save()
    for gw, ga in ((glow, 0.08), (glow * 0.55, 0.14)):
        cr.set_line_width(width + gw)
        cr.set_source_rgba(r, g, b, ga)
        cr.move_to(x1, y1)
        cr.line_to(x2, y2)
        cr.stroke()
    cr.set_line_width(width)
    cr.set_source_rgba(r, g, b, a)
    cr.move_to(x1, y1)
    cr.line_to(x2, y2)
    cr.stroke()
    cr.restore()


def draw_neon_arc(cr, cx, cy, radius, start, end, color, width=2.0):
    r, g, b, a = _hex_rgba(color, 0.95)
    cr.save()
    cr.set_line_width(width + 8)
    cr.set_source_rgba(r, g, b, 0.07)
    cr.arc(cx, cy, radius, start, end)
    cr.stroke()
    cr.set_line_width(width)
    cr.set_source_rgba(r, g, b, a)
    cr.arc(cx, cy, radius, start, end)
    cr.stroke()
    cr.restore()


class MusicHUD(Gtk.DrawingArea):

    def __init__(self, window):

        super().__init__()

        self.window = window

        self.skin = load_active_skin()

        self.visualizer = [0] * 42
        self.progress = 0.0
        self.elapsed = 0
        self.duration = 0
        self.time_text = "0:00 / 0:00"

        self.animation = 0.0
        self.animating = False
        self.direction = "in"
        self.hidden = True

        self.artist = ""
        self.title = ""
        self.album = ""
        self.file = ""
        self.playing = False

        self.art_surface = None
        self.last_track = ""

        self.set_draw_func(self.draw)

        click = Gtk.GestureClick()
        click.connect("released", self.on_click)
        self.add_controller(click)

        GLib.timeout_add(16, self.animate)
        GLib.timeout_add(250, self.update_mpd)
        GLib.idle_add(self.update_mpd)
        threading.Thread(target=self.read_cava, daemon=True).start()


    def read_cava(self):

        while True:
            try:
                with open(CAVA_FIFO, "r") as fifo:
                    while True:
                        line = fifo.readline()
                        if not line:
                            break
                        values = []
                        for item in line.strip().split(";"):
                            try:
                                values.append(max(0, min(1000, int(item))))
                            except ValueError:
                                pass

                        if values:
                            self.visualizer = values[:42]
                            if len(self.visualizer) < 42:
                                self.visualizer += [0] * (42 - len(self.visualizer))

                            GLib.idle_add(self.queue_draw)

            except Exception:
                time.sleep(0.25)

    # =====================================================
    # TOGGLE
    # =====================================================

    def toggle(self):

        if self.animating:
            return False

        if self.hidden:
            self.show_hud()
        else:
            self.hide_hud()

        return False


    def show_hud(self):

        self.hidden = False
        self.animating = True
        self.direction = "in"

        self.animation = 0.0

        self.window.set_visible(True)
        self.window.present()


    def hide_hud(self):

        self.animating = True
        self.direction = "out"

        self.animation = 0.0


    # =====================================================
    # ANIMATION
    # =====================================================

    def animate(self):

        if not self.animating:

            if not self.hidden:
                self.queue_draw()

            return True

        self.animation += 0.035

        if self.animation >= 1.0:

            self.animation = 1.0
            self.animating = False

            if self.direction == "out":

                self.hidden = True
                self.window.set_visible(False)

        self.queue_draw()

        return True


    # =====================================================
    # MPD
    # =====================================================

    def mpc(self, args):

        try:

            result = subprocess.run(
                ["mpc"] + args,
                capture_output=True,
                text=True,
                timeout=2
            )

            return result.stdout.strip()

        except Exception:

            return ""


    def _time_to_seconds(self, value):
        try:
            bits = value.split(":")
            if len(bits) == 2:
                return int(bits[0]) * 60 + int(float(bits[1]))
            if len(bits) == 3:
                return int(bits[0]) * 3600 + int(bits[1]) * 60 + int(float(bits[2]))
        except Exception:
            pass
        return 0

    def update_mpd(self):

        artist = self.mpc(["--format", "%artist%", "current"]).strip()
        album = self.mpc(["--format", "%album%", "current"]).strip()
        title = self.mpc(["--format", "%title%", "current"]).strip()
        filename = self.mpc(["--format", "%file%", "current"]).strip()
        current_line = self.mpc(["current"]).strip()
        status = self.mpc(["status"]).strip()

        if filename:
            fa, falbum, ftitle = metadata_from_path(filename)
            self.artist = artist or fa or "Unknown Artist"
            self.album = album or falbum or ""
            self.title = title or ftitle or "Unknown Track"
            self.file = filename
        elif current_line:
            if " - " in current_line:
                parsed_artist, parsed_title = current_line.split(" - ", 1)
            else:
                parsed_artist, parsed_title = "", current_line
            self.artist = artist or parsed_artist or "Unknown Artist"
            self.album = album or self.album or ""
            self.title = title or parsed_title or "Unknown Track"

        if self.file and self.file != self.last_track:
            self.last_track = self.file
            self.art_surface = None
            print(
                f"MUSIC HUD: {self.artist} / {self.album} / {self.title}",
                flush=True
            )
            threading.Thread(
                target=self.load_artwork,
                args=(self.file,),
                daemon=True
            ).start()

        self.playing = "[playing]" in status

        match = re.search(
            r'(\d+):(\d+(?:\.\d+)?)\s*/\s*(\d+):(\d+(?:\.\d+)?)',
            status
        )
        if match:
            elapsed_text = f"{match.group(1)}:{match.group(2)}"
            duration_text = f"{match.group(3)}:{match.group(4)}"
            self.elapsed = self._time_to_seconds(elapsed_text)
            self.duration = self._time_to_seconds(duration_text)
            if self.duration > 0:
                self.progress = max(0.0, min(1.0, self.elapsed / self.duration))
            self.time_text = (
                f"{self.elapsed // 60}:{self.elapsed % 60:02d} / "
                f"{self.duration // 60}:{self.duration % 60:02d}"
            )

        self.queue_draw()
        return True


    # =====================================================
    # ARTWORK
    # =====================================================

    def load_artwork(self, filename):

        full_path = os.path.join(
            MUSIC_DIR,
            filename
        )

        if not os.path.exists(full_path):
            print(f"MUSIC HUD: artwork source not found: {full_path}", flush=True)
            return

        key = hashlib.md5(
            filename.encode()
        ).hexdigest()

        output = os.path.join(
            CACHE_DIR,
            key + ".png"
        )

        def valid_png(path):
            try:
                if not os.path.exists(path):
                    return False

                # Cairo needs a real PNG it can decode.
                surface = cairo.ImageSurface.create_from_png(path)
                return surface.get_width() > 0 and surface.get_height() > 0

            except Exception:
                return False

        # The earlier prototype could leave behind an unusable cache file.
        if not valid_png(output):

            try:
                os.unlink(output)
            except FileNotFoundError:
                pass

            try:
                result = subprocess.run(
                    [
                        "ffmpeg",
                        "-y",
                        "-loglevel",
                        "error",
                        "-i",
                        full_path,
                        "-map",
                        "0:v:0",
                        "-frames:v",
                        "1",
                        "-f",
                        "image2",
                        "-update",
                        "1",
                        output
                    ],
                    capture_output=True,
                    text=True,
                    timeout=20
                )

                if result.returncode != 0:
                    print(
                        "MUSIC HUD: ffmpeg artwork extraction failed:",
                        result.stderr.strip() or f"exit {result.returncode}",
                        flush=True
                    )
                    return

            except Exception as exc:
                print(
                    f"MUSIC HUD: artwork extraction exception: {exc}",
                    flush=True
                )
                return

        if not valid_png(output):
            print(
                f"MUSIC HUD: no usable embedded artwork for {filename}",
                flush=True
            )
            return

        try:

            surface = cairo.ImageSurface.create_from_png(output)

            def update():

                if filename == self.file:

                    self.art_surface = surface
                    print(
                        f"MUSIC HUD: artwork loaded: {filename}",
                        flush=True
                    )
                    self.queue_draw()

                return False

            GLib.idle_add(update)

        except Exception as exc:
            print(
                f"MUSIC HUD: cairo artwork load failed: {exc}",
                flush=True
            )


    # =====================================================
    # BUTTONS
    # =====================================================

    def on_click(self, gesture, n_press, x, y):

        if self.hidden or self.animating:
            return

        native_width = 1100.0
        native_height = 322.0
        widget_width = max(1.0, float(self.get_width()))
        widget_height = max(1.0, float(self.get_height()))
        scale = min(widget_width / native_width, widget_height / native_height)
        if scale <= 0:
            return

        draw_width = native_width * scale
        draw_height = native_height * scale
        left = (widget_width - draw_width) / 2.0
        top = (widget_height - draw_height) / 2.0

        x = (x - left) / scale
        y = (y - top) / scale

        bob = math.sin(time.monotonic() * 2.0) * 2.0

        # These match the live controls painted over the reference skin.
        buttons = {
            "previous": (560, 245 + bob),
            "play": (630, 245 + bob),
            "next": (700, 245 + bob),
        }

        for name, (bx, by) in buttons.items():
            if math.hypot(x - bx, y - by) < 30:
                if name == "previous":
                    self.mpc(["prev"])
                elif name == "play":
                    self.mpc(["toggle"])
                else:
                    self.mpc(["next"])
                return


    # =====================================================
    # DRAW
    # =====================================================

    def draw(self, area, cr, width, height):

        cr.set_operator(cairo.OPERATOR_CLEAR)
        cr.paint()
        cr.set_operator(cairo.OPERATOR_OVER)

        # IMPORTANT: use the actual DrawingArea size supplied by GTK.
        # This avoids guessing how the compositor/GTK reports HiDPI sizes.
        # The complete 1100x322 design is always fitted into the widget.
        native_width = 1100.0
        native_height = 322.0

        if width <= 0 or height <= 0:
            return True

        display_scale = min(
            float(width) / native_width,
            float(height) / native_height
        )

        draw_width = native_width * display_scale
        draw_height = native_height * display_scale
        left = (float(width) - draw_width) / 2.0
        top = (float(height) - draw_height) / 2.0

        cr.save()
        cr.translate(left, top)
        cr.scale(display_scale, display_scale)

        t = max(0.0, min(1.0, self.animation))
        ease = 1.0 - pow(1.0 - t, 3)

        if self.direction == "in":
            xoff = -1150 + 1150 * ease
        else:
            xoff = 1150 * ease

        bob = 0.0
        if not self.animating and not self.hidden:
            bob = math.sin(time.monotonic() * 2.0) * 2.0

        skin_filename = self.skin.get("skin_png", "")
        skin_path = os.path.join(SKIN_DIR, skin_filename)

        # Subtle animated electrical/hover field beneath the ship.
        # It is deliberately low-opacity so the new blue energy in the base
        # artwork remains the hero effect.
        now = time.monotonic()

        cr.save()
        cr.set_line_cap(cairo.LINE_CAP_ROUND)

        for j, phase in enumerate((0.0, 1.9, 3.8)):
            base_y = 294 + j * 5
            amp = 3.5 + j * 0.8
            speed = 1.8 + j * 0.25
            alpha = 0.10 + 0.045 * (
                0.5 + 0.5 * math.sin(now * speed + phase)
            )

            cr.set_line_width(1.4 if j else 2.0)
            cr.set_source_rgba(0.05, 0.55, 1.0, alpha)
            cr.new_path()

            for step in range(0, 111):
                xx = step * 10.0
                yy = base_y + math.sin(
                    xx * 0.045 + now * speed + phase
                ) * amp

                if step == 0:
                    cr.move_to(xx, yy)
                else:
                    cr.line_to(xx, yy)

            cr.stroke()

        # A few tiny blue electrical sparks under the hull.
        for i in range(9):
            phase = i * 1.73
            xx = 120 + ((i * 103) % 820)
            yy = 292 + 17 * (0.5 + 0.5 * math.sin(now * 2.2 + phase))
            spark_alpha = 0.08 + 0.16 * (
                0.5 + 0.5 * math.sin(now * 3.4 + phase)
            )

            cr.set_source_rgba(0.08, 0.65, 1.0, spark_alpha)
            cr.arc(xx, yy, 1.2 + 0.8 * (i % 2), 0, math.tau)
            cr.fill()

        cr.restore()

        try:
            surface = cairo.ImageSurface.create_from_png(skin_path)
            cr.save()
            cr.translate(xoff, bob)
            cr.set_source_surface(surface, 0, 0)
            cr.paint()
            cr.restore()
        except Exception as exc:
            print(f"MUSIC HUD: skin render failed: {exc}", flush=True)
            cr.restore()
            return True

        ox = xoff
        oy = bob

        def X(v):
            return v + ox

        def Y(v):
            return v + oy

        primary = (0.0, 0.91, 1.0)
        secondary = (1.0, 0.08, 0.84)
        yellow = (1.0, 0.90, 0.0)
        white = (0.94, 1.0, 1.0)
        muted = (0.55, 0.66, 0.70)
        panel = (0.003, 0.008, 0.012)

        # Completely cover the music-player area baked into the artwork.
        # The chassis and album/reactor art remain visible.
        cr.save()
        cr.set_source_rgba(*panel, 1.0)
        rounded_rectangle(cr, X(270), Y(52), 505, 189, 20)
        cr.fill()
        cr.restore()

        # LIVE ALBUM ART -------------------------------------------------
        if self.art_surface:
            art_x, art_y, art_size = X(103), Y(66), 140

            cr.save()
            cr.arc(
                art_x + art_size / 2,
                art_y + art_size / 2,
                art_size / 2,
                0,
                math.tau,
            )
            cr.clip()

            iw = self.art_surface.get_width()
            ih = self.art_surface.get_height()
            art_scale = max(art_size / iw, art_size / ih)
            nw, nh = iw * art_scale, ih * art_scale
            px = art_x + (art_size - nw) / 2
            py = art_y + (art_size - nh) / 2

            cr.scale(art_scale, art_scale)
            cr.set_source_surface(
                self.art_surface,
                px / art_scale,
                py / art_scale,
            )
            cr.paint()
            cr.restore()

        # Reactor ring.
        cr.set_line_width(5)
        cr.set_source_rgba(*yellow, 0.98)
        cr.arc(X(178), Y(154), 86, 0, math.tau)
        cr.stroke()

        sweep = (time.monotonic() * 1.4) % math.tau
        cr.set_line_width(2)
        cr.set_source_rgba(*primary, 0.95)
        cr.arc(X(178), Y(154), 96, sweep, sweep + 1.0)
        cr.stroke()

        # LIVE TRACK INFORMATION -----------------------------------------
        cr.select_font_face(
            "Sans",
            cairo.FONT_SLANT_NORMAL,
            cairo.FONT_WEIGHT_BOLD,
        )

        cr.set_font_size(28)
        cr.set_source_rgba(*yellow, 0.98)
        cr.move_to(X(295), Y(98))
        cr.show_text((self.artist or "Unknown Artist")[:30])

        cr.set_font_size(22)
        cr.set_source_rgba(*primary, 0.98)
        cr.move_to(X(295), Y(128))
        cr.show_text((self.title or "Unknown Track")[:42])

        cr.set_font_size(16)
        cr.set_source_rgba(*white, 0.78)
        cr.move_to(X(295), Y(153))
        cr.show_text((self.album or "MPD")[:45])

        # LIVE PROGRESS --------------------------------------------------
        px = X(295)
        py = Y(185)
        pw = 220

        cr.set_line_width(4)
        cr.set_source_rgba(*muted, 0.50)
        cr.move_to(px, py)
        cr.line_to(px + pw, py)
        cr.stroke()

        cr.set_source_rgba(*yellow, 0.98)
        cr.move_to(px, py)
        cr.line_to(px + pw * self.progress, py)
        cr.stroke()

        cr.set_source_rgba(*yellow, 1.0)
        cr.arc(px + pw * self.progress, py, 5, 0, math.tau)
        cr.fill()

        cr.select_font_face(
            "Monospace",
            cairo.FONT_SLANT_NORMAL,
            cairo.FONT_WEIGHT_NORMAL,
        )
        cr.set_font_size(13)
        cr.set_source_rgba(*white, 0.90)
        cr.move_to(px, Y(208))
        cr.show_text(self.time_text)

        cr.set_source_rgba(*muted, 0.85)
        cr.move_to(px + 95, Y(208))
        cr.show_text("FLAC  1013 KBPS  44.1 KHZ")

        # LIVE CAVA ------------------------------------------------------
        bars = self.visualizer[:42]
        if len(bars) < 42:
            bars += [0] * (42 - len(bars))

        vx, vy, vw, vh = 505, 220, 270, 45
        gap = 2.0
        bw = (vw - gap * 41) / 42

        for i, val in enumerate(bars):
            level = max(0.0, min(1.0, val / 1000.0))
            hbar = max(1.0, level * vh)
            xx = X(vx + i * (bw + gap))
            yy = Y(vy - hbar)

            col = secondary if i < 14 or i > 30 else primary

            cr.set_source_rgba(*col, 0.14)
            cr.rectangle(xx - 1, yy - 2, bw + 2, hbar + 3)
            cr.fill()

            cr.set_source_rgba(*col, 0.95)
            cr.rectangle(xx, yy, bw, hbar)
            cr.fill()

        # STATUS ---------------------------------------------------------
        pulse = (math.sin(time.monotonic() * 5) + 1) / 2
        status_col = yellow if self.playing else secondary

        cr.set_source_rgba(*status_col, 0.35 + pulse * 0.55)
        cr.arc(X(742), Y(82), 5, 0, math.tau)
        cr.fill()

        cr.set_font_size(11)
        cr.set_source_rgba(*status_col, 0.95)
        cr.move_to(X(753), Y(86))
        cr.show_text("PLAYING" if self.playing else "PAUSED")

        # LIVE CONTROLS --------------------------------------------------
        controls = [
            (560, 245, "prev"),
            (630, 245, "play"),
            (700, 245, "next"),
        ]

        for bx, by, kind in controls:
            bx, by = X(bx), Y(by)
            col = primary if kind == "play" else yellow

            cr.set_line_width(2)
            cr.set_source_rgba(*col, 0.18)
            cr.arc(bx, by, 30, 0, math.tau)
            cr.fill()

            cr.set_source_rgba(*col, 0.90)
            cr.arc(bx, by, 25, 0, math.tau)
            cr.stroke()

            cr.set_source_rgba(*col, 0.98)

            if kind == "play":
                if self.playing:
                    cr.rectangle(bx - 9, by - 13, 7, 26)
                    cr.rectangle(bx + 3, by - 13, 7, 26)
                    cr.fill()
                else:
                    cr.move_to(bx - 9, by - 14)
                    cr.line_to(bx - 9, by + 14)
                    cr.line_to(bx + 15, by)
                    cr.close_path()
                    cr.fill()

            elif kind == "prev":
                cr.rectangle(bx - 13, by - 13, 5, 26)
                cr.fill()
                cr.move_to(bx + 11, by - 13)
                cr.line_to(bx - 7, by)
                cr.line_to(bx + 11, by + 13)
                cr.close_path()
                cr.fill()

            else:
                cr.move_to(bx - 11, by - 13)
                cr.line_to(bx + 7, by)
                cr.line_to(bx - 11, by + 13)
                cr.close_path()
                cr.fill()
                cr.rectangle(bx + 9, by - 13, 5, 26)
                cr.fill()

        cr.set_font_size(10)
        cr.set_source_rgba(*muted, 0.75)
        cr.move_to(X(295), Y(286))
        cr.show_text("MPD // NIGHT CITY RADIO // SYSTEMS ONLINE")

        cr.restore()

        return True


# =========================================================
# APPLICATION
# =========================================================

class App(Gtk.Application):

    def __init__(self):

        super().__init__(
            application_id="com.omarchy.music-hud"
        )

        self.window = None
        self.hud = None
        self.pending_toggle = False

        # Keep GTK alive while hidden
        self.hold()

        # Create the HUD once GTK's main loop is running.
        # This avoids relying on Gtk.Application activation.
        GLib.idle_add(self.create_hud)

        # Start the HUD CAVA instance.
        self.cava_process = None
        self.start_cava()

        # Start control socket immediately
        threading.Thread(
            target=self.control_server,
            daemon=True
        ).start()


    def reload_skin(self):
        self.hud.skin = load_active_skin()
        hud_width, hud_height, _ = get_display_size(
            self.hud.skin,
            self.window.get_scale_factor()
        )
        self.window.set_default_size(hud_width, hud_height)
        self.hud.queue_draw()

    def start_cava(self):

        try:
            ensure_cava_config()

            try:
                os.unlink(CAVA_FIFO)
            except FileNotFoundError:
                pass

            os.mkfifo(CAVA_FIFO, 0o600)

            self.cava_process = subprocess.Popen(
                ["cava", "-p", CAVA_CONFIG],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL
            )

            print("MUSIC HUD: CAVA visualizer started", flush=True)

        except Exception as exc:
            print(f"MUSIC HUD: CAVA start failed: {exc}", flush=True)

    def create_hud(self):

        if self.window:
            return

        # Use a plain Gtk.Window rather than Gtk.ApplicationWindow.
        # Gtk.ApplicationWindow + the current GTK/Python 3.14 stack is
        # crashing in gtk_window_set_application() before the HUD appears.
        self.window = Gtk.Window()
        LayerShell.init_for_window(
            self.window
        )

        LayerShell.set_layer(
            self.window,
            LayerShell.Layer.TOP
        )

        LayerShell.set_anchor(
            self.window,
            LayerShell.Edge.TOP,
            True
        )

        LayerShell.set_margin(
            self.window,
            LayerShell.Edge.TOP,
            80
        )

        LayerShell.set_exclusive_zone(
            self.window,
            0
        )

        LayerShell.set_keyboard_mode(
            self.window,
            LayerShell.KeyboardMode.NONE
        )

        LayerShell.set_namespace(
            self.window,
            "music-hud"
        )


        # Size the window from the skin's native canvas while keeping a
        # sensible default physical width across different systems.
        skin = load_active_skin()
        hud_width, hud_height, _ = get_display_size(
            skin,
            self.window.get_scale_factor()
        )

        self.window.set_default_size(
            hud_width,
            hud_height
        )

        self.window.set_decorated(
            False
        )


        css = Gtk.CssProvider()

        css.load_from_data(
            b"""
            window {
                background: transparent;
                background-color: rgba(0,0,0,0);
            }

            drawingarea {
                background: transparent;
                background-color: rgba(0,0,0,0);
            }
            """
        )

        Gtk.StyleContext.add_provider_for_display(
            self.window.get_display(),
            css,
            Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION
        )


        self.hud = MusicHUD(
            self.window
        )

        self.window.set_child(
            self.hud
        )

        self.window.set_visible(False)

        # If a toggle arrived before the HUD finished being created,
        # honour it now.
        if self.pending_toggle:

            self.pending_toggle = False

            GLib.idle_add(
                self.hud.toggle
            )


    def control_server(self):

        server = socket.socket(
            socket.AF_UNIX,
            socket.SOCK_STREAM
        )

        server.bind(SOCKET)
        server.listen(5)

        os.chmod(
            SOCKET,
            0o600
        )

        while True:

            try:

                conn, _ = server.accept()

                command = conn.recv(32).decode().strip()

                conn.close()

                if command == "reload":
                    GLib.idle_add(self.reload_skin)
                    continue

                if command == "clear-art-cache":
                    def clear_cache():
                        for item in Path(CACHE_DIR).glob("*.png"):
                            try:
                                item.unlink()
                            except OSError:
                                pass
                        if self.file:
                            threading.Thread(
                                target=self.load_artwork,
                                args=(self.file,),
                                daemon=True
                            ).start()
                        return False
                    GLib.idle_add(clear_cache)
                    continue

                if command == "toggle":

                    print("MUSIC HUD: TOGGLE RECEIVED", flush=True)

                    def do_toggle():

                        if self.hud is not None:
                            self.hud.toggle()

                        else:
                            self.pending_toggle = True

                        return False

                    GLib.idle_add(do_toggle)

            except Exception:

                pass


app = App()


app.run()


