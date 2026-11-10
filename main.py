#!/usr/bin/env python3
"""WoW fishing bot.

Flow:
  1. cast
  2. find the gear icon (template gear.png) in the centre search band
  3. find the bobber (template bobber.png) just below the gear
  4. lock a square around the bobber and record the red feather's Y position
  5. watch the feather; if it moves in Y (or vanishes) for a few frames -> bite
  6. press the interact key to loot, recast, repeat

Needs gear.png and bobber.png next to this script (use the Grab buttons).

Platforms
  Windows: pip install opencv-python numpy pillow mss pyautogui
  macOS:   pip install opencv-python numpy pillow pyautogui pyobjc-core pyobjc-framework-Quartz
           (grant Screen Recording + Accessibility to your Terminal/Python)
  Linux:   pip install opencv-python numpy pillow pipewire-capture ; needs ydotool
"""
from __future__ import annotations

import json
import random
import re
import subprocess
import sys
import threading
import time
from enum import Enum, auto
from pathlib import Path
from statistics import median

import cv2
import numpy as np

try:
    import tkinter as tk
    from tkinter import ttk, messagebox
except ImportError:
    print("tkinter not available")
    sys.exit(1)

IS_WIN = sys.platform == "win32"
IS_MAC = sys.platform == "darwin"
USE_PYAUTOGUI = IS_WIN or IS_MAC          # Linux uses ydotool instead
if getattr(sys, "frozen", False):
    # Packaged with PyInstaller: __file__ points into a temp folder that is wiped on exit,
    # so keep gear.png / bobber.png / config.json somewhere that persists.
    ROOT = Path(sys.executable).resolve().parent
    if IS_MAC and ".app/Contents/" in str(ROOT):
        ROOT = Path.home() / "Library" / "Application Support" / "WoWFishingBot"
        ROOT.mkdir(parents=True, exist_ok=True)
else:
    ROOT = Path(__file__).resolve().parent
GEAR_TMPL = ROOT / "gear.png"
BOBBER_TMPL = ROOT / "bobber.png"
CONFIG = ROOT / "config.json"

if IS_WIN:
    # Without this, display scaling > 100% makes the captured window area wrong.
    try:
        import ctypes
        try:
            ctypes.windll.shcore.SetProcessDpiAwareness(2)   # per-monitor
        except Exception:
            ctypes.windll.user32.SetProcessDPIAware()
    except Exception:
        pass

if USE_PYAUTOGUI:
    import pyautogui

    pyautogui.FAILSAFE = False
    pyautogui.PAUSE = 0.05


class Phase(Enum):
    IDLE = auto()
    LOOKING_FOR_GEAR = auto()
    LOOKING_FOR_BOBBER = auto()
    WATCHING = auto()


# key, label, kind, min, max, step, default, help
PARAMS = [
    ("gear_lock",     "Gear lock",       float, 0.1, 0.95, 0.01, 0.45, "Min template score to accept the gear"),
    ("lock_score",    "Bobber lock",     float, 0.1, 0.95, 0.01, 0.35, "Min template score to accept the bobber"),
    ("min_red",       "Min red pixels",  int,   2,   200,  1,    8,    "Red feather pixels needed to count as seen"),
    ("bite_px",       "Bite shift (px)", int,   2,   100,  1,    10,   "Feather Y move from baseline that counts as a bite"),
    ("bite_frames",   "Bite frames",     int,   1,   10,   1,    3,    "Consecutive frames the bite must last"),
    ("settle",        "Settle (s)",      float, 0.3, 4.0,  0.1,  1.0,  "Time after lock used to measure baseline Y"),
    ("h_min",         "H min %",         int,   0,   50,   1,    35,   "Left edge of gear search band"),
    ("h_max",         "H max %",         int,   50,  100,  1,    65,   "Right edge of gear search band"),
    ("v_min",         "V min %",         int,   0,   50,   1,    30,   "Top edge of gear search band"),
    ("v_max",         "V max %",         int,   50,  100,  1,    70,   "Bottom edge of gear search band"),
    ("cast_anim",     "Cast anim (s)",   float, 0.2, 3.0,  0.1,  1.0,  "Wait after casting before looking"),
    ("loot_wait",     "Loot wait (s)",   float, 0.5, 5.0,  0.1,  1.5,  "Wait after reel for auto-loot"),
    ("seek_seconds",  "Seek timeout",    float, 3,   20,   0.5,  8.0,  "Recast if gear/bobber not found"),
    ("watch_seconds", "Watch timeout",   float, 10,  60,   1,    25.0, "Recast if no bite in this time"),
    ("interval",      "Loop interval",   float, 0.01, 0.5, 0.01, 0.05, "Seconds between frames"),
    ("start_delay",   "Start delay (s)", float, 0,   10,   1,    3.0,  "Time to focus WoW after pressing Start"),
    ("target",        "Target fish",     int,   1,   500,  1,    100,  "Stop after this many catches"),
    ("jitter",        "Timing variance %", int, 0,   100,  5,    25,   "Random ± applied to the cast and loot waits"),
    ("react_min",     "Reaction min (s)", float, 0,  3.0,  0.05, 0.2,  "Shortest pause between a bite and the reel press"),
    ("react_max",     "Reaction max (s)", float, 0,  3.0,  0.05, 0.7,  "Longest pause between a bite and the reel press"),
]
DEFAULT_KEY = "<"
DEFAULTS = {p[0]: p[6] for p in PARAMS}
DEFAULTS["cast_key"] = DEFAULT_KEY   # string setting, edited with the key picker


# ---------------------------------------------------------------- input

# Linux (ydotool) evdev codes for the keys the picker can produce.
# Anything else on Linux is stored as "code:<n>" straight from the key press.
EVDEV = {"<": 86, "space": 57, "enter": 28, "tab": 15, "esc": 1, "`": 41, "-": 12, "=": 13,
         ",": 51, ".": 52, "/": 53, ";": 39, "'": 40, "[": 26, "]": 27, "\\": 43}
for _i, _ch in enumerate("1234567890"):
    EVDEV[_ch] = 2 + _i
