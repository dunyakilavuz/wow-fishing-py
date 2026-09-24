#!/usr/bin/env python3
"""WoW fishing loop: cast → lock bobber → score drop = bite → recast."""
from __future__ import annotations

import subprocess
import sys
import time
from enum import Enum, auto
from pathlib import Path

import cv2
import numpy as np

IS_WIN = sys.platform == "win32"

ROOT = Path(__file__).resolve().parent
TEMPLATE = ROOT / "bobber.png"

START_DELAY = 3.0
SEEK_SECONDS = 8.0
WATCH_SECONDS = 25.0
LOCK_SCORE = 0.50
DROP_DELTA = 0.22
BITE_FRAMES = 2
TARGET_CATCHES = 100
INTERVAL = 0.12
WOW_NAME = "World of Warcraft"
LOOT_WAIT = 1.5   # after reel, bags/auto-loot
CAST_ANIM = 1.0   # after <, bobber not in the water yet

if IS_WIN:
    import pyautogui
    pyautogui.FAILSAFE = False
    pyautogui.PAUSE = 0.05


class Phase(Enum):
    SEEK = auto()
    WATCH = auto()


def press_cast(*, after=CAST_ANIM):
    if IS_WIN:
        pyautogui.press("<")
    else:
        subprocess.run(["ydotool", "key", "86:1", "86:0"], check=False)
    print("cast  <", flush=True)
    if after:
        time.sleep(after)


def match_template(bgr, tmpl):
    if tmpl is None:
        return None
    if bgr.shape[0] < tmpl.shape[0] or bgr.shape[1] < tmpl.shape[1]:
        return None
    gray = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY)
    tgray = cv2.cvtColor(tmpl, cv2.COLOR_BGR2GRAY)
    res = cv2.matchTemplate(gray, tgray, cv2.TM_CCOEFF_NORMED)
    _, score, _, loc = cv2.minMaxLoc(res)
    h, w = tgray.shape[:2]
    x, y = loc
    return float(score), (x + w // 2, y + h // 2), (x, y, w, h)


class PipewireSource:
    def __init__(self):
        from pipewire_capture import PortalCapture, CaptureStream, is_available

        if not is_available():
            raise RuntimeError("no capture source")
        print("Pick the World of Warcraft window.", flush=True)
        self.session = PortalCapture().select_window()
        if self.session is None:
            raise RuntimeError("cancelled")
        self.stream = CaptureStream(
            self.session.fd, self.session.node_id,
            self.session.width, self.session.height,
        )
        self.stream.start()
        print(f"streaming {self.session.width}x{self.session.height}", flush=True)

    def grab(self):
        frame = self.stream.get_frame()
        if frame is None:
            return None
        return cv2.cvtColor(frame, cv2.COLOR_BGRA2BGR)

    def close(self):
        self.stream.stop()
        self.session.close()


class WindowsSource:
    def __init__(self):
        import mss
        self._mss = mss.mss()
        self._hwnd = self._find_wow()
        if not self._hwnd:
            raise RuntimeError("World of Warcraft window not found")
        print(f"capturing hwnd={self._hwnd}", flush=True)

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
        w = rect.right - rect.left
        h = rect.bottom - rect.top
        return {"left": pt.x, "top": pt.y, "width": w, "height": h}

    def grab(self):
        box = self._client_box()
        if box["width"] <= 0 or box["height"] <= 0:
            return None
        shot = np.array(self._mss.grab(box))
        return cv2.cvtColor(shot, cv2.COLOR_BGRA2BGR)

    def close(self):
        self._mss.close()


def open_source():
    return WindowsSource() if IS_WIN else PipewireSource()


def run(source, tmpl):
    print("Fishing bot will start in 3 seconds, go to Wow window.", flush=True)
    time.sleep(START_DELAY)



    caught = 0
    phase = Phase.SEEK
    press_cast()
    t0 = time.monotonic()
    lock_score = None
    low_frames = 0

    while caught < TARGET_CATCHES:
        bgr = source.grab()
        if bgr is None:
            time.sleep(0.03)
            continue

        hit = match_template(bgr, tmpl)
        score = hit[0] if hit else 0.0
        now = time.monotonic()
        elapsed = now - t0

        print(
            f"{phase.name} score={score:.3f} threshold={LOCK_SCORE:.3f} "
            f"lock={lock_score if lock_score is None else f'{lock_score:.3f}'} "
            f"t={elapsed:.1f}s",
            flush=True,
        )

        if phase == Phase.SEEK:
            if score >= LOCK_SCORE:
                lock_score = score
                low_frames = 0
                phase = Phase.WATCH
                t0 = now
                print(f"bobber lock score={score:.3f} pos={hit[1]}", flush=True)
            elif elapsed >= SEEK_SECONDS:
                print("no bobber — recast", flush=True)
                press_cast()
                t0 = time.monotonic()
                lock_score = None
                low_frames = 0

        elif phase == Phase.WATCH:
            dropped = lock_score is not None and (lock_score - score) >= DROP_DELTA
            if dropped:
                low_frames += 1
            else:
                low_frames = 0
                if score > (lock_score or 0):
                    lock_score = score

            if low_frames >= BITE_FRAMES:
                print(f"bite  lock={lock_score:.3f} now={score:.3f} frames={low_frames}", flush=True)
                press_cast(after=LOOT_WAIT)
                caught += 1
                print(f"catched around ~= {caught} fish", flush=True)
                press_cast(after=CAST_ANIM)
                phase = Phase.SEEK
                t0 = time.monotonic()
                lock_score = None
                low_frames = 0
            elif elapsed >= WATCH_SECONDS:
                print("no bite in 25s — recast", flush=True)
                press_cast()
                phase = Phase.SEEK
                t0 = time.monotonic()
                lock_score = None
                low_frames = 0

        time.sleep(INTERVAL)

    print(f"done — {caught} fish", flush=True)


def main():
    tmpl = cv2.imread(str(TEMPLATE), cv2.IMREAD_COLOR) if TEMPLATE.exists() else None
    if tmpl is None:
        print("bobber.png missing — template score will stay 0, cannot lock", flush=True)
        sys.exit(1)

    source = open_source()
    try:
        run(source, tmpl)
    finally:
        source.close()


if __name__ == "__main__":
    main()