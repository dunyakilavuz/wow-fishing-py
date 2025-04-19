import random
import time
import pyautogui
import cv2
import numpy as np
from PIL import Image

def is_red_feather(r, g, b, color_multiplier=0.5, closeness_multiplier=2.0):
    def is_bigger(a, b):
        return a * color_multiplier > b

    def are_close(a, b):
        maximum = max(a, b)
        minimum = min(a, b)
        return int(minimum) * closeness_multiplier > int(maximum) - 20

    return is_bigger(r, g) and is_bigger(r, b) and are_close(g, b)

def GetScreenSize():
    width, height = pyautogui.size()
    return width, height

def GetSearchRegion(left = 0.3, top = 0.3, right = 0.7, bottom = 0.7): # Adjusted to 40% of the screen
    screenWidth, screenHeight = GetScreenSize()
    x = int(screenWidth * left)
    y = int(screenHeight * top)
    width = int(screenWidth * (right - left))
    height = int(screenHeight * (bottom - top))
    return (x, y, width, height)

def GetScreenShotNP(region):
    img = pyautogui.screenshot(region=region)
    return cv2.cvtColor(np.array(img), cv2.COLOR_RGB2BGR)


def CastFishing():
    pyautogui.press('1') # Hotkey for casting
    time.sleep(2.5)

def FindBobber(debug=False):
    region = GetSearchRegion()
    img = GetScreenShotNP(region)
    h, w = img.shape[:2]
    mask = np.zeros((h, w), dtype=np.uint8)

    for y in range(h):
        for x in range(w):
            b, g, r = img[y, x]
            if is_red_feather(r, g, b):
                mask[y, x] = 255

    # Find the largest red cluster
    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

    if debug:
        cv2.imwrite("log/screenshot.png", mask)

    if contours:
        largest = max(contours, key=cv2.contourArea)
        x, y, w, h = cv2.boundingRect(largest)
        cx = x + w // 2 + region[0]
        cy = y + h // 2 + region[1]
        print(f"Found red cluster at ({cx}, {cy})")
        return (cx, cy)
    else:
        print("No red feather detected.")
        return None

def WatchBobber(bobberPos, timeout=30, boxSize=50, sensitivity=2.5):
    x, y = bobberPos
    half = boxSize // 2
    region = (x - half, y - half, boxSize, boxSize)
    history = []
    start_time = time.time()
    average, std_dev = None, None
    spike_frames = 0
    spike_required = 2

    while time.time() - start_time < timeout:
        elapsed = time.time() - start_time
        img = GetScreenShotNP(region)
        h, w = img.shape[:2]

        feather_y_positions = []
        for j in range(h):
            for i in range(w):
                b, g, r = img[j, i]
                if is_red_feather(r, g, b):
                    feather_y_positions.append(j)

        if feather_y_positions:
            center_y = sum(feather_y_positions) / len(feather_y_positions)
            history.append(center_y)

        if len(history) >= 10:
            average = sum(history) / len(history)
            std_dev = np.std(history)

            delta = abs(history[-1] - average)
            print(f"ΔY={delta:.2f}, std={std_dev:.2f}, avg={average:.2f}, last={history[-1]:.2f}")

            if len(history) > 30:
                history.pop(0)

            if delta >= std_dev * sensitivity:
                spike_frames += 1
                if spike_frames >= spike_required:
                    print(f"[Y-Dev] Splash detected! ΔY: {delta:.2f}")
                    return True
            else:
                spike_frames = 0
        else:
            print("[Y-Dev] No red feather detected.")

        time.sleep(0.1)

    print("[Y-Dev] No splash detected.")
    return False


def Loot(bobberPos):
    offset_x = random.randint(-2, 2)
    offset_y = random.randint(-2, 2)
    x = bobberPos[0] + offset_x
    y = bobberPos[1] + offset_y

    pyautogui.moveTo(x, y, duration=0.2)
    pyautogui.rightClick()
    time.sleep(1.5)