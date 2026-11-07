"""Minimal DDS (DXT1/DXT5) decoder + PNG encoder — standard library only.

Used to serve the game's icon textures to the mod manager UI. Handles the
formats DoW2 uses for UI icons (DXT5, some DXT1); mipmaps are ignored (level
0 only).
"""
from __future__ import annotations
import struct
import zlib


def _rgb565(c):
    r = (c >> 11) & 0x1F
    g = (c >> 5) & 0x3F
    b = c & 0x1F
    return ((r << 3) | (r >> 2), (g << 2) | (g >> 4), (b << 3) | (b >> 2))


def _decode_color_block(block, out, bx, by, w, h, alpha=None):
    c0, c1, bits = struct.unpack_from("<HHI", block, 0)
    p0 = _rgb565(c0)
    p1 = _rgb565(c1)
    if c0 > c1 or alpha is not None:      # 4-colour mode (always for DXT5)
        pal = (p0, p1,
               tuple((2 * a + b) // 3 for a, b in zip(p0, p1)),
               tuple((a + 2 * b) // 3 for a, b in zip(p0, p1)))
        pal_a = (255, 255, 255, 255)
    else:                                  # 3-colour + transparent (DXT1)
        pal = (p0, p1,
               tuple((a + b) // 2 for a, b in zip(p0, p1)),
               (0, 0, 0))
        pal_a = (255, 255, 255, 0)
    for j in range(4):
        for i in range(4):
            x, y = bx + i, by + j
            if x >= w or y >= h:
                continue
            idx = (bits >> (2 * (4 * j + i))) & 0x3
            r, g, b = pal[idx]
            a = alpha[4 * j + i] if alpha is not None else pal_a[idx]
            o = 4 * (y * w + x)
            out[o:o + 4] = bytes((r, g, b, a))


def _decode_dxt5_alpha(block):
    a0, a1 = block[0], block[1]
    bits = int.from_bytes(block[2:8], "little")
    if a0 > a1:
        pal = (a0, a1) + tuple(((7 - i) * a0 + i * a1) // 7 for i in range(1, 7))
    else:
        pal = (a0, a1) + tuple(((5 - i) * a0 + i * a1) // 5 for i in range(1, 5)) + (0, 255)
    return [pal[(bits >> (3 * i)) & 0x7] for i in range(16)]


def decode(data: bytes) -> tuple[int, int, bytearray]:
    """DDS bytes -> (width, height, RGBA8 pixel buffer)."""
    if data[:4] != b"DDS ":
        raise ValueError("not a DDS file")
    h = struct.unpack_from("<I", data, 12)[0]
    w = struct.unpack_from("<I", data, 16)[0]
    fourcc = data[84:88]
    out = bytearray(4 * w * h)
    pos = 128
    if fourcc == b"DXT5":
        for by in range(0, h, 4):
            for bx in range(0, w, 4):
                block = data[pos:pos + 16]
                pos += 16
                alpha = _decode_dxt5_alpha(block[:8])
                _decode_color_block(block[8:], out, bx, by, w, h, alpha)
    elif fourcc == b"DXT1":
        for by in range(0, h, 4):
            for bx in range(0, w, 4):
                _decode_color_block(data[pos:pos + 8], out, bx, by, w, h)
                pos += 8
    elif fourcc == b"\x00\x00\x00\x00":     # uncompressed BGRA
        bits = struct.unpack_from("<I", data, 88)[0]
        if bits != 32:
            raise ValueError(f"unsupported uncompressed DDS ({bits}bpp)")
        for i in range(w * h):
            b, g, r, a = data[128 + 4 * i:132 + 4 * i]
            out[4 * i:4 * i + 4] = bytes((r, g, b, a))
    else:
        raise ValueError(f"unsupported DDS fourcc {fourcc!r}")
    return w, h, out


def to_png(data: bytes) -> bytes:
    """DDS bytes -> PNG bytes (RGBA)."""
    w, h, px = decode(data)
    raw = bytearray()
    stride = 4 * w
    for y in range(h):
        raw.append(0)                       # filter: none
        raw += px[y * stride:(y + 1) * stride]

    def chunk(tag: bytes, body: bytes) -> bytes:
        return (struct.pack(">I", len(body)) + tag + body
                + struct.pack(">I", zlib.crc32(tag + body) & 0xFFFFFFFF))

    ihdr = struct.pack(">IIBBBBB", w, h, 8, 6, 0, 0, 0)
    return (b"\x89PNG\r\n\x1a\n"
            + chunk(b"IHDR", ihdr)
            + chunk(b"IDAT", zlib.compress(bytes(raw), 6))
            + chunk(b"IEND", b""))
