"""The structural image validator, proved against a real attack corpus.

`app/imagecheck.py` is the whole of what stands between a byte string that
arrived from outside the process and the instance directory, so the rule for
this module is stricter than "assert what it does":

    EVERY TEST HERE IS WRITTEN TO FAIL IF ITS DEFENCE IS DELETED.

That is why refusals assert the *reason code* and not merely `facts is None`.
A refusal for the wrong reason means the intended guard is not the thing doing
the work — `bomb.png` refused as `"format"` would say the dimension bound was
never consulted and the parser merely tripped over something else. r1 of this
plan really did accept both bombs, so the discrimination is not hypothetical.

## Where the fixtures come from, and why none of them is read at run time

Nothing here opens a file. Every input is either built by `struct`/`zlib` in
this module or embedded as a base64 literal, and `test_fixtures_are_the_corpus`
pins the SHA-256 of each one against the digest of the corresponding attack
corpus artifact, measured offline. So "self-contained" does not cost fidelity:
these ARE the corpus bytes, and the test says so in a way that would break if
a builder ever drifted.

- **The PNGs are built here.** `_png` and `_png_claiming` reproduce
  `corpus/valid.png`, `corpus/valid-large.png` and `corpus/bomb.png`
  byte-identically (asserted below). Building rather than embedding is what
  lets the dimension cases be minted at any size without materialising a
  900-megapixel raster — which is precisely the bomb's own trick.
- **The JPEGs are real encoder output, minted OFFLINE.** The gate's
  interpreter (`.venv`) has no Pillow and none may be added, so these were
  produced by the *system* Python 3's Pillow 10.2.0 and pasted in as base64.
  That provenance is the point: they are a real encoder's bytes rather than
  something hand-rolled to satisfy our own parser. **This module never imports
  PIL.**

`corpus/trailing.jpg` and `corpus/bomb.jpg` in particular are load-bearing:
Pillow 10.2.0 ACCEPTS the first (16 bytes of padding after EOI) and REFUSES
the second (`DecompressionBombError`, 900000000 pixels), and this validator is
required to agree with it on both.
"""

import base64
import hashlib
import struct
import zlib

import pytest

from app.imagecheck import MAX_IMAGE_EDGE, MAX_IMAGE_PIXELS, sniff_image

# ---------------------------------------------------------------------------
# PNG construction (stdlib only, no fixture files)
# ---------------------------------------------------------------------------

PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"


def _chunk(kind, payload):
    """One PNG chunk with a genuinely computed CRC-32."""
    crc = zlib.crc32(kind + payload) & 0xFFFFFFFF
    return struct.pack(">I", len(payload)) + kind + payload + struct.pack(">I", crc)


def _ihdr(width, height, bit_depth=8, colour_type=2, interlace=0):
    body = struct.pack(
        ">IIBBBBB", width, height, bit_depth, colour_type, 0, 0, interlace
    )
    return _chunk(b"IHDR", body)


def _png(width, height, colour=(0xC8, 0x78, 0x3C)):
    """A real PNG: every scanline present, filter 0, honestly compressed.

    At 4x4 and 64x64 this is byte-identical to corpus/valid.png and
    corpus/valid-large.png.
    """
    raw = b"".join(b"\x00" + bytes(colour) * width for _ in range(height))
    return (
        PNG_SIGNATURE
        + _ihdr(width, height)
        + _chunk(b"IDAT", zlib.compress(raw))
        + _chunk(b"IEND", b"")
    )


def _png_claiming(width, height):
    """A structurally perfect PNG whose IHDR CLAIMS (width, height) while the
    IDAT stays tiny — the decompression-bomb shape, and the reason a bound on
    declared dimensions is the only place this can be refused.

    At 30000x30000 this is byte-identical to corpus/bomb.png (69 bytes).
    """
    return (
        PNG_SIGNATURE
        + _ihdr(width, height)
        + _chunk(b"IDAT", zlib.compress(b"\x00" * 100))
        + _chunk(b"IEND", b"")
    )


# ---------------------------------------------------------------------------
# JPEG fixtures — real Pillow 10.2.0 output, minted offline, embedded here.
# The gate's interpreter has no PIL and this module never imports it.
# ---------------------------------------------------------------------------

