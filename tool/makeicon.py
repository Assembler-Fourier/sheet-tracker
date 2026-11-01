"""Draws the Sheet Tracker icon and writes tool\\app.ico. Standard library only - no PIL.

    python makeicon.py            write tool\\app.ico
    python makeicon.py look.png   also write a big PNG to look at

The mark: an amber tile, seven day columns for Monday to Sunday, and a tick under each - the Mon-Sun week
the tool is built around. Deliberately nothing like the Check Call Log icon (navy tile, blue circle, tick),
because the two shortcuts sit side by side on the Desktop and have to be told apart at 16x16.

Everything is drawn at 8x and averaged down, which is what keeps the small sizes from going ragged.
"""
import os
import struct
import sys
import zlib

HERE = os.path.dirname(os.path.abspath(__file__))
SIZES = [16, 20, 24, 32, 40, 48, 64, 128, 256]
SS = 8                                                 # drawn this many times bigger, then averaged down

AMBER = (0xF2, 0x9D, 0x1B)                             # the tile
AMBER_DEEP = (0xD4, 0x7F, 0x0A)                        # its lower half, a flat two-tone so it reads at 16px
PAPER = (0xFF, 0xFF, 0xFF)
INK = (0x6B, 0x3F, 0x05)
GREEN = (0x16, 0x7C, 0x3C)