for _row, _start in (("qwertyuiop", 16), ("asdfghjkl", 30), ("zxcvbnm", 44)):
    for _i, _ch in enumerate(_row):
        EVDEV[_ch] = _start + _i
for _n in range(1, 11):
    EVDEV[f"f{_n}"] = 58 + _n
EVDEV["f11"], EVDEV["f12"] = 87, 88


def key_supported(key: str) -> bool:
    if not key:
        return False
    if USE_PYAUTOGUI:
        return key in pyautogui.KEYBOARD_KEYS
    return key in EVDEV or (key.startswith("code:") and key[5:].isdigit())


def jittered(base: float, pct: float) -> float:
    """base ± pct% (uniform), never negative."""
    spread = max(0.0, float(pct)) / 100.0
    return max(0.0, base * random.uniform(1 - spread, 1 + spread))


def press_key(key: str):
    """Tap a key with a short, randomly varying hold time like a real keypress."""
    hold = random.uniform(0.04, 0.12)
    if USE_PYAUTOGUI:
        pyautogui.keyDown(key)
        time.sleep(hold)
        pyautogui.keyUp(key)
    else:
        code = int(key[5:]) if key.startswith("code:") else EVDEV[key]
        subprocess.run(["ydotool", "key", f"{code}:1"], check=False)
        time.sleep(hold)
        subprocess.run(["ydotool", "key", f"{code}:0"], check=False)


# ---------------------------------------------------------------- vision

SCALES = [0.5, 0.65, 0.8, 1.0, 1.25, 1.5, 1.75, 2.0]

PREVIEW_W, PREVIEW_H = 512, 288   # live view canvas
ZOOM_W, ZOOM_H = 200, 288         # locked-bobber zoom canvas