JPEG_8X8_B64 = (
    "/9j/4AAQSkZJRgABAQAAAQABAAD/2wBDAAYEBQYFBAYGBQYHBwYIChAKCgkJChQODwwQFxQY"
    "GBcUFhYaHSUfGhsjHBYWICwgIyYnKSopGR8tMC0oMCUoKSj/2wBDAQcHBwoIChMKChMoGhYa"
    "KCgoKCgoKCgoKCgoKCgoKCgoKCgoKCgoKCgoKCgoKCgoKCgoKCgoKCgoKCgoKCgoKCj/wAAR"
    "CAAIAAgDASIAAhEBAxEB/8QAHwAAAQUBAQEBAQEAAAAAAAAAAAECAwQFBgcICQoL/8QAtRAA"
    "AgEDAwIEAwUFBAQAAAF9AQIDAAQRBRIhMUEGE1FhByJxFDKBkaEII0KxwRVS0fAkM2JyggkK"
    "FhcYGRolJicoKSo0NTY3ODk6Q0RFRkdISUpTVFVWV1hZWmNkZWZnaGlqc3R1dnd4eXqDhIWG"
    "h4iJipKTlJWWl5iZmqKjpKWmp6ipqrKztLW2t7i5usLDxMXGx8jJytLT1NXW19jZ2uHi4+Tl"
    "5ufo6erx8vP09fb3+Pn6/8QAHwEAAwEBAQEBAQEBAQAAAAAAAAECAwQFBgcICQoL/8QAtREA"
    "AgECBAQDBAcFBAQAAQJ3AAECAxEEBSExBhJBUQdhcRMiMoEIFEKRobHBCSMzUvAVYnLRChYk"
    "NOEl8RcYGRomJygpKjU2Nzg5OkNERUZHSElKU1RVVldYWVpjZGVmZ2hpanN0dXZ3eHl6goOE"
    "hYaHiImKkpOUlZaXmJmaoqOkpaanqKmqsrO0tba3uLm6wsPExcbHyMnK0tPU1dbX2Nna4uPk"
    "5ebn6Onq8vP09fb3+Pn6/9oADAMBAAIRAxEAPwDIooor5E+4P//Z"
)
JPEG_PROGRESSIVE_B64 = (
    "/9j/4AAQSkZJRgABAQAAAQABAAD/2wBDAAgGBgcGBQgHBwcJCQgKDBQNDAsLDBkSEw8UHRof"
    "Hh0aHBwgJC4nICIsIxwcKDcpLDAxNDQ0Hyc5PTgyPC4zNDL/2wBDAQkJCQwLDBgNDRgyIRwh"
    "MjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjL/wgAR"
    "CABAAEADASIAAhEBAxEB/8QAFQABAQAAAAAAAAAAAAAAAAAAAAT/xAAVAQEBAAAAAAAAAAAA"
    "AAAAAAAABf/aAAwDAQACEAMQAAABmE2sAAAAAAAAAAAAAAB//8QAFBABAAAAAAAAAAAAAAAA"
    "AAAAYP/aAAgBAQABBQIB/8QAFBEBAAAAAAAAAAAAAAAAAAAAQP/aAAgBAwEBPwEH/8QAFBEB"
    "AAAAAAAAAAAAAAAAAAAAQP/aAAgBAgEBPwEH/8QAFBABAAAAAAAAAAAAAAAAAAAAYP/aAAgB"
    "AQAGPwIB/8QAFBABAAAAAAAAAAAAAAAAAAAAYP/aAAgBAQABPyEB/9oADAMBAAIAAwAAABDz"
    "zzzzzzzzzzzzzzz/xAAUEQEAAAAAAAAAAAAAAAAAAABA/9oACAEDAQE/EAf/xAAUEQEAAAAA"
    "AAAAAAAAAAAAAABA/9oACAECAQE/EAf/xAAUEAEAAAAAAAAAAAAAAAAAAABg/9oACAEBAAE/"
    "EAH/2Q=="
)
JPEG_PHOTO_B64 = (
    "/9j/4AAQSkZJRgABAQAAAQABAAD/2wBDAAUDBAQEAwUEBAQFBQUGBwwIBwcHBw8LCwkMEQ8S"
    "EhEPERETFhwXExQaFRERGCEYGh0dHx8fExciJCIeJBweHx7/2wBDAQUFBQcGBw4ICA4eFBEU"
    "Hh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh7/wAAR"
    "CAHgAoADASIAAhEBAxEB/8QAHwAAAQUBAQEBAQEAAAAAAAAAAAECAwQFBgcICQoL/8QAtRAA"
    "AgEDAwIEAwUFBAQAAAF9AQIDAAQRBRIhMUEGE1FhByJxFDKBkaEII0KxwRVS0fAkM2JyggkK"
    "FhcYGRolJicoKSo0NTY3ODk6Q0RFRkdISUpTVFVWV1hZWmNkZWZnaGlqc3R1dnd4eXqDhIWG"
    "h4iJipKTlJWWl5iZmqKjpKWmp6ipqrKztLW2t7i5usLDxMXGx8jJytLT1NXW19jZ2uHi4+Tl"
    "5ufo6erx8vP09fb3+Pn6/8QAHwEAAwEBAQEBAQEBAQAAAAAAAAECAwQFBgcICQoL/8QAtREA"
    "AgECBAQDBAcFBAQAAQJ3AAECAxEEBSExBhJBUQdhcRMiMoEIFEKRobHBCSMzUvAVYnLRChYk"
    "NOEl8RcYGRomJygpKjU2Nzg5OkNERUZHSElKU1RVVldYWVpjZGVmZ2hpanN0dXZ3eHl6goOE"
    "hYaHiImKkpOUlZaXmJmaoqOkpaanqKmqsrO0tba3uLm6wsPExcbHyMnK0tPU1dbX2Nna4uPk"
    "5ebn6Onq8vP09fb3+Pn6/9oADAMBAAIRAxEAPwDEooor8/P04KKKKACiiigAooooAKKKKACi"
    "iigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAoooo"
    "AKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACi"
    "iigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAoooo"
    "AKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACi"
    "iigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAoooo"
    "AKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACi"
    "iigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAoooo"
    "AKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACi"
    "iigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAoooo"
    "AKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACi"
    "iigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAoooo"
    "AKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACi"
    "iigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAoooo"
    "AKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACi"
    "iigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAoooo"
    "AKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACi"
    "iigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAoooo"
    "AKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACi"
    "iigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAoooo"
    "AKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACi"
    "iigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAoooo"
    "AKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACi"
    "iigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAoooo"
    "AKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACi"
    "iigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAoooo"
    "AKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACi"
    "iigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAoooo"
    "AKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACi"
    "iigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAoooo"
    "AKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACi"
    "iigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAoooo"
    "AKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACi"
    "iigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAoooo"
    "AKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACi"
    "iigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAoooo"
    "AKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACi"
    "iigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAoooo"
    "AKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACi"
    "iigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAoooo"
    "AKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACi"
    "iigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAoooo"
    "AKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACi"
    "iigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAoooo"
    "AKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACi"
    "iigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAoooo"
    "AKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACi"
    "iigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAoooo"
    "AKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACi"
    "iigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAoooo"
    "AKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACi"
    "iigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAoooo"
    "AKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACi"
    "iigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAoooo"
    "AKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACi"
    "iigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAoooo"
    "AKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACi"
    "iigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAoooo"
    "AKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACi"
    "iigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAoooo"
    "AKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACi"
    "iigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAoooo"
    "AKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACi"
    "iigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAoooo"
    "AKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACi"
    "iigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAoooo"
    "AKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACi"
    "iigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAoooo"
    "AKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACi"
    "iigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAoooo"
    "AKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACi"
    "iigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAoooo"
    "AKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACi"
    "iigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAoooo"
    "AKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACi"
    "iigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAoooo"
    "AKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACi"
    "iigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAoooo"
    "AKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACi"
    "iigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAoooo"
    "AKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACi"
    "iigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAoooo"
    "AKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACi"
    "iigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAoooo"
    "AKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACi"
    "iigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAoooo"
    "AKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACi"
    "iigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAoooo"
    "AKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACi"
    "iigAooooAKKKKACiiigAooooAKKKKACiiigD/9k="
)
JPEG_TRAILING_B64 = (
    "/9j/4AAQSkZJRgABAQAAAQABAAD/2wBDAAgGBgcGBQgHBwcJCQgKDBQNDAsLDBkSEw8UHRof"
    "Hh0aHBwgJC4nICIsIxwcKDcpLDAxNDQ0Hyc5PTgyPC4zNDL/2wBDAQkJCQwLDBgNDRgyIRwh"
    "MjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjL/wAAR"
    "CAAIAAgDASIAAhEBAxEB/8QAHwAAAQUBAQEBAQEAAAAAAAAAAAECAwQFBgcICQoL/8QAtRAA"
    "AgEDAwIEAwUFBAQAAAF9AQIDAAQRBRIhMUEGE1FhByJxFDKBkaEII0KxwRVS0fAkM2JyggkK"
    "FhcYGRolJicoKSo0NTY3ODk6Q0RFRkdISUpTVFVWV1hZWmNkZWZnaGlqc3R1dnd4eXqDhIWG"
    "h4iJipKTlJWWl5iZmqKjpKWmp6ipqrKztLW2t7i5usLDxMXGx8jJytLT1NXW19jZ2uHi4+Tl"
    "5ufo6erx8vP09fb3+Pn6/8QAHwEAAwEBAQEBAQEBAQAAAAAAAAECAwQFBgcICQoL/8QAtREA"
    "AgECBAQDBAcFBAQAAQJ3AAECAxEEBSExBhJBUQdhcRMiMoEIFEKRobHBCSMzUvAVYnLRChYk"
    "NOEl8RcYGRomJygpKjU2Nzg5OkNERUZHSElKU1RVVldYWVpjZGVmZ2hpanN0dXZ3eHl6goOE"
    "hYaHiImKkpOUlZaXmJmaoqOkpaanqKmqsrO0tba3uLm6wsPExcbHyMnK0tPU1dbX2Nna4uPk"
    "5ebn6Onq8vP09fb3+Pn6/9oADAMBAAIRAxEAPwDwGiiimI//2QAAAAAAAAAAAAAAAAAAAAA="
)
JPEG_BOMB_B64 = (
    "/9j/4AAQSkZJRgABAQAAAQABAAD/2wBDAAgGBgcGBQgHBwcJCQgKDBQNDAsLDBkSEw8UHRof"
    "Hh0aHBwgJC4nICIsIxwcKDcpLDAxNDQ0Hyc5PTgyPC4zNDL/2wBDAQkJCQwLDBgNDRgyIRwh"
    "MjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjL/wAAR"
    "CHUwdTADASIAAhEBAxEB/8QAHwAAAQUBAQEBAQEAAAAAAAAAAAECAwQFBgcICQoL/8QAtRAA"
    "AgEDAwIEAwUFBAQAAAF9AQIDAAQRBRIhMUEGE1FhByJxFDKBkaEII0KxwRVS0fAkM2JyggkK"
    "FhcYGRolJicoKSo0NTY3ODk6Q0RFRkdISUpTVFVWV1hZWmNkZWZnaGlqc3R1dnd4eXqDhIWG"
    "h4iJipKTlJWWl5iZmqKjpKWmp6ipqrKztLW2t7i5usLDxMXGx8jJytLT1NXW19jZ2uHi4+Tl"
    "5ufo6erx8vP09fb3+Pn6/8QAHwEAAwEBAQEBAQEBAQAAAAAAAAECAwQFBgcICQoL/8QAtREA"
    "AgECBAQDBAcFBAQAAQJ3AAECAxEEBSExBhJBUQdhcRMiMoEIFEKRobHBCSMzUvAVYnLRChYk"
    "NOEl8RcYGRomJygpKjU2Nzg5OkNERUZHSElKU1RVVldYWVpjZGVmZ2hpanN0dXZ3eHl6goOE"
    "hYaHiImKkpOUlZaXmJmaoqOkpaanqKmqsrO0tba3uLm6wsPExcbHyMnK0tPU1dbX2Nna4uPk"
    "5ebn6Onq8vP09fb3+Pn6/9oADAMBAAIRAxEAPwDwGiiimI//2Q=="
)