class Pad:
    """A plain RGBA canvas with the few shapes this icon needs."""

    def __init__(self, n):
        self.n = n
        self.px = bytearray(n * n * 4)

    def blend(self, x, y, rgb, a=1.0):
        if not (0 <= x < self.n and 0 <= y < self.n) or a <= 0:
            return
        i = (y * self.n + x) * 4
        old = self.px[i:i + 4]
        oa = old[3] / 255.0
        na = a + oa * (1 - a)
        for c in range(3):
            was = old[c] / 255.0 * oa
            now = rgb[c] / 255.0 * a + was * (1 - a)
            self.px[i + c] = int(round(now / na * 255)) if na else 0
        self.px[i + 3] = int(round(na * 255))

    def rect(self, x0, y0, x1, y1, rgb, r=0):
        for y in range(int(y0), int(y1)):
            for x in range(int(x0), int(x1)):
                if r:
                    for cx, cy in ((x0 + r, y0 + r), (x1 - r, y0 + r), (x0 + r, y1 - r), (x1 - r, y1 - r)):
                        if ((x < x0 + r and cx == x0 + r) or (x >= x1 - r and cx == x1 - r)) and \
                           ((y < y0 + r and cy == y0 + r) or (y >= y1 - r and cy == y1 - r)):
                            if (x + 0.5 - cx) ** 2 + (y + 0.5 - cy) ** 2 > r * r:
                                break
                    else:
                        self.blend(x, y, rgb)
                    continue
                self.blend(x, y, rgb)

    def circle(self, cx, cy, r, rgb):
        for y in range(int(cy - r - 1), int(cy + r + 2)):
            for x in range(int(cx - r - 1), int(cx + r + 2)):
                if (x + 0.5 - cx) ** 2 + (y + 0.5 - cy) ** 2 <= r * r:
                    self.blend(x, y, rgb)

    def line(self, x0, y0, x1, y1, rgb, w):
        """A thick line with round ends, done the dumb way: every pixel near the segment."""
        dx, dy = x1 - x0, y1 - y0
        length = max(1e-6, (dx * dx + dy * dy) ** 0.5)
        half = w / 2.0
        for y in range(int(min(y0, y1) - half - 1), int(max(y0, y1) + half + 2)):
            for x in range(int(min(x0, x1) - half - 1), int(max(x0, x1) + half + 2)):
                t = max(0.0, min(1.0, ((x + 0.5 - x0) * dx + (y + 0.5 - y0) * dy) / (length * length)))
                px, py = x0 + t * dx, y0 + t * dy
                if (x + 0.5 - px) ** 2 + (y + 0.5 - py) ** 2 <= half * half:
                    self.blend(x, y, rgb)

    def down(self, n):
        """Average down to n x n - the anti-aliasing."""
        out = Pad(n)
        step = self.n // n
        area = step * step
        for y in range(n):
            for x in range(n):
                r = g = b = a = 0
                for sy in range(y * step, (y + 1) * step):
                    base = sy * self.n
                    for sx in range(x * step, (x + 1) * step):
                        i = (base + sx) * 4
                        pa = self.px[i + 3]
                        r += self.px[i] * pa
                        g += self.px[i + 1] * pa
                        b += self.px[i + 2] * pa
                        a += pa
                i = (y * n + x) * 4
                if a:
                    out.px[i] = min(255, r // a)
                    out.px[i + 1] = min(255, g // a)
                    out.px[i + 2] = min(255, b // a)
                out.px[i + 3] = a // area
        return out


def draw(n):
    """The mark: an amber tile, a white week sheet with a column per day, and a green tick badge."""
    big = n * SS
    p = Pad(big)
    u = big / 32.0                                     # one unit = 1/32 of the icon
    tiny = n <= 24                                     # at tiny sizes: fewer, fatter columns, bigger badge

    p.rect(u * 1.5, u * 1.5, u * 30.5, u * 30.5, AMBER, r=u * 7)

    # the sheet, sitting high and left so the badge has a corner to itself
    p.rect(u * 4.5, u * 5.5, u * 25.5, u * 24.0, PAPER, r=u * 2.2)

    # a column per day, standing on a baseline inside the sheet
    days = 4 if tiny else 7
    left, right = u * 7.0, u * 23.0
    gap = (right - left) / days
    bar = gap * (0.66 if tiny else 0.56)
    foot = u * 20.5
    highs = (0.46, 0.78, 0.34, 0.92, 0.58, 0.86, 0.66)     # a week never looks the same two days running
    for i in range(days):
        x = left + gap * i + (gap - bar) / 2.0
        high = highs[i * 2 if tiny else i] * (u * 11.0)
        p.rect(x, foot - high, x + bar, foot, AMBER_DEEP, r=bar * 0.35)
    p.rect(u * 7.0, foot + u * 0.5, u * 23.0, foot + u * 1.3, INK, r=u * 0.4)   # the line they stand on

    # the badge: a green disc in the free corner, ringed so it lifts off both the sheet and the tile
    r = u * (8.6 if tiny else 7.6)
    cx, cy = u * 23.0, u * 23.0
    p.circle(cx, cy, r + u * 1.6, PAPER)
    p.circle(cx, cy, r, GREEN)
    w = r * 0.30
    p.line(cx - r * 0.44, cy + r * 0.02, cx - r * 0.10, cy + r * 0.38, PAPER, w)
    p.line(cx - r * 0.10, cy + r * 0.38, cx + r * 0.48, cy - r * 0.36, PAPER, w)
    return p.down(n)


def png(pad):
    """A PNG of one pad, for looking at."""
    raw = b""
    for y in range(pad.n):
        raw += b"\x00" + bytes(pad.px[y * pad.n * 4:(y + 1) * pad.n * 4])

    def chunk(kind, data):
        c = struct.pack(">I", len(data)) + kind + data
        return c + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF)

    return (b"\x89PNG\r\n\x1a\n"
            + chunk(b"IHDR", struct.pack(">IIBBBBB", pad.n, pad.n, 8, 6, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(raw, 9))
            + chunk(b"IEND", b""))


def dib(pad):
    """One icon entry as a bottom-up BGRA bitmap with the AND mask Windows still wants."""
    n = pad.n
    head = struct.pack("<IiiHHIIiiII", 40, n, n * 2, 1, 32, 0, n * n * 4, 0, 0, 0, 0)
    rows = []
    for y in range(n - 1, -1, -1):
        row = bytearray()
        for x in range(n):
            i = (y * n + x) * 4
            row += bytes((pad.px[i + 2], pad.px[i + 1], pad.px[i], pad.px[i + 3]))
        rows.append(bytes(row))
    mask_row = ((n + 31) // 32) * 4                    # the AND mask is padded to 4 bytes a row
    return head + b"".join(rows) + b"\x00" * (mask_row * n)


def main():
    pads = [(n, draw(n)) for n in SIZES]
    parts = [dib(p) for _, p in pads]
    out = struct.pack("<HHH", 0, 1, len(parts))
    offset = 6 + 16 * len(parts)
    for (n, _), data in zip(pads, parts):
        out += struct.pack("<BBBBHHII", n % 256, n % 256, 0, 0, 1, 32, len(data), offset)
        offset += len(data)
    out += b"".join(parts)
    path = os.path.join(HERE, "app.ico")
    with open(path, "wb") as f:
        f.write(out)
    print("wrote %s  (%d sizes, %d bytes)" % (path, len(parts), len(out)))
    if len(sys.argv) > 1:
        with open(sys.argv[1], "wb") as f:
            f.write(png(dict(pads)[256]))
        print("wrote " + sys.argv[1])


if __name__ == "__main__":
    main()
