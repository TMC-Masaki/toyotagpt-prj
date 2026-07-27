#!/usr/bin/env python3
import time
from app.modules.can.receiver import CANReceiver

def main():
    can_rx = CANReceiver(channel="can0")
    can_rx.start()
    print("[INFO] CANReceiver running... Press Ctrl+C to stop")

    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("\n[INFO] KeyboardInterrupt received, stopping...")
        can_rx.stop()
        print("[INFO] CANReceiver stopped")

if __name__ == "__main__":
    main()