JPEG_8X8 = base64.b64decode(JPEG_8X8_B64)
JPEG_PROGRESSIVE = base64.b64decode(JPEG_PROGRESSIVE_B64)
JPEG_PHOTO = base64.b64decode(JPEG_PHOTO_B64)
JPEG_TRAILING = base64.b64decode(JPEG_TRAILING_B64)
JPEG_BOMB = base64.b64decode(JPEG_BOMB_B64)

# The JPEG whose entropy data trailing.jpg carries, without the 16 pad bytes:
# what canonicalisation is required to store.
JPEG_TRAILING_CANONICAL = JPEG_TRAILING[:631]

_SOF_MARKERS = frozenset(
    m for m in range(0xC0, 0xD0) if m not in (0xC4, 0xC8, 0xCC)
)


def _jpeg_claiming(width, height, base=JPEG_8X8):
    """A real JPEG with its frame header rewritten to claim (width, height).

    This is how corpus/bomb.jpg was made and it is how a JPEG bomb is made in
    the wild: the SOF is a *claim*, and a decoder allocates against the claim
    long before it discovers the entropy data does not fill it. Everything
    outside the two patched 16-bit fields is untouched real encoder output.
    """
    offset = 2
    while offset < len(base) - 1:
        assert base[offset] == 0xFF, "not at a marker"
        marker = base[offset + 1]
        if marker in (0xD8, 0x01) or 0xD0 <= marker <= 0xD7:
            offset += 2
            continue
        (length,) = struct.unpack(">H", base[offset + 2 : offset + 4])
        if marker in _SOF_MARKERS:
            # FF xx | length(2) | precision(1) | height(2) | width(2)
            return (
                base[: offset + 5]
                + struct.pack(">HH", height, width)
                + base[offset + 9 :]
            )
        if marker == 0xDA:
            break
        offset += 2 + length
    raise AssertionError("no SOF marker found in the base JPEG")


