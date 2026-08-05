"""
main.py — Kimo Robot Pet entry point.

Two modes (TAB to toggle):
  VOICE  — microphone + Groq + keyword brain controls the robot
  MANUAL — arrow keys + D/Space + r/g/b/y/o color follow (terminal keyboard)
""" 

import sys
import time
import threading
import readchar
from voice import listen_and_transcribe, select_mic, stop_droidcam
from brain import get_command
from motor import MotorController
from vision import ColorFollower

_mode = "VOICE"   # "VOICE" or "MANUAL"

_COLOR_KEYS = {'r': 'red'}


def _print_mode_banner():
    print(f"\n{'='*42}")
    print(f"  MODE: {_mode}")
    if _mode == "MANUAL":
        print("  ↑↓←→ = move  |  Space = stop  |  D = dance")
        print("  r = follow red  |  ESC = stop follow  |  TAB = voice mode")
    else:
        print("  Speak a command into the mic")
        print("  TAB = switch to manual mode")
    print(f"{'='*42}\n")


def _keyboard_loop(motor, follower):
    global _mode

    while True:
        try:
            key = readchar.readkey()
        except (Exception, KeyboardInterrupt):
            break

        # TAB — toggle mode
        if key == readchar.key.TAB:
            _mode = "MANUAL" if _mode == "VOICE" else "VOICE"
            follower.stop()
            motor.send_command("STOP")
            _print_mode_banner()
            continue

        if _mode != "MANUAL":
            continue

        # Arrow keys — move
        if key == readchar.key.UP:
            follower.stop()
            motor.send_command("FORWARD")
            print("[Keys] FORWARD")
        elif key == readchar.key.DOWN:
            follower.stop()
            motor.send_command("BACKWARD")
            print("[Keys] BACKWARD")
        elif key == readchar.key.LEFT:
            follower.stop()
            motor.send_command("LEFT")
            print("[Keys] LEFT")
        elif key == readchar.key.RIGHT:
            follower.stop()
            motor.send_command("RIGHT")
            print("[Keys] RIGHT")

        # Space — stop
        elif key == readchar.key.SPACE:
            follower.stop()
            motor.send_command("STOP")
            print("[Keys] STOP")

        # ESC — stop color follow
        elif key == readchar.key.ESC:
            follower.stop()
            print("[Keys] Follow stopped")

        # D — dance
        elif key.lower() == 'd':
            follower.stop()
            motor.send_command("DANCE")
            print("[Keys] DANCE")

        # Color follow keys
        elif key.lower() in _COLOR_KEYS:
            color = _COLOR_KEYS[key.lower()]
            follower.start(color)
            print(f"[Keys] Follow: {color}")


def main() -> None:
    print("=== Kimo Robot Pet ===")
    print("Starting up...\n")
    select_mic()

    motor    = MotorController()
    follower = ColorFollower(motor)

    # Start keyboard listener thread
    kb_thread = threading.Thread(target=_keyboard_loop, args=(motor, follower), daemon=True)
    kb_thread.start()

    _print_mode_banner()

    while True:
        try:
            if _mode == "MANUAL":
                time.sleep(0.1)
                continue

            text = listen_and_transcribe()

            if _mode == "MANUAL":
                continue

            if not text:
                continue

            print(f"[Kimo] Heard:   \"{text}\"")

            command = get_command(text)
            print(f"[Kimo] Command: {command}\n")

            if command == "NOOP":
                pass  # no keyword matched — do nothing, keep follower running

            elif command.startswith("FOLLOW:"):
                color = command.split(":")[1]
                follower.start(color)

            elif command == "STOP":
                if follower.is_active():
                    follower.stop()
                motor.send_command("STOP")

            else:
                if not follower.is_active():
                    motor.send_command(command)

        except KeyboardInterrupt:
            print("\n[Kimo] Shutting down...")
            follower.stop()
            stop_droidcam()
            motor.close()
            sys.exit(0)

        except Exception as e:
            print(f"[Kimo] Error: {e}")


if __name__ == "__main__":
    main()
