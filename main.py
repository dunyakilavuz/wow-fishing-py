import time
from util import CastFishing, CastLure, FindBobber, Loot, WatchBobber
import argparse

parser = argparse.ArgumentParser(description="WoW Classic Fishing Bot 🎣")
parser.add_argument("--lure", type=float, default=0.0,
    help="Apply lure every X minutes (e.g., --lure 10). 0 = disabled")
args = parser.parse_args()
lure_interval_seconds = args.lure * 60 + 15 # 15 seconds buffer
lure_enabled = args.lure > 0

args = parser.parse_args()

def RunFishingLoop():
    print("🎣 Fishing bot stars in 3 seconds. Press Ctrl+C to stop.")
    time.sleep(3)  # wait for 3 seconds before starting
    last_lure_time = 0
    fish_caught = 0

    try:
        while True:
            current_time = time.time()

            if lure_enabled and (current_time - last_lure_time >= lure_interval_seconds):
                print("Status: Luring")
                CastLure()
                last_lure_time = current_time

            print("Status: Casting")
            CastFishing()
            print("Status: Finding Bobber")
            pos = FindBobber()
            if not pos:
                print("No bobber found. Retrying...")
                continue
            print("Status: Watching")
            if WatchBobber(pos):
                print("Status: Looting")
                Loot(pos)
                fish_caught += 1
            else:
                print("No splash detected. Restarting...")
            time.sleep(1)  # small delay between loops
    except KeyboardInterrupt:
        print(f"🎣 Total fish caught: Around~ {fish_caught}")
        print("\n🛑 Bot stopped by user.")


if __name__ == "__main__":
    RunFishingLoop()