# ---------------------------------------------------------------------------
# Non-images, byte-identical to the corpus
# ---------------------------------------------------------------------------

XSS_SVG = (
    b'<?xml version="1.0"?>\n<svg xmlns="http://www.w3.org/2000/svg"'
    b' width="100" height="100"><script>alert(document.domain)</script>'
    b'<image href="x" onerror="alert(1)"/></svg>'
)
NOT_AN_IMAGE = b"this is definitely not an image, it is just prose.\n" * 10
EVIL_MAGIC = PNG_SIGNATURE + b'<?php system($_GET["c"]); ?>' * 20
TRUNCATED_PNG = _png(4, 4)[:36]
PHP_PAYLOAD = b'<?php system($_GET[0]); ?>'


def _badcrc_png():
    """corpus/badcrc.png: valid.png with one byte of the IHDR CRC flipped."""
    data = bytearray(_png(4, 4))
    data[29] ^= 0xFF
    return bytes(data)


def _oversize_png():
    """corpus/oversize.png: a valid 4x4 PNG with 12 MiB of padding after IEND.

    Pillow 10.2.0 ACCEPTS this as a 4x4 PNG. We refuse it. It is the one place
    this validator is knowingly stricter than the reference implementation.
    """
    return _png(4, 4) + b"\x00" * (12 * 1024 * 1024)


# ---------------------------------------------------------------------------
# Provenance
# ---------------------------------------------------------------------------

# SHA-256 of each attack-corpus artifact, measured offline against the files in
# scratchpad/LLM-COP-21/corpus/. The builders and literals above must land on
# these digests, which is what makes "self-contained" free of fidelity loss.
CORPUS_DIGESTS = {
    "valid.png": "2aaf301a0d419bf2c046b4a0dc440727519af83a2d3ce050e1e11ca144089b0b",
    "valid-large.png": "9ac5b03e9f1afb38898fe6e1dca137c469a26f0178e3cae25010147c2e74acae",
    "bomb.png": "d64d14d1a3522f2d25d3f1b1778d48d287d7fb5abc371dc5ddc142d216c6bae0",
    "valid.jpg": "28f1f3a394e4570cfa0d71a1492619cf3a59fcdbf6e1a5435fa94e9c5f5b3c07",
    "valid-progressive.jpg": (
        "1a46a1f96fe518bfe221c29cfe993d1bb57e489bf1bad97af1b7cf87ac51537c"
    ),
    "valid-photo.jpg": (
        "2da545e4eac8c7e8ad97a969e1f91fedb7fd0a1f6e43eb9f1487235151f732a6"
    ),
    "trailing.jpg": "5ece882a9e7eddae00a8ad350b5f0eeb771ccbf239d314a07f0aa482b062a617",
    "bomb.jpg": "1df165b9e0b5a25eeed8e17dd84f38fec30e83bfd85f1b37f703650a79043a78",
    "xss.svg": "2867ee25b0f97809a31b66c5f875f74e948257afd04f4910efa9afa5a1826ba7",
    "notanimage.png": "c4c58166e0b4d7d98feaec6353547dff8dd5c60677c6cbec3fd99b4f037d8278",
    "evil-magic.png": "7114ace81ed1cb8464d33d2dde3d03aed3095e6bcdc825138741c2381fe5463a",
    "oversize.png": "4f5358c6cd9ff118741a36c6625a951eabb1bfcdbde29ca56e8f812f3e71addd",
}


