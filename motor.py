"""
motor.py — PySerial wrapper for sending commands to the Arduino over USB.
"""

import time
import serial
import serial.tools.list_ports

_CANDIDATE_PORTS = ["/dev/ttyACM0", "/dev/ttyUSB0"]
BAUD_RATE = 9600
ARDUINO_BOOT_DELAY = 2.0  # seconds — Arduino resets on serial connect


def _find_port() -> str:
    """Return the first available candidate port, or raise if none found."""
    for port in _CANDIDATE_PORTS:
        try:
            s = serial.Serial(port, BAUD_RATE, timeout=0.1)
            s.close()
            return port
        except serial.SerialException:
            continue
    raise RuntimeError(
        f"Arduino not found on {_CANDIDATE_PORTS}. "
        "Check USB cable and that the correct port is listed in /dev/."
    )


class MotorController:
    def __init__(self, port: str | None = None, baudrate: int = BAUD_RATE):
        resolved_port = port or _find_port()
        print(f"[Motor] Connecting to Arduino on {resolved_port}...")
        self._serial = serial.Serial(resolved_port, baudrate, timeout=1)
        time.sleep(ARDUINO_BOOT_DELAY)  # wait for Arduino to finish reset
        print("[Motor] Arduino ready.")

    def send_command(self, command: str) -> None:
        """Send a newline-terminated command string to the Arduino."""
        self._serial.write(f"{command}\n".encode())
        print(f"[Motor] → {command}")

    def close(self) -> None:
        """Stop motors and close the serial port."""
        if self._serial.is_open:
            self.send_command("STOP")
            self._serial.close()
            print("[Motor] Serial port closed.")
