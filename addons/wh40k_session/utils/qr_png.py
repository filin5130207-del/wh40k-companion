"""Local QR PNG generation (no open proxy to public QR CDNs)."""

from __future__ import annotations

import re
import struct
import zlib
from pathlib import Path

JOIN_URL_RE = re.compile(
    r"^https?://[^/\s]+/wh40k/join/[a-fA-F0-9-]{16,64}/?$",
    re.IGNORECASE,
)


def _load_vendored_qrcode():
    lib_dir = Path(__file__).resolve().parents[1] / "lib"
    import sys

    lib_str = str(lib_dir)
    if lib_str not in sys.path:
        sys.path.insert(0, lib_str)
    import qrcode  # noqa: WPS433 — vendored under addons/.../lib/qrcode

    return qrcode


def _png_chunk(tag: bytes, data: bytes) -> bytes:
    return (
        struct.pack(">I", len(data))
        + tag
        + data
        + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)
    )


def _matrix_to_png(matrix, scale: int = 8, border: int = 2) -> bytes:
    """Encode a boolean matrix as a grayscale PNG (stdlib only)."""
    rows = len(matrix)
    cols = len(matrix[0]) if rows else 0
    width = (cols + border * 2) * scale
    height = (rows + border * 2) * scale
    raw = bytearray()
    white = 255
    black = 0
    for y in range(height):
        raw.append(0)  # filter: None
        my = y // scale - border
        for x in range(width):
            mx = x // scale - border
            if 0 <= my < rows and 0 <= mx < cols and matrix[my][mx]:
                raw.append(black)
            else:
                raw.append(white)
    compressed = zlib.compress(bytes(raw), level=9)
    ihdr = struct.pack(">IIBBBBB", width, height, 8, 0, 0, 0, 0)
    return (
        b"\x89PNG\r\n\x1a\n"
        + _png_chunk(b"IHDR", ihdr)
        + _png_chunk(b"IDAT", compressed)
        + _png_chunk(b"IEND", b"")
    )


def render_join_qr_png(data: str, size: int = 260) -> bytes:
    """Render a PNG QR for a WH40k join URL only.

    Raises ValueError if the payload is not an allowed join URL.
    """
    payload = (data or "").strip()
    if not payload or len(payload) > 512:
        raise ValueError("QR payload missing or too long.")
    if not JOIN_URL_RE.match(payload):
        raise ValueError("QR payload must be a /wh40k/join/<uuid> URL.")

    size_i = max(80, min(512, int(size or 260)))
    qrcode = _load_vendored_qrcode()
    qr = qrcode.QRCode(error_correction=qrcode.constants.ERROR_CORRECT_M, border=1)
    qr.add_data(payload)
    qr.make(fit=True)
    matrix = qr.get_matrix()
    modules = len(matrix) + 2  # account for border used in encoder
    scale = max(2, size_i // max(modules, 1))
    return _matrix_to_png(matrix, scale=scale, border=2)