@pytest.mark.parametrize(
    "name,data",
    [
        ("valid.png", _png(4, 4)),
        ("valid-large.png", _png(64, 64)),
        ("bomb.png", _png_claiming(30000, 30000)),
        ("valid.jpg", JPEG_8X8),
        ("valid-progressive.jpg", JPEG_PROGRESSIVE),
        ("valid-photo.jpg", JPEG_PHOTO),
        ("trailing.jpg", JPEG_TRAILING),
        ("bomb.jpg", JPEG_BOMB),
        ("xss.svg", XSS_SVG),
        ("notanimage.png", NOT_AN_IMAGE),
        ("evil-magic.png", EVIL_MAGIC),
    ],
)
def test_fixtures_are_the_corpus(name, data):
    """The bytes exercised here are the attack corpus, not a paraphrase.

    If a builder is ever "tidied" into producing something slightly different,
    every refusal test below would still pass while no longer testing the
    artifact it names. This is the test that stops that.
    """
    assert hashlib.sha256(data).hexdigest() == CORPUS_DIGESTS[name]


def test_the_jpeg_bomb_builder_agrees_with_the_corpus_bomb():
    """_jpeg_claiming is the corpus bomb's own construction, not a lookalike.

    corpus/bomb.jpg is trailing.jpg's canonical span with the SOF patched to
    30000x30000; rebuilding it from that base must reproduce it byte for byte.
    """
    assert _jpeg_claiming(30000, 30000, base=JPEG_TRAILING_CANONICAL) == JPEG_BOMB


# ---------------------------------------------------------------------------
# The bound is a product decision, so it is pinned, not derived
# ---------------------------------------------------------------------------


def test_the_bound_is_the_one_that_was_decided():
    """Every dimension case below is derived from these two constants, so
    without this test a future edit could relax the bound to 900 megapixels
    and the derived cases would happily follow it. Pinning the numbers is what
    makes the derivation safe.

    Provenance (plan-r2, Decision 1): 25 Mpx clears a 6000x4000 full-frame
    camera JPEG (24 Mpx) and a 5K full-bleed hero (14.7 Mpx), and sits 7.2x
    under Pillow 10.2.0's own refusal threshold of 178,956,970 pixels.
    """
    assert MAX_IMAGE_PIXELS == 25_000_000
    assert MAX_IMAGE_EDGE == 10_000


# ---------------------------------------------------------------------------
# Accept
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "name,data,content_type,extension,width,height,stored",
    [
        ("valid.png", _png(4, 4), "image/png", "png", 4, 4, 73),
        ("valid-large.png", _png(64, 64), "image/png", "png", 64, 64, 179),
        ("valid.jpg", JPEG_8X8, "image/jpeg", "jpg", 8, 8, 633),
        (
            "valid-progressive.jpg",
            JPEG_PROGRESSIVE,
            "image/jpeg",
            "jpg",
            64,
            64,
            544,
        ),
        ("valid-photo.jpg", JPEG_PHOTO, "image/jpeg", "jpg", 640, 480, 5429),
        # 16 bytes of padding after EOI, which Pillow accepts and phone
        # cameras really emit (MPF / thumbnail blocks). Accepted, and the
        # padding is dropped: 647 in, 631 stored.
        ("trailing.jpg", JPEG_TRAILING, "image/jpeg", "jpg", 8, 8, 631),
        # 1x1 is legal. The wizard's "at least 600x600" is copy, not a rule:
        # enforcing it would refuse the fixtures this suite is built from.
        ("1x1.png", _png(1, 1), "image/png", "png", 1, 1, None),
    ],
)
def test_accepts_real_images(
    name, data, content_type, extension, width, height, stored
):
    """A validator that refused everything would pass every hazard test in
    this file. These are the cases that stop it being one — and they carry the
    determined content type, which is what the serving path later trusts
    instead of anything the client asserted.
    """
    facts, reason = sniff_image(data)
    assert reason is None, f"{name} was refused as {reason!r}"
    assert facts is not None
    assert facts.content_type == content_type
    assert facts.extension == extension
    assert (facts.width, facts.height) == (width, height)
    if stored is not None:
        assert len(facts.data) == stored