def match_template(bgr, tmpl_gray, roi=None, scales=SCALES):
    """Multi-scale template match. roi=(x1,y1,x2,y2) in frame coords.

    Returns (score, (cx, cy), (x, y, w, h)) in frame coords, or None.
    """
    if bgr is None or tmpl_gray is None:
        return None
    H, W = bgr.shape[:2]
    if roi:
        x1, y1, x2, y2 = roi
        x1, y1 = max(0, int(x1)), max(0, int(y1))
        x2, y2 = min(W, int(x2)), min(H, int(y2))
    else:
        x1, y1, x2, y2 = 0, 0, W, H
    if x2 <= x1 or y2 <= y1:
        return None

    gray = cv2.cvtColor(bgr[y1:y2, x1:x2], cv2.COLOR_BGR2GRAY)
    th, tw = tmpl_gray.shape[:2]
    best = None
    for s in scales:
        w, h = int(tw * s), int(th * s)
        if w < 8 or h < 8 or w > gray.shape[1] or h > gray.shape[0]:
            continue
        interp = cv2.INTER_AREA if s < 1 else cv2.INTER_LINEAR
        scaled = cv2.resize(tmpl_gray, (w, h), interpolation=interp)
        res = cv2.matchTemplate(gray, scaled, cv2.TM_CCOEFF_NORMED)
        _, score, _, loc = cv2.minMaxLoc(res)
        if best is None or score > best[0]:
            x, y = loc
            best = (float(score),
                    (x + w // 2 + x1, y + h // 2 + y1),
                    (x + x1, y + y1, w, h))
    return best


def red_centroid(bgr, region, min_pixels=8):
    """Centroid Y (frame coords) and pixel count of red inside region=(x,y,w,h)."""
    x, y, w, h = region
    H, W = bgr.shape[:2]
    x1, y1 = max(0, int(x)), max(0, int(y))
    x2, y2 = min(W, int(x + w)), min(H, int(y + h))
    if x2 <= x1 or y2 <= y1:
        return None
    hsv = cv2.cvtColor(bgr[y1:y2, x1:x2], cv2.COLOR_BGR2HSV)
    mask = (cv2.inRange(hsv, (0, 80, 60), (12, 255, 255))
            | cv2.inRange(hsv, (168, 80, 60), (180, 255, 255)))
    ys, _ = np.where(mask > 0)
    if len(ys) < min_pixels:
        return None
    return float(ys.mean() + y1), int(len(ys))


def pad_box(box, px, py):
    x, y, w, h = box
    return (x - px, y - py, w + 2 * px, h + 2 * py)


# ---------------------------------------------------------------- capture

class PipewireSource:
    def __init__(self):
        from pipewire_capture import PortalCapture, CaptureStream, is_available
        if not is_available():
            raise RuntimeError("no capture source")
        self.session = PortalCapture().select_window()
        if self.session is None:
            raise RuntimeError("cancelled")
        self.stream = CaptureStream(
            self.session.fd, self.session.node_id,
            self.session.width, self.session.height,
        )
        self.stream.start()

    def grab(self):
        frame = self.stream.get_frame()
        if frame is None:
            return None
        return cv2.cvtColor(frame, cv2.COLOR_BGRA2BGR)

    def close(self):
        try:
            self.stream.stop()
            self.session.close()
        except Exception:
            pass


class WindowsSource:
    def __init__(self):
        import mss
        self._mss = mss.mss()
        self._hwnd = self._find_wow()
        if not self._hwnd:
            raise RuntimeError("World of Warcraft window not found")

    def _find_wow(self):
        import ctypes
        from ctypes import wintypes
        user32 = ctypes.windll.user32
        found = []

        @ctypes.WINFUNCTYPE(ctypes.c_bool, wintypes.HWND, wintypes.LPARAM)
        def cb(hwnd, _):
            if user32.IsWindowVisible(hwnd):
                n = user32.GetWindowTextLengthW(hwnd) + 1
                buf = ctypes.create_unicode_buffer(n)
                user32.GetWindowTextW(hwnd, buf, n)
                title = buf.value.lower()
                if "world of warcraft" in title or title == "wow":
                    found.append(hwnd)
            return True

        user32.EnumWindows(cb, 0)
        return found[0] if found else None

    def _client_box(self):
        import ctypes
        from ctypes import wintypes
        user32 = ctypes.windll.user32
        rect = wintypes.RECT()
        user32.GetClientRect(self._hwnd, ctypes.byref(rect))
        pt = wintypes.POINT(0, 0)
        user32.ClientToScreen(self._hwnd, ctypes.byref(pt))
        return {
            "left": pt.x,
            "top": pt.y,
            "width": rect.right - rect.left,
            "height": rect.bottom - rect.top,
        }

    def grab(self):
        box = self._client_box()
        if box["width"] <= 0 or box["height"] <= 0:
            return None
        shot = np.array(self._mss.grab(box))
        return cv2.cvtColor(shot, cv2.COLOR_BGRA2BGR)

    def close(self):
        try:
            self._mss.close()
        except Exception:
            pass


class MacSource:
    """Captures the WoW window with Quartz (needs Screen Recording permission).

    Frames are in physical pixels (2x on Retina). Nothing is clicked by position,
    so no coordinate scaling is needed; templates just have to be grabbed here too.
    """

    def __init__(self):
        try:
            import Quartz
        except ImportError:
            raise RuntimeError("Missing dependency: pip install pyobjc-core pyobjc-framework-Quartz")
        self.Q = Quartz
        preflight = getattr(Quartz, "CGPreflightScreenCaptureAccess", None)
        if preflight and not preflight():
            request = getattr(Quartz, "CGRequestScreenCaptureAccess", None)
            if request:
                request()
            raise RuntimeError(
                "Screen Recording permission needed.\n"
                "System Settings > Privacy & Security > Screen Recording: enable your "
                "Terminal / Python, then restart this app.")
        self._wid = self._find_wow()
        if self._wid is None:
            raise RuntimeError("World of Warcraft window not found (is it open and not minimized?)")

    def _find_wow(self):
        Q = self.Q
        opts = Q.kCGWindowListOptionOnScreenOnly | Q.kCGWindowListExcludeDesktopElements
        best = None
        for w in Q.CGWindowListCopyWindowInfo(opts, Q.kCGNullWindowID) or []:
            owner = str(w.get("kCGWindowOwnerName", "")).lower()
            name = str(w.get("kCGWindowName", "")).lower()
            if "world of warcraft" not in owner and "world of warcraft" not in name:
                continue
            if w.get("kCGWindowLayer", 0) != 0:
                continue
            b = w.get("kCGWindowBounds", {})
            area = b.get("Width", 0) * b.get("Height", 0)
            if area > 0 and (best is None or area > best[0]):
                best = (area, w["kCGWindowNumber"])
        return best[1] if best else None

    def grab(self):
        Q = self.Q
        img = Q.CGWindowListCreateImage(
            Q.CGRectNull, Q.kCGWindowListOptionIncludingWindow, self._wid,
            Q.kCGWindowImageBoundsIgnoreFraming | Q.kCGWindowImageBestResolution)
        if img is None:
            self._wid = self._find_wow() or self._wid   # window may have been re-created
            return None
        w, h = Q.CGImageGetWidth(img), Q.CGImageGetHeight(img)
        if w == 0 or h == 0:
            return None
        bytes_per_row = Q.CGImageGetBytesPerRow(img)
        data = Q.CGDataProviderCopyData(Q.CGImageGetDataProvider(img))
        arr = np.frombuffer(bytes(data), dtype=np.uint8).reshape(h, bytes_per_row // 4, 4)[:, :w, :]
        return cv2.cvtColor(np.ascontiguousarray(arr), cv2.COLOR_BGRA2BGR)

    def close(self):
        pass


def open_source():
    if IS_WIN:
        return WindowsSource()
    if IS_MAC:
        return MacSource()
    return PipewireSource()


# ---------------------------------------------------------------- bot

class FishingBot:
    def __init__(self, gui):
        self.gui = gui
        self.running = False
        self.thread = None
        self.source = None
        self.gear_g = None
        self.bobber_g = None
        self.caught = 0
        self.casts = 0
        self.session_t0 = 0.0
        self._reset_state()

    def _reset_state(self):
        self.phase = Phase.IDLE
        self.t0 = 0.0
        self.gear_box = None
        self.lock_box = None
        self.baseline = None
        self.settle_until = 0.0
        self.settle_ys = []
        self.low_frames = 0

    # ----- lifecycle

    def start(self):
        if self.running:
            return
        gear = cv2.imread(str(GEAR_TMPL), cv2.IMREAD_COLOR)
        bobber = cv2.imread(str(BOBBER_TMPL), cv2.IMREAD_COLOR)
        if gear is None or bobber is None:
            messagebox.showerror(
                "Missing templates",
                "Need gear.png and bobber.png next to the script.\n"
                "Use the 'Grab gear' / 'Grab bobber' buttons.")
            return
        self.gear_g = cv2.cvtColor(gear, cv2.COLOR_BGR2GRAY)
        self.bobber_g = cv2.cvtColor(bobber, cv2.COLOR_BGR2GRAY)

        if not key_supported(self.gui.params["cast_key"]):
            messagebox.showerror("Unsupported key",
                                 f"The key '{self.gui.params['cast_key']}' can't be sent on this system.\n"
                                 "Pick another one with 'Change key'.")
            return

        try:
            self.source = open_source()
        except Exception as e:
            messagebox.showerror("Capture error", str(e))
            return

        self.gui.save_config()
        self.caught = 0
        self.casts = 0
        self.session_t0 = time.monotonic()
        self._reset_state()
        self.running = True
        self.thread = threading.Thread(target=self._loop, daemon=True)
        self.thread.start()
        self.gui.status_var.set("Running — focus WoW")

    def stop(self):
        self.running = False
        if self.thread and self.thread is not threading.current_thread():
            self.thread.join(timeout=1.0)
        if self.source:
            self.source.close()
            self.source = None
        self.phase = Phase.IDLE
        self.gui.status_var.set("Stopped")

    # ----- helpers

    def _recast(self, P):
        press_key(P["cast_key"])
        time.sleep(jittered(P["cast_anim"], P["jitter"]))
        self.casts += 1
        self._reset_state()
        self.phase = Phase.LOOKING_FOR_GEAR
        self.t0 = time.monotonic()

    def _reel(self, P):
        # a human needs a moment to react to the splash
        lo, hi = sorted((P["react_min"], P["react_max"]))
        time.sleep(random.uniform(lo, hi))
        press_key(P["cast_key"])
        time.sleep(jittered(P["loot_wait"], P["jitter"]))
        self.caught += 1
        self._recast(P)

    def _zoom_view(self, frame, lock_box, info, P):
        """Magnified crop of the watched area with baseline / bite lines and feather marker."""
        rx, ry, rw, rh = (int(v) for v in pad_box(lock_box, 8, 40))
        H, W = frame.shape[:2]
        x1, y1, x2, y2 = max(0, rx), max(0, ry), min(W, rx + rw), min(H, ry + rh)
        if x2 <= x1 or y2 <= y1:
            return None
        crop = frame[y1:y2, x1:x2]
        z = min(ZOOM_W / crop.shape[1], ZOOM_H / crop.shape[0])
        view = cv2.resize(crop, (max(1, int(crop.shape[1] * z)), max(1, int(crop.shape[0] * z))),
                          interpolation=cv2.INTER_NEAREST)
        vw = view.shape[1]

        def ly(y):
            return int((y - y1) * z)

        base = info.get("baseline")
        if base is not None:
            cv2.line(view, (0, ly(base)), (vw, ly(base)), (255, 255, 0), 1)           # baseline
            for s in (-1, 1):
                cv2.line(view, (0, ly(base + s * P["bite_px"])),
                         (vw, ly(base + s * P["bite_px"])), (0, 200, 255), 1)         # bite zone
        if info["y"] is not None:
            cv2.circle(view, (vw // 2, ly(info["y"])), 4, (0, 0, 255), -1)            # feather
        return view

    def _publish(self, frame, info, search_band, gear_box, lock_box, P):
        H, W = frame.shape[:2]
        scale = min(PREVIEW_W / W, PREVIEW_H / H)
        small = cv2.resize(frame, (int(W * scale), int(H * scale)))

        def rect(box, color, thick=1, xywh=True):
            if box is None:
                return
            x, y, w, h = box if xywh else (box[0], box[1], box[2] - box[0], box[3] - box[1])
            cv2.rectangle(small, (int(x * scale), int(y * scale)),
                          (int((x + w) * scale), int((y + h) * scale)), color, thick)

        rect(search_band, (255, 255, 0), 1, xywh=False)  # search band
        rect(gear_box, (0, 255, 255), 1)                 # gear
        rect(lock_box, (0, 255, 0), 2)                   # locked bobber square
        zoom = self._zoom_view(frame, lock_box, info, P) if lock_box else None
        self.gui.push(info, small, zoom)

    # ----- main loop

    def _loop(self):
        P = self.gui.params
        time.sleep(P["start_delay"])
        if not self.running:
            return
        self._recast(P)

        while self.running: # and self.caught < P["target"]:
            frame = self.source.grab() if self.source else None
            if frame is None:
                time.sleep(0.03)
                continue

            P = self.gui.params
            now = time.monotonic()
            elapsed = now - self.t0
            H, W = frame.shape[:2]
            band = (int(W * P["h_min"] / 100), int(H * P["v_min"] / 100),
                    int(W * P["h_max"] / 100), int(H * P["v_max"] / 100))

            gear_score = 0.0
            bobber_score = 0.0
            red_y = None
            dy = None

            # --- 1. gear
            if self.phase in (Phase.LOOKING_FOR_GEAR, Phase.LOOKING_FOR_BOBBER):
                hit = match_template(frame, self.gear_g, roi=band)
                if hit:
                    gear_score = hit[0]
                    if gear_score >= P["gear_lock"]:
                        self.gear_box = hit[2]
                        if self.phase == Phase.LOOKING_FOR_GEAR:
                            self.phase = Phase.LOOKING_FOR_BOBBER
                            self.t0 = now
                            elapsed = 0.0

            if self.phase == Phase.LOOKING_FOR_GEAR:
                if elapsed >= P["seek_seconds"]:
                    self._recast(P)

            # --- 2. bobber below the gear
            elif self.phase == Phase.LOOKING_FOR_BOBBER:
                gx, gy, gw, gh = self.gear_box
                cx = gx + gw // 2
                roi = (cx - 110, gy + gh // 2, cx + 110, gy + gh + 260)
                hit = match_template(frame, self.bobber_g, roi=roi)
                if hit:
                    bobber_score = hit[0]
                    box = hit[2]
                    has_red = red_centroid(frame, box, P["min_red"]) is not None
                    if bobber_score >= P["lock_score"] and has_red:
                        # --- 3. lock the square
                        self.lock_box = box
                        self.settle_until = now + P["settle"]
                        self.settle_ys = []
                        self.baseline = None
                        self.low_frames = 0
                        self.phase = Phase.WATCHING
                        self.t0 = now
                        elapsed = 0.0
                if self.phase == Phase.LOOKING_FOR_BOBBER and elapsed >= P["seek_seconds"]:
                    self._recast(P)

            # --- 4. watch the red feather inside the locked square
            elif self.phase == Phase.WATCHING:
                # look a bit beyond the square vertically so a big dip is still seen
                region = pad_box(self.lock_box, 8, 40)
                red = red_centroid(frame, region, P["min_red"])
                red_y = red[0] if red else None

                if now < self.settle_until:
                    if red_y is not None:
                        self.settle_ys.append(red_y)
                else:
                    if self.baseline is None:
                        if len(self.settle_ys) < 3:
                            self._recast(P)  # could not read the feather
                            continue
                        self.baseline = median(self.settle_ys)

                    # feather gone = bobber dipped under water = bite too
                    moved = red_y is None or abs(red_y - self.baseline) >= P["bite_px"]
                    if red_y is not None:
                        dy = red_y - self.baseline

                    if moved:
                        self.low_frames += 1
                    else:
                        self.low_frames = 0
                        # follow slow drift from waves
                        self.baseline = 0.9 * self.baseline + 0.1 * red_y

                    if self.low_frames >= P["bite_frames"]:
                        self._reel(P)
                        continue
                    if elapsed >= P["watch_seconds"]:
                        self._recast(P)
                        continue

            info = {
                "phase": self.phase.name.replace("_", " "),
                "gear": gear_score,
                "bobber": bobber_score,
                "y": red_y,
                "dy": dy,
                "low": self.low_frames,
                "caught": self.caught,
                "casts": self.casts,
                "baseline": self.baseline,
                "settling": self.phase == Phase.WATCHING and self.baseline is None,
            }
            self._publish(frame, info, band, self.gear_box, self.lock_box, P)
            time.sleep(P["interval"])

        self.running = False
        if self.source:
            self.source.close()
            self.source = None
        self.phase = Phase.IDLE
        self.gui.set_status_threadsafe(
            f"Done — {self.caught} fish" if self.caught else "Stopped")


# ---------------------------------------------------------------- GUI

from collections import deque

try:
    from PIL import Image, ImageTk
except ImportError:  # the GUI shows a hint instead of the preview
    Image = ImageTk = None

# palette
BG = "#14171c"
PANEL = "#1c2028"
PANEL2 = "#262b35"
HOVER = "#323947"
BORDER = "#2d3340"
FG = "#e6e9ef"
MUTED = "#8b93a1"
ACCENT = "#4ea1ff"
GREEN = "#3ddc84"
RED = "#ff5d5d"
AMBER = "#ffb74d"

# phase -> (pill text, pill background, pill foreground)
PHASE_STYLE = {
    "IDLE":                ("IDLE",                  PANEL2,    MUTED),
    "STARTING":            ("STARTING…",             "#5a4310", AMBER),
    "LOOKING FOR GEAR":    ("SEARCHING FOR GEAR",    "#5a4310", AMBER),
    "LOOKING FOR BOBBER":  ("SEARCHING FOR BOBBER",  "#10335a", ACCENT),
    "WATCHING":            ("WATCHING FEATHER",      "#0f4a2a", GREEN),
}

# parameter tabs: (tab title, [param keys])
TABS = [
    ("Detection", ["gear_lock", "lock_score", "min_red", "bite_px", "bite_frames", "settle"]),
    ("Search area", ["h_min", "h_max", "v_min", "v_max"]),
    ("Timing", ["cast_anim", "loot_wait", "seek_seconds", "watch_seconds",
                "interval", "start_delay", "target"]),
    ("Humanize", ["jitter", "react_min", "react_max"]),
]
PARAM_BY_KEY = {p[0]: p for p in PARAMS}

# Tk keysym -> key name used by press_key (letters, digits and F-keys are handled separately)
KEYSYM_NAMES = {"less": "<", "greater": ">", "space": "space", "Return": "enter", "Tab": "tab",
                "minus": "-", "equal": "=", "comma": ",", "period": ".", "slash": "/",
                "semicolon": ";", "grave": "`", "apostrophe": "'", "bracketleft": "[",
                "bracketright": "]", "backslash": "\\"}
MODIFIER_KEYSYMS = {"Shift_L", "Shift_R", "Control_L", "Control_R", "Alt_L", "Alt_R", "Meta_L",
                    "Meta_R", "Super_L", "Super_R", "Caps_Lock", "ISO_Level3_Shift", "Num_Lock"}

TRACE_W, TRACE_H = PREVIEW_W + ZOOM_W + 12, 120


def fmt_time(seconds):
    s = int(seconds)
    return f"{s // 3600:d}:{(s % 3600) // 60:02d}:{s % 60:02d}"


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("WoW Fishing Bot")
        self.geometry("1130x780")
        self.minsize(1100, 760)
        self.configure(bg=BG)
        self._init_style()

        # tkinter vars live on the GUI thread; the bot reads the plain dict
        self.vars = {}
        self.params = dict(DEFAULTS)
        for key, _, kind, *_rest in PARAMS:
            var = tk.DoubleVar(value=DEFAULTS[key]) if kind is float else tk.IntVar(value=DEFAULTS[key])
            var.trace_add("write", lambda *_a, k=key: self._sync(k))
            self.vars[key] = var
        key_var = tk.StringVar(value=DEFAULT_KEY)   # cast / loot key
        key_var.trace_add("write", lambda *_a: self._sync("cast_key"))
        self.vars["cast_key"] = key_var

        self.status_var = tk.StringVar(value="Ready — press Start, then click into WoW")
        self.stat_caught = tk.StringVar(value="0")
        self.stat_casts = tk.StringVar(value="0")
        self.stat_rate = tk.StringVar(value="—")
        self.stat_time = tk.StringVar(value="0:00:00")
        self.read = {k: tk.StringVar(value="—") for k in ("y", "dy", "low")}
        self.gauge_txt = {k: tk.StringVar(value="—") for k in ("gear", "bobber")}

        self.preview_photo = None
        self.zoom_photo = None
        self.thumbs = {}
        self.history = deque(maxlen=160)     # feather Y shift samples for the trace graph
        self._latest = None
        self._lock = threading.Lock()
        self.last_phase = "IDLE"
        self.prev_caught = 0
        self.flash_until = 0.0
        self.last_elapsed = 0.0

        self.bot = FishingBot(self)
        self._load_config()
        self._build()
        self.protocol("WM_DELETE_WINDOW", self._on_close)
        self.after(60, self._poll)

    # ----- style

    def _init_style(self):
        s = ttk.Style(self)
        s.theme_use("clam")
        s.configure(".", background=BG, foreground=FG, fieldbackground=PANEL,
                    bordercolor=BORDER, lightcolor=PANEL, darkcolor=PANEL,
                    troughcolor=PANEL, focuscolor=BG)
        s.configure("TFrame", background=BG)
        s.configure("TLabel", background=BG, foreground=FG)
        s.configure("Muted.TLabel", foreground=MUTED)
        s.configure("TLabelframe", background=BG, bordercolor=BORDER)
        s.configure("TLabelframe.Label", background=BG, foreground=MUTED)
        s.configure("TNotebook", background=BG, borderwidth=0)
        s.configure("TNotebook.Tab", background=PANEL, foreground=MUTED, padding=(14, 6), borderwidth=0)
        s.map("TNotebook.Tab", background=[("selected", BG)], foreground=[("selected", FG)])
        s.configure("TSpinbox", arrowcolor=FG, insertcolor=FG, padding=3)
        s.configure("TButton", background=PANEL2, foreground=FG, padding=(14, 7), borderwidth=0)
        s.map("TButton", background=[("active", HOVER)])
        s.configure("Start.TButton", background="#1f8f55", foreground="white", font=("", 10, "bold"))
        s.map("Start.TButton", background=[("active", "#27ad66")])
        s.configure("Stop.TButton", background="#b23b3b", foreground="white", font=("", 10, "bold"))
        s.map("Stop.TButton", background=[("active", "#d44a4a")])
        for name, color in (("ok", GREEN), ("low", AMBER)):
            s.configure(f"{name}.Horizontal.TProgressbar", background=color, troughcolor=PANEL,
                        bordercolor=PANEL, lightcolor=color, darkcolor=color)

    # ----- params / config

    def _sync(self, key):
        try:
            self.params[key] = self.vars[key].get()
        except (tk.TclError, ValueError):
            pass  # field temporarily empty / invalid while typing

    def _load_config(self):
        if not CONFIG.exists():
            return
        try:
            data = json.loads(CONFIG.read_text())
        except Exception:
            return
        for key, var in self.vars.items():
            if key in data:
                try:
                    var.set(data[key])
                except Exception:
                    pass

    def save_config(self):
        try:
            data = {k: v.get() for k, v in self.vars.items()}
            CONFIG.write_text(json.dumps(data, indent=2))
        except Exception:
            pass

    # ----- thread-safe hooks used by the bot

    def push(self, info, preview_bgr, zoom_bgr):
        with self._lock:
            if info["phase"] == "WATCHING":
                if not info["settling"]:
                    self.history.append(info["dy"])  # None = feather vanished
            else:
                self.history.clear()
            self._latest = (info, preview_bgr, zoom_bgr)

    def set_status_threadsafe(self, text):
        self.after(0, lambda: self.status_var.set(text))

    # ----- layout

    def _build(self):
        pad = {"padx": 10, "pady": 6}

        # header: phase pill + session stats
        header = ttk.Frame(self)
        header.pack(fill="x", **pad)
        self.pill = tk.Label(header, text="IDLE", font=("", 13, "bold"), padx=18, pady=8,
                             bg=PANEL2, fg=MUTED)
        self.pill.pack(side="left")
        stats = ttk.Frame(header)
        stats.pack(side="right")
        for col, (title, var) in enumerate([("Caught", self.stat_caught), ("Casts", self.stat_casts),
                                            ("Fish / hour", self.stat_rate), ("Session", self.stat_time)]):
            f = ttk.Frame(stats)
            f.grid(row=0, column=col, padx=14)
            ttk.Label(f, text=title.upper(), style="Muted.TLabel", font=("", 8)).pack(anchor="e")
            ttk.Label(f, textvariable=var, font=("", 20, "bold")).pack(anchor="e")

        body = ttk.Frame(self)
        body.pack(fill="both", expand=True, padx=10)

        # left column: views, gauges, trace
        left = ttk.Frame(body)
        left.pack(side="left", fill="y")

        views = ttk.Frame(left)
        views.pack(fill="x")
        pv = ttk.LabelFrame(views, text="Live view")
        pv.pack(side="left")
        self.preview_canvas = tk.Canvas(pv, width=PREVIEW_W, height=PREVIEW_H, bg="black",
                                        highlightthickness=0)
        self.preview_canvas.pack(padx=4, pady=4)
        zv = ttk.LabelFrame(views, text="Locked bobber")
        zv.pack(side="left", padx=(12, 0))
        self.zoom_canvas = tk.Canvas(zv, width=ZOOM_W, height=ZOOM_H, bg="black", highlightthickness=0)
        self.zoom_canvas.pack(padx=4, pady=4)
        self._placeholder(self.preview_canvas, PREVIEW_W, PREVIEW_H, "Press Start")
        self._placeholder(self.zoom_canvas, ZOOM_W, ZOOM_H, "No bobber locked")

        strip = ttk.Frame(left)
        strip.pack(fill="x", pady=(8, 0))
        self.gauges = {}
        for i, (key, title) in enumerate([("gear", "Gear match"), ("bobber", "Bobber match")]):
            f = ttk.Frame(strip)
            f.grid(row=0, column=i, padx=(0, 18), sticky="w")
            row = ttk.Frame(f)
            row.pack(fill="x")
            ttk.Label(row, text=title, style="Muted.TLabel").pack(side="left")
            ttk.Label(row, textvariable=self.gauge_txt[key], font=("", 9, "bold")).pack(side="right")
            bar = ttk.Progressbar(f, length=170, maximum=100, style="low.Horizontal.TProgressbar")
            bar.pack(pady=(2, 0))
            self.gauges[key] = bar
        for i, (key, title) in enumerate([("y", "Feather Y"), ("dy", "Y shift"), ("low", "Bite frames")]):
            f = ttk.Frame(strip)
            f.grid(row=0, column=2 + i, padx=12, sticky="w")
            ttk.Label(f, text=title, style="Muted.TLabel").pack(anchor="w")
            ttk.Label(f, textvariable=self.read[key], font=("", 12, "bold")).pack(anchor="w")

        tv = ttk.LabelFrame(left, text="Feather Y shift over time (bite zone = outside the dotted lines)")
        tv.pack(fill="x", pady=(8, 0))
        self.trace = tk.Canvas(tv, width=TRACE_W, height=TRACE_H, bg=PANEL, highlightthickness=0)
        self.trace.pack(padx=4, pady=4)
        self._draw_trace()

        # right column: controls
        right = ttk.Frame(body)
        right.pack(side="left", fill="both", expand=True, padx=(14, 0))

        btns = ttk.Frame(right)
        btns.pack(fill="x", pady=(0, 8))
        ttk.Button(btns, text="▶  Start", style="Start.TButton", command=self.bot.start).pack(
            side="left", expand=True, fill="x", padx=(0, 4))
        ttk.Button(btns, text="■  Stop", style="Stop.TButton", command=self.bot.stop).pack(
            side="left", expand=True, fill="x", padx=(4, 0))

        kf = ttk.LabelFrame(right, text="Cast / loot key")
        kf.pack(fill="x", pady=(0, 8))
        tk.Label(kf, textvariable=self.vars["cast_key"], font=("", 16, "bold"), bg=PANEL, fg=FG,
                 width=9, pady=4).pack(side="left", padx=10, pady=8)
        ttk.Button(kf, text="Change key", command=self.change_key).pack(side="left", padx=(0, 10))

        tmpl = ttk.LabelFrame(right, text="Templates")
        tmpl.pack(fill="x", pady=(0, 8))
        self.thumb_labels = {}
        for col, (path, name, title) in enumerate([(GEAR_TMPL, "gear", "Grab gear"),
                                                   (BOBBER_TMPL, "bobber", "Grab bobber")]):
            f = ttk.Frame(tmpl)
            f.grid(row=0, column=col, padx=10, pady=8)
            lbl = tk.Label(f, bg=PANEL, fg=RED, width=10, height=4, text="missing", compound="center")
            lbl.pack()
            self.thumb_labels[name] = (lbl, path)
            ttk.Button(f, text=title, command=lambda p=path, n=name: self.grab_template(p, n)).pack(pady=(6, 0))
        tmpl.columnconfigure((0, 1), weight=1)
        self.refresh_thumbs()

        nb = ttk.Notebook(right)
        nb.pack(fill="both", expand=True)
        for title, keys in TABS:
            page = ttk.Frame(nb, padding=12)
            nb.add(page, text=title)
            page.columnconfigure(0, weight=1)
            for i, key in enumerate(keys):
                _k, label, kind, lo, hi, step, _d, help_ = PARAM_BY_KEY[key]
                ttk.Label(page, text=label).grid(row=2 * i, column=0, sticky="w", pady=(6, 0))
                kw = dict(from_=lo, to=hi, textvariable=self.vars[key], width=8, increment=step)
                if kind is float:
                    kw["format"] = "%.2f"
                ttk.Spinbox(page, **kw).grid(row=2 * i, column=1, sticky="e", pady=(6, 0))
                ttk.Label(page, text=help_, style="Muted.TLabel", font=("", 8),
                          wraplength=300, justify="left").grid(row=2 * i + 1, column=0, columnspan=2, sticky="w")

        ttk.Label(self, textvariable=self.status_var, style="Muted.TLabel").pack(
            side="bottom", anchor="w", padx=12, pady=(0, 8))

    # ----- drawing helpers

    def _placeholder(self, canvas, w, h, text):
        canvas.delete("all")
        canvas.create_text(w // 2, h // 2, text=text, fill=MUTED, font=("", 11))

    def _show(self, canvas, bgr, attr, w, h):
        if Image is None:
            self._placeholder(canvas, w, h, "Install Pillow to see the preview")
            return
        photo = ImageTk.PhotoImage(Image.fromarray(cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)))
        setattr(self, attr, photo)  # keep a reference
        canvas.delete("all")
        canvas.create_image(w // 2, h // 2, image=photo)

    def refresh_thumbs(self):
        for name, (lbl, path) in self.thumb_labels.items():
            if Image is not None and path.exists():
                try:
                    img = Image.open(path).convert("RGB")
                    img.thumbnail((72, 72))
                    photo = ImageTk.PhotoImage(img)
                    self.thumbs[name] = photo
                    lbl.configure(image=photo, text="", width=72, height=72)
                    continue
                except Exception:
                    pass
            lbl.configure(image="", text="missing", width=10, height=4)

    def _draw_trace(self):
        c = self.trace
        c.delete("all")
        w, h = TRACE_W, TRACE_H
        pts = list(self.history)
        bite = max(1, self.params.get("bite_px", 10))
        mid = h / 2
        seen = max((abs(v) for v in pts if v is not None), default=0)
        span = max(bite * 2.5, seen * 1.15)
        k = (h / 2 - 8) / span

        c.create_rectangle(0, mid - bite * k, w, mid + bite * k, fill="#232830", outline="")
        c.create_line(0, mid, w, mid, fill=MUTED, dash=(3, 4))
        for s in (-1, 1):
            c.create_line(0, mid + s * bite * k, w, mid + s * bite * k, fill=AMBER, dash=(2, 4))
        c.create_text(w - 6, mid - bite * k - 7, text=f"-{bite}px", fill=AMBER, anchor="e", font=("", 7))
        c.create_text(w - 6, mid + bite * k + 7, text=f"+{bite}px", fill=AMBER, anchor="e", font=("", 7))

        if not pts:
            c.create_text(w // 2, mid, text="waiting for a locked bobber…", fill=MUTED, font=("", 10))
            return

        n = self.history.maxlen
        dx = w / (n - 1)
        seg = []

        def flush():
            if len(seg) >= 4:
                c.create_line(*seg, fill=ACCENT, width=2)
            seg.clear()

        for i, v in enumerate(pts):
            x = w - (len(pts) - 1 - i) * dx
            if v is None:
                flush()
                c.create_line(x, h - 4, x, h - 18, fill=RED, width=2)  # feather vanished
            else:
                seg += [x, mid + max(-span, min(span, v)) * k]
        flush()

        last = pts[-1]
        if last is not None:
            x = w
            y = mid + max(-span, min(span, last)) * k
            col = RED if abs(last) >= bite else GREEN
            c.create_oval(x - 4, y - 4, x + 2, y + 2, fill=col, outline="")

    # ----- periodic refresh

    def _poll(self):
        now = time.monotonic()
        with self._lock:
            latest, self._latest = self._latest, None

        P = self.params
        if latest:
            info, preview, zoom = latest
            self.last_phase = info["phase"]

            for key, thr_key in (("gear", "gear_lock"), ("bobber", "lock_score")):
                score = max(0.0, min(1.0, info[key]))
                self.gauge_txt[key].set(f"{score:.2f} / {P[thr_key]:.2f}")
                bar = self.gauges[key]
                bar["value"] = score * 100
                bar.configure(style=("ok" if score >= P[thr_key] else "low") + ".Horizontal.TProgressbar")

            self.read["y"].set(f"{info['y']:.1f}" if info["y"] is not None else "—")
            self.read["dy"].set(f"{info['dy']:+.1f}" if info["dy"] is not None else "—")
            self.read["low"].set(f"{info['low']} / {P['bite_frames']}")
            self.stat_caught.set(str(info["caught"]))
            self.stat_casts.set(str(info["casts"]))

            if info["caught"] > self.prev_caught:
                self.flash_until = now + 1.5
            self.prev_caught = info["caught"]

            try:
                self._show(self.preview_canvas, preview, "preview_photo", PREVIEW_W, PREVIEW_H)
                if zoom is not None:
                    self._show(self.zoom_canvas, zoom, "zoom_photo", ZOOM_W, ZOOM_H)
                else:
                    self._placeholder(self.zoom_canvas, ZOOM_W, ZOOM_H, "No bobber locked")
            except Exception:
                pass
            self._draw_trace()

        # session timer + rate
        if self.bot.running:
            self.last_elapsed = now - self.bot.session_t0
        self.stat_time.set(fmt_time(self.last_elapsed))
        caught = self.bot.caught
        self.stat_rate.set(f"{caught / (self.last_elapsed / 3600):.0f}"
                           if caught and self.last_elapsed > 30 else "—")

        # phase pill
        if now < self.flash_until:
            text, bg, fg = "CAUGHT!", GREEN, "#06210f"
        elif not self.bot.running:
            text, bg, fg = PHASE_STYLE["IDLE"]
        else:
            text, bg, fg = PHASE_STYLE.get(self.last_phase, PHASE_STYLE["STARTING"])
            if self.last_phase == "IDLE":
                text, bg, fg = PHASE_STYLE["STARTING"]
        self.pill.configure(text=text, bg=bg, fg=fg)

        self.after(60, self._poll)

    # ----- key picker

    @staticmethod
    def _key_from_event(e):
        ks = e.keysym
        name = KEYSYM_NAMES.get(ks)
        if name is None:
            if len(ks) == 1:
                name = ks.lower()
            elif re.fullmatch(r"F\d{1,2}", ks):
                name = ks.lower()
        if name and key_supported(name):
            return name
        if not USE_PYAUTOGUI and e.keycode > 8:   # Linux/X11 keycode = evdev code + 8
            return f"code:{e.keycode - 8}"
        return None

    def change_key(self):
        if self.bot.running:
            messagebox.showinfo("Busy", "Stop the bot first to change the key.")
            return
        win = tk.Toplevel(self)
        win.title("Change key")
        win.configure(bg=BG)
        win.resizable(False, False)
        ttk.Label(win, text="Press the key that casts / loots in WoW", padding=(30, 24, 30, 6),
                  font=("", 11)).pack()
        hint = ttk.Label(win, text="Esc to cancel", style="Muted.TLabel", padding=(30, 0, 30, 20))
        hint.pack()

        def on_key(e):
            if e.keysym == "Escape":
                win.destroy()
                return
            if e.keysym in MODIFIER_KEYSYMS:
                return
            key = self._key_from_event(e)
            if key is None:
                hint.configure(text="That key can't be used here — try another (Esc to cancel)")
                return
            self.vars["cast_key"].set(key)
            self.save_config()
            win.destroy()

        win.bind("<KeyPress>", on_key)
        win.transient(self)
        win.grab_set()
        win.focus_force()

    # ----- template grabbing

    def grab_template(self, path, name):
        if self.bot.running:
            messagebox.showinfo("Busy", "Stop the bot first to grab a new template.")
            return
        try:
            src = open_source()
        except Exception as e:
            messagebox.showerror("Capture error", str(e))
            return
        frame = None
        for _ in range(60):
            frame = src.grab()
            if frame is not None:
                break
            time.sleep(0.05)
        src.close()
        if frame is None:
            messagebox.showerror("Error", "Could not grab a frame")
            return
        self._select_region(frame, path, name)

    def _select_region(self, bgr, path, name):
        if Image is None:
            messagebox.showerror("Pillow missing", "Install Pillow (pip install pillow) to grab templates.")
            return

        win = tk.Toplevel(self)
        win.title(f"Drag a box around the {name} — Enter to save, Esc to cancel")
        win.configure(bg=BG)

        h, w = bgr.shape[:2]
        scale = min(1.0, 960 / w, 640 / h)
        small = cv2.resize(bgr, (int(w * scale), int(h * scale))) if scale < 1 else bgr
        photo = ImageTk.PhotoImage(Image.fromarray(cv2.cvtColor(small, cv2.COLOR_BGR2RGB)))

        canvas = tk.Canvas(win, width=small.shape[1], height=small.shape[0], cursor="cross",
                           highlightthickness=0)
        canvas.pack()
        canvas.create_image(0, 0, anchor="nw", image=photo)
        canvas.image = photo

        state = {"rect": None, "start": (0, 0), "end": (0, 0)}

        def on_press(e):
            state["start"] = state["end"] = (e.x, e.y)
            if state["rect"]:
                canvas.delete(state["rect"])
            state["rect"] = canvas.create_rectangle(e.x, e.y, e.x, e.y, outline="lime", width=2)

        def on_drag(e):
            state["end"] = (e.x, e.y)
            canvas.coords(state["rect"], *state["start"], e.x, e.y)

        def on_confirm(_=None):
            (sx, sy), (ex, ey) = state["start"], state["end"]
            x1, x2 = sorted((sx, ex))
            y1, y2 = sorted((sy, ey))
            if x2 - x1 < 10 or y2 - y1 < 10:
                messagebox.showwarning("Too small", "Select a larger region", parent=win)
                return
            crop = bgr[int(y1 / scale):int(y2 / scale), int(x1 / scale):int(x2 / scale)]
            if crop.size == 0:
                return
            cv2.imwrite(str(path), crop)
            self.refresh_thumbs()
            messagebox.showinfo("Saved", f"{name} template saved ({crop.shape[1]}x{crop.shape[0]})", parent=win)
            win.destroy()

        canvas.bind("<ButtonPress-1>", on_press)
        canvas.bind("<B1-Motion>", on_drag)
        win.bind("<Return>", on_confirm)
        win.bind("<Escape>", lambda _e: win.destroy())
        ttk.Button(win, text="Save region (Enter)", command=on_confirm).pack(pady=6)
        win.transient(self)
        win.grab_set()

    def _on_close(self):
        self.save_config()
        self.bot.stop()
        self.destroy()


if __name__ == "__main__":
    App().mainloop()
