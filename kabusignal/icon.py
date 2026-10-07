"""
kabusignal/icon.py
===================
ホーム画面用アイコン(青地に白い右肩上がりの線)を PNG で書き出す。画像ライブラリは使わない。
"""

import math
import struct
import zlib

BG = (47, 91, 211)
FG = (255, 255, 255)
POINTS = [(0.18, 0.70), (0.40, 0.48), (0.56, 0.60), (0.82, 0.30)]


def _dist(px, py, ax, ay, bx, by):
    dx, dy = bx - ax, by - ay
    t = max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / (dx * dx + dy * dy)))
    return math.hypot(px - (ax + t * dx), py - (ay + t * dy))


def png(size: int) -> bytes:
    half_width = 0.045
    segs = list(zip(POINTS, POINTS[1:]))
    rows = []
    for y in range(size):
        row = bytearray([0])
        fy = (y + 0.5) / size
        for x in range(size):
            fx = (x + 0.5) / size
            d = min(_dist(fx, fy, a[0], a[1], b[0], b[1]) for a, b in segs)
            # 線の縁を1ピクセル分だけぼかす
            a = max(0.0, min(1.0, (half_width - d) * size + 0.5))
            row += bytes(round(bg + (fg - bg) * a) for bg, fg in zip(BG, FG))
        rows.append(bytes(row))

    def chunk(tag, data):
        return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)

    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", size, size, 8, 2, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(b"".join(rows), 9)) + chunk(b"IEND", b""))