# ---------------------------------------------------------------------------
# Refuse: structure
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "name,data",
    [
        # The conductor's own stated test case: correct magic bytes are not a
        # decode, and a prefix check alone must not pass this file.
        ("png signature + php", PNG_SIGNATURE + PHP_PAYLOAD),
        ("evil-magic.png", EVIL_MAGIC),
        ("notanimage.png", NOT_AN_IMAGE),
        ("truncated.png", TRUNCATED_PNG),
        ("badcrc.png", _badcrc_png()),
        # An SVG is a script vector. It is outside the closed set, and it is
        # refused on its bytes, so renaming it changes nothing (the route
        # never looks at the name at all — see tests/test_images.py).
        ("xss.svg", XSS_SVG),
        ("xss-svg-named.png", XSS_SVG),
        ("png + trailing php", _png(4, 4) + b"<?php ?>"),
        ("png 0x0", _png_claiming(0, 0)),
        ("png 4x0", _png_claiming(4, 0)),
        ("jpeg soi + php", b"\xff\xd8" + b"<?php ?>"),
        ("jpeg truncated mid-scan", JPEG_8X8[:316]),
        ("jpeg without EOI", JPEG_8X8[:-2]),
        ("empty", b""),
        ("hello world", b"hello world"),
        ("gif", b"GIF89a" + b"\x00" * 20),
        ("bmp", b"BM" + b"\x00" * 40),
        ("webp riff", b"RIFF\x00\x00\x00\x00WEBPVP8 " + b"\x00" * 16),
        ("pdf", b"%PDF-1.4\n" + b"\x00" * 40),
        ("zip", b"PK\x03\x04" + b"\x00" * 40),
    ],
)
def test_refuses_non_images_with_the_format_reason(name, data):
    """`format`, specifically — the owner is told the file is not an intact
    PNG or JPEG, which is a different and differently actionable message from
    the one the dimension bound produces.
    """
    facts, reason = sniff_image(data)
    assert facts is None, f"{name} was ACCEPTED"
    assert reason == "format", f"{name} refused as {reason!r}, expected 'format'"


def test_refuses_a_png_carrying_no_image_data_at_all():
    """Signature + IHDR + IEND parses perfectly and contains no image.

    r1's walker accepted this. At least one IDAT is now required, so deleting
    that clause makes this test fail.
    """
    empty = PNG_SIGNATURE + _ihdr(4, 4) + _chunk(b"IEND", b"")
    facts, reason = sniff_image(empty)
    assert facts is None
    assert reason == "format"


def test_refuses_a_png_with_two_ihdr_chunks():
    """Exactly one header, or the dimensions the bound was checked against are
    not the dimensions a decoder will use."""
    data = (
        PNG_SIGNATURE
        + _ihdr(4, 4)
        + _ihdr(30000, 30000)
        + _chunk(b"IDAT", zlib.compress(b"\x00" * 100))
        + _chunk(b"IEND", b"")
    )
    facts, reason = sniff_image(data)
    assert facts is None
    assert reason == "format"


def test_refuses_a_png_whose_header_is_not_first():
    """IHDR must come first, for the same reason: the bound has to be applied
    to the header a decoder will actually honour."""
    data = (
        PNG_SIGNATURE
        + _chunk(b"tEXt", b"comment\x00hello")
        + _ihdr(4, 4)
        + _chunk(b"IDAT", zlib.compress(b"\x00" * 100))
        + _chunk(b"IEND", b"")
    )
    facts, reason = sniff_image(data)
    assert facts is None
    assert reason == "format"


def test_refuses_bytes_after_iend_however_few():
    """PNG's no-appendix rule, tested at one byte as well as at 12 MiB.

    Every Pillow-emitted PNG ends exactly at IEND (default, optimize,
    compress_level=0, interlace — all measured), so no real encoder pays for
    this and anything that trips it was hand-built.
    """
    facts, reason = sniff_image(_png(4, 4) + b"\x00")
    assert facts is None
    assert reason == "format"


def test_refuses_oversize_png_where_pillow_accepts_it():
    """corpus/oversize.png: 12 MiB of garbage after IEND.

    Pillow 10.2.0 accepts this as a 4x4 PNG. This is the one case where the
    validator is deliberately stricter than the reference implementation, and
    it exists so the claim is checked rather than asserted in a PR body.
    """
    facts, reason = sniff_image(_oversize_png())
    assert facts is None
    assert reason == "format"


# ---------------------------------------------------------------------------
# Refuse: the dimension bound — both clauses, both sides, both formats
# ---------------------------------------------------------------------------

# Each case isolates ONE clause, so deleting either clause fails a test that
# the other clause cannot rescue:
#
#   pixels only  9000x9000  = 81 Mpx, both edges well under 10000
#   edge only    10001x2000 = 20 Mpx, under the pixel bound
#
# and the accepted cases sit hard against the bound from the inside, so
# tightening the bound by one pixel in either dimension also fails.

