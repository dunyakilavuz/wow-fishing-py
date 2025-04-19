import time
from util import CastFishing, FindBobber, Loot, WatchBobber

def RunFishingLoop():
    print("🎣 Fishing bot stars in 3 seconds. Press Ctrl+C to stop.")
    time.sleep(3)  # wait for 3 seconds before starting
    try:
        while True:
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
            else:
                print("No splash detected. Restarting...")
            time.sleep(1)  # small delay between loops
    except KeyboardInterrupt:
        print("\n🛑 Bot stopped by user.")


if __name__ == "__main__":
    RunFishingLoop()