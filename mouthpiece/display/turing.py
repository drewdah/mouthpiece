"""Minimal driver for the Turing Smart Screen 3.5" rev A (USB serial, VID 1A86 PID 5722).

Protocol: every command is a 6-byte header packing x, y, ex, ey (inclusive
bounds) and a command id; DISPLAY_BITMAP is followed by the rectangle's pixels
as RGB565 little-endian. The link carries a flat ~160 KB/s no matter how the
data is chunked (measured), so callers should only send small dirty rectangles:
a full 320x480 frame takes ~1.9 s.
"""
from __future__ import annotations

import logging
import time
from typing import Optional

import numpy as np
import serial
from PIL import Image
from serial.tools import list_ports

log = logging.getLogger("mouthpiece.turing")

VID, PID, SERIAL_NO = 0x1A86, 0x5722, "USB35INCHIPSV2"

CMD_RESET = 101
CMD_SCREEN_OFF = 108
CMD_SCREEN_ON = 109
CMD_SET_BRIGHTNESS = 110
CMD_SET_ORIENTATION = 121
CMD_DISPLAY_BITMAP = 197
CMD_HELLO = 69
PORTRAIT = 0
BYTES_PER_SEC = 160_000     # measured link throughput
CHUNK = 320 * 8             # bytes per serial write


def find_port() -> Optional[str]:
    for p in list_ports.comports():
        if p.serial_number == SERIAL_NO or (p.vid == VID and p.pid == PID):
            return p.device
    return None


def rgb565(img: Image.Image) -> bytes:
    a = np.asarray(img.convert("RGB"), dtype=np.uint16)
    v = ((a[..., 0] >> 3) << 11) | ((a[..., 1] >> 2) << 5) | (a[..., 2] >> 3)
    return v.astype("<u2").tobytes()


def _header(cmd: int, x: int, y: int, ex: int, ey: int) -> bytes:
    return bytes([x >> 2, ((x & 3) << 6) | (y >> 4), ((y & 15) << 4) | (ex >> 6),
                  ((ex & 63) << 2) | (ey >> 8), ey & 255, cmd])


class TuringRevA:
    width, height = 320, 480

    def __init__(self, port: str = "AUTO") -> None:
        self.port = port
        self.ser: Optional[serial.Serial] = None
        self.bytes_sent = 0

    def _port(self) -> str:
        dev = find_port() if self.port.upper() == "AUTO" else self.port
        if not dev:
            raise OSError("Turing screen not found (VID 1A86 PID 5722)")
        return dev

    def open(self) -> None:
        # Reboot the panel first: if a previous writer died mid-bitmap the device
        # is still waiting for pixels and would eat our commands as image data.
        with serial.Serial(self._port(), 115200, timeout=1, write_timeout=5, rtscts=True) as s:
            s.write(_header(CMD_RESET, 0, 0, 0, 0))
            s.flush()
        time.sleep(5)                       # the COM port can change across the reset
        dev = self._port()
        self.ser = serial.Serial(dev, 115200, timeout=1, write_timeout=5, rtscts=True)
        # HELLO: the official 3.5" does not answer; drain whatever comes back.
        self.ser.write(bytes([CMD_HELLO] * 6))
        self.ser.read(6)
        self.ser.reset_input_buffer()
        orient = bytearray(_header(CMD_SET_ORIENTATION, 0, 0, 0, 0)) + bytes(10)
        orient[6] = PORTRAIT + 100
        orient[7:11] = bytes([self.width >> 8, self.width & 255, self.height >> 8, self.height & 255])
        self.ser.write(bytes(orient))
        # Other tools (InfoPanel) send SCREEN_OFF when they exit; the panel then
        # silently ignores bitmaps until it is switched back on.
        self.ser.write(_header(CMD_SCREEN_ON, 0, 0, 0, 0))
        # The panel drops bytes while it powers up; the protocol has no framing,
        # so a lost byte shifts every later pixel. Let it settle first.
        self.ser.flush()
        time.sleep(1.0)
        self.ser.reset_input_buffer()
        log.info("Turing rev A on %s", dev)

    def screen_off(self) -> None:
        self._write(_header(CMD_SCREEN_OFF, 0, 0, 0, 0))

    def brightness(self, pct: int) -> None:
        # 0 = brightest, 255 = darkest on the wire.
        self._write(_header(CMD_SET_BRIGHTNESS, int(255 - max(0, min(100, pct)) * 2.55), 0, 0, 0))

    def blit(self, img: Image.Image, x: int, y: int) -> int:
        """Draw img at (x, y). Returns bytes sent."""
        w, h = img.size
        data = rgb565(img)
        self._write(_header(CMD_DISPLAY_BITMAP, x, y, x + w - 1, y + h - 1))
        # Same chunking as the reference driver (4 screen rows per write) so the
        # device's small receive buffer never overruns on big rectangles.
        for i in range(0, len(data), CHUNK):
            self._write(data[i:i + CHUNK])
        return len(data)

    def _write(self, data: bytes) -> None:
        if not self.ser:
            raise OSError("screen not open")
        self.ser.write(data)
        self.bytes_sent += len(data)

    def close(self) -> None:
        if self.ser:
            try:
                self.ser.close()
            finally:
                self.ser = None