_ACCEPTED_DIMENSIONS = [
    ("exactly on both bounds", MAX_IMAGE_EDGE, MAX_IMAGE_PIXELS // MAX_IMAGE_EDGE),
    ("one under the edge", MAX_IMAGE_EDGE - 1, 2500),
    ("one under the pixel bound", 5000, (MAX_IMAGE_PIXELS - 1) // 5000),
    ("a 6000x4000 camera frame", 6000, 4000),
    ("a 5K full-bleed hero", 5120, 2880),
]

_REFUSED_DIMENSIONS = [
    ("bomb, both clauses", 30000, 30000),
    ("pixel clause alone", 9000, 9000),
    ("edge clause alone", MAX_IMAGE_EDGE + 1, 2000),
    ("one over the edge", MAX_IMAGE_EDGE + 1, 2500),
    ("one over the pixel bound", MAX_IMAGE_EDGE, MAX_IMAGE_PIXELS // MAX_IMAGE_EDGE + 1),
    # The widest strip a JPEG can even declare (see JPEG_MAX_DECLARABLE): the
    # pixel count is trivial, so only the edge clause can refuse these.
    ("a one-pixel-tall strip", 65535, 1),
    ("a one-pixel-wide strip", 1, 65535),
]

# JPEG's SOF frame header stores height and width as 16-bit fields, so the
# largest image a JPEG can DECLARE is 65535x65535. That is still 4.29
# gigapixels — 171x our bound — so the bound is doing real work on JPEG too;
# it just means the pixel-bound-exactly strip below is a PNG-only shape.
JPEG_MAX_DECLARABLE = 65535


@pytest.mark.parametrize(
    "width,height",
    [pytest.param(w, h, id=n) for n, w, h in _ACCEPTED_DIMENSIONS],
)
@pytest.mark.parametrize("fmt", ["png", "jpeg"])
def test_accepts_dimensions_inside_the_bound(fmt, width, height):
    data = _png_claiming(width, height) if fmt == "png" else _jpeg_claiming(
        width, height
    )
    facts, reason = sniff_image(data)
    assert reason is None, f"{fmt} {width}x{height} refused as {reason!r}"
    assert (facts.width, facts.height) == (width, height)


@pytest.mark.parametrize(
    "width,height",
    [pytest.param(w, h, id=n) for n, w, h in _REFUSED_DIMENSIONS],
)
@pytest.mark.parametrize("fmt", ["png", "jpeg"])
def test_refuses_dimensions_outside_the_bound(fmt, width, height):
    """`dimensions`, not `format`.

    This is the discrimination that matters. A decompression bomb is a
    STRUCTURALLY PERFECT file — every chunk correct, every CRC right, the
    entropy data ending cleanly at EOI. Nothing but a bound on the declared
    dimensions can refuse it, so a `format` answer here would prove the bound
    was never reached and something else tripped by luck.
    """
    data = _png_claiming(width, height) if fmt == "png" else _jpeg_claiming(
        width, height
    )
    facts, reason = sniff_image(data)
    assert facts is None, f"{fmt} {width}x{height} was ACCEPTED"
    assert reason == "dimensions", (
        f"{fmt} {width}x{height} refused as {reason!r}; a bomb must be refused"
        " by the dimension bound, not incidentally by a structural rule"
    )


@pytest.mark.parametrize(
    "width,height",
    [
        pytest.param(1, MAX_IMAGE_PIXELS, id="one-pixel-wide"),
        pytest.param(MAX_IMAGE_PIXELS, 1, id="one-pixel-tall"),
    ],
)
def test_a_strip_exactly_on_the_pixel_bound_is_still_refused(width, height):
    """The case that proves the edge clause is not decoration — PNG only,
    because only PNG can declare a dimension this large (JPEG's SOF fields are
    16-bit; see JPEG_MAX_DECLARABLE).

    1 x 25,000,000 passes the pixel bound EXACTLY. It is nonetheless a
    pathological allocation, because decoders allocate per row. Delete
    MAX_IMAGE_EDGE and nothing else in this file catches it: the pixel clause
    is satisfied to the pixel.
    """
    facts, reason = sniff_image(_png_claiming(width, height))
    assert facts is None, f"{width}x{height} was ACCEPTED"
    assert reason == "dimensions"


def test_the_largest_jpeg_expressible_is_still_far_over_the_bound():
    """65535x65535 is 4.29 gigapixels — the bound is not vacuous for JPEG."""
    facts, reason = sniff_image(
        _jpeg_claiming(JPEG_MAX_DECLARABLE, JPEG_MAX_DECLARABLE)
    )
    assert facts is None
    assert reason == "dimensions"


@pytest.mark.parametrize(
    "name,data", [("bomb.png", _png_claiming(30000, 30000)), ("bomb.jpg", JPEG_BOMB)]
)
def test_the_corpus_bombs_are_refused_by_the_bound(name, data):
    """The two artifacts by name, against Pillow's own verdict.

    Pillow 10.2.0 refuses both with
    `DecompressionBombError: Image size (900000000 pixels) exceeds limit of
    178956970 pixels`. We refuse both too, 7.2x earlier. r1 of this plan
    ACCEPTED both, which is what this test exists to prevent recurring.
    """
    facts, reason = sniff_image(data)
    assert facts is None, f"{name} was ACCEPTED"
    assert reason == "dimensions"


def test_the_bomb_is_otherwise_a_perfectly_valid_file():
    """Proof that the previous test is really the bound doing the work.

    The same 69 bytes with a sane IHDR are accepted. So the ONLY difference
    between accept and refuse is the declared size — which is the definition
    of the guard being the thing under test.
    """
    facts, reason = sniff_image(_png_claiming(4, 4))
    assert reason is None and facts is not None
    assert (facts.width, facts.height) == (4, 4)


# ---------------------------------------------------------------------------
# Canonicalisation: what is stored is the span that was tiled, never the input
# ---------------------------------------------------------------------------


def test_an_appended_payload_cannot_reach_storage():
    """A JPEG with a PHP payload glued on is accepted — and stores zero
    appended bytes.

    This is the whole of Decision 2. Refusing would reject the owner's own
    phone photograph (phones append MPF and thumbnail blocks after EOI, and
    Pillow accepts them). Accepting as-is would store the payload. Hashing and
    storing the tiled span does neither: the result is byte-identical to the
    clean file and therefore dedupes onto it.
    """
    clean, reason = sniff_image(JPEG_8X8)
    assert reason is None
    dirty, reason = sniff_image(JPEG_8X8 + PHP_PAYLOAD)
    assert reason is None, f"the appended-payload JPEG was refused as {reason!r}"

    assert dirty.data == clean.data
    assert PHP_PAYLOAD not in dirty.data
    assert dirty.data.endswith(b"\xff\xd9")
    # Same bytes therefore same digest therefore one file on disk.
    assert (
        hashlib.sha256(dirty.data).hexdigest()
        == hashlib.sha256(clean.data).hexdigest()
    )


def test_trailing_padding_is_dropped_not_stored():
    """corpus/trailing.jpg: 647 bytes in, 631 out, ending at EOI."""
    facts, reason = sniff_image(JPEG_TRAILING)
    assert reason is None
    assert len(JPEG_TRAILING) == 647
    assert facts.data == JPEG_TRAILING_CANONICAL
    assert len(facts.data) == 631
    assert facts.data.endswith(b"\xff\xd9")


def test_the_same_photograph_padded_or_not_costs_one_file():
    """The digest is over the canonical span, so padding does not fork
    storage — which is the dedup claim, at the layer that decides it."""
    padded, _ = sniff_image(JPEG_TRAILING)
    bare, _ = sniff_image(JPEG_TRAILING_CANONICAL)
    assert padded.data == bare.data


def test_png_canonical_bytes_are_the_input_exactly():
    """PNG refuses an appendix rather than trimming one, so for an accepted
    PNG the canonical span is the whole input — no silent rewriting."""
    data = _png(64, 64)
    facts, reason = sniff_image(data)
    assert reason is None
    assert facts.data == data


# ---------------------------------------------------------------------------
# The interface the route is built on
# ---------------------------------------------------------------------------


def test_the_extension_is_ours_and_matches_the_content_type():
    """The stored name is computed from these two, never from the client's
    filename, so they must be a closed and consistent pair."""
    png, _ = sniff_image(_png(4, 4))
    jpeg, _ = sniff_image(JPEG_8X8)
    assert (png.content_type, png.extension) == ("image/png", "png")
    assert (jpeg.content_type, jpeg.extension) == ("image/jpeg", "jpg")


def test_refusal_never_returns_facts_and_acceptance_never_returns_a_reason():
    """The two-channel contract the route switches on."""
    for data in (_png(4, 4), JPEG_8X8):
        facts, reason = sniff_image(data)
        assert facts is not None and reason is None
    for data in (XSS_SVG, _png_claiming(30000, 30000)):
        facts, reason = sniff_image(data)
        assert facts is None and reason in ("format", "dimensions")


def test_sniff_image_does_not_mutate_or_alias_its_input():
    """facts.data must not be a view onto a caller-owned buffer."""
    data = _png(4, 4)
    original = bytes(data)
    facts, _ = sniff_image(data)
    assert data == original
    assert isinstance(facts.data, bytes)


# ---------------------------------------------------------------------------
# Disclosed limits — pinned so the disclosure cannot quietly become a claim
# ---------------------------------------------------------------------------


def test_a_polyglot_inside_a_well_formed_chunk_is_accepted():
    """The honest limit, asserted rather than only written down.

    A payload inside an ancillary chunk with a correct CRC is structurally
    indistinguishable from a comment, and no validator short of re-encoding
    refuses it. It is inert because of the SERVING path — a Flask view, a
    content type we determined, nosniff and a sandbox CSP — not because of
    this parser. tests/test_images.py proves that half.
    """
    data = (
        PNG_SIGNATURE
        + _ihdr(4, 4)
        + _chunk(b"tEXt", b"comment\x00" + PHP_PAYLOAD)
        + _chunk(b"IDAT", zlib.compress(b"\x00" * 100))
        + _chunk(b"IEND", b"")
    )
    facts, reason = sniff_image(data)
    assert reason is None
    # And it is stored verbatim, payload and all — say so plainly.
    assert PHP_PAYLOAD in facts.data


def test_an_apng_passes_as_a_still_png():
    """acTL/fcTL are well-formed ancillary chunks, so an APNG is admitted and
    its animation is not costed. Disclosed in app/imagecheck.py's docstring;
    pinned here so the docstring stays true."""
    actl = struct.pack(">II", 2, 0)
    data = (
        PNG_SIGNATURE
        + _ihdr(4, 4)
        + _chunk(b"acTL", actl)
        + _chunk(b"IDAT", zlib.compress(b"\x00" * 100))
        + _chunk(b"IEND", b"")
    )
    facts, reason = sniff_image(data)
    assert reason is None
    assert (facts.width, facts.height) == (4, 4)


def test_bit_depth_is_not_validated_so_the_memory_figure_is_the_8_bit_one():
    """A 16-bit image at the pixel bound is admitted and decodes to roughly
    double the ~100 MB the bound was reasoned against. Disclosed, not fixed:
    the bound is on dimensions because decode cost tracks dimensions."""
    data = (
        PNG_SIGNATURE
        + _ihdr(5000, 5000, bit_depth=16, colour_type=6)
        + _chunk(b"IDAT", zlib.compress(b"\x00" * 100))
        + _chunk(b"IEND", b"")
    )
    facts, reason = sniff_image(data)
    assert reason is None
    assert (facts.width, facts.height) == (5000, 5000)
