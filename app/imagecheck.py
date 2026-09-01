"""Structural image validation (LLM-COP-21): is this really a PNG or a JPEG?

The closed set is PNG and JPEG, and nothing else — an extension proves
nothing and a magic-byte prefix proves almost nothing, so every byte of the
file is walked. PNG is tiled chunk by chunk with every CRC recomputed; JPEG
is tiled marker by marker with every segment length followed. A file that
does not tile exactly is refused.

No decoder, and deliberately no Pillow. The product's whole production
dependency list is one line (requirements.txt), we never render pixels, and
a large C-extension image stack is precisely where image CVEs live. But
declining a dependency is not free: it moves the dependency's safety duties
onto this module, which is why the dimension bound below exists at all.

**The bound.** Pillow refuses above 178,956,970 pixels
(DecompressionBombError) and warns above 89,478,485. We never decode — we
*displace* the decode onto every visitor's browser, and the serving path
caches for a year, so one accepted file is decoded forever. A 69-byte upload
declaring 30000x30000 in its header sails past any byte cap and costs every
visitor a multi-gigabyte allocation attempt. So the bound is checked the
moment the dimensions are read (IHDR for PNG, SOF for JPEG), before any
further parsing:

    MAX_IMAGE_PIXELS = 25,000,000   MAX_IMAGE_EDGE = 10,000

25 Mpx clears everything the product needs — a 6000x4000 full-frame camera
JPEG is 24 Mpx, V2's 5K full-bleed hero is 14.7 Mpx, the wizard asks for at
least 600x600 — while being 7x tighter than Pillow's own refusal. The edge
clause is independent, not decoration: a 1 x 25,000,000 strip passes the
pixel bound exactly and is still a pathological allocation, because decoders
allocate per row. It is a maximum only; the validator enforces no minimum
beyond 1 x 1, so the suite's 4x4 fixtures and a small-but-adequate portrait
both pass.

Two honest caveats on that bound, neither of which changes it:

  * IHDR's bit depth, colour type and interlace flag are read as opaque
    bytes and are not validated. "25 Mpx is about 100 MB decoded" is the
    8-bit RGBA figure; a 16-bit image is roughly double, and an interlaced
    one costs more passes.
  * An APNG passes, because acTL and fcTL are well-formed ancillary chunks
    carrying correct CRCs. Decode cost then depends on frame count as well
    as on dimensions, so "dimensions alone" is the still-image statement.

**Trailing bytes: JPEG canonicalises, PNG refuses.** The asymmetry is a
decision about the world, not about taste. Phone cameras really do emit MPF
and thumbnail blocks after EOI and the reference implementation accepts
them, so refusing there would refuse the owner's own photograph — the exact
failure this JPEG parser exists to prevent. So JPEG accepts an appendix and
then drops it: facts.data is the span the parser actually tiled, ending at
EOI. Callers hash and store *that*, never the request body, so an appended
payload is structurally incapable of reaching disk and the same photograph
with and without padding is one file. No PNG encoder appends after IEND —
IEND ends the datastream and the ecosystem agrees — so PNG keeps the
refusal, which is louder than a silent trim: if a PNG has bytes after IEND,
something hand-built it and the owner should be told.

**What this does not do.** A polyglot — a structurally perfect PNG carrying
a payload inside a chunk with a correct CRC — is accepted, and no validator
short of re-encoding refuses one. It is inert because of the *serving* path
(a content type we determined, nosniff, a sandbox CSP, bytes served by a
Flask view rather than by a web server mapping extensions onto
interpreters), not because of anything here. Say that plainly rather than
implying the parser makes a file harmless.

**Cost.** The JPEG entropy scan uses bytes.find rather than a Python-level
byte loop, which is about 60x faster on real photographs (a few ms at the
5 MB cap) — the common case, and the reason for the choice. It is not a
bound: adversarial input made entirely of stuffed FF 00 pairs measures
~585 ms at the cap, restart markers ~665 ms, and a PNG of many tiny empty
ancillary chunks ~347 ms. On stuffed input find is in fact ~2x slower than
the byte loop. The upload route is admin-only and behind a 5 MB cap, so
this is a cost note rather than a denial-of-service surface.
"""

import struct
import zlib
from collections import namedtuple

PNG_SIG = b"\x89PNG\r\n\x1a\n"

MAX_IMAGE_PIXELS = 25_000_000
MAX_IMAGE_EDGE = 10_000

# data is the CANONICAL span — identical to the input for PNG, truncated at
# EOI for JPEG. It, and never the request body, is what gets hashed, stored
# and served.
ImageFacts = namedtuple(
    "ImageFacts", "content_type extension width height data"
)

# The two refusal reasons, so the route can answer something the owner can
# act on instead of one flat "not an image".
FORMAT = "format"
DIMENSIONS = "dimensions"


def _bounded(width, height):
    return (
        0 < width <= MAX_IMAGE_EDGE
        and 0 < height <= MAX_IMAGE_EDGE
        and width * height <= MAX_IMAGE_PIXELS
    )


def _parse_png(data):
    """Walk every chunk: length, type, body, CRC — and refuse on any gap."""
    if not data.startswith(PNG_SIG):
        return None, FORMAT
    off = len(PNG_SIG)
    first = True
    dims = None
    idats = 0
    ihdrs = 0
    n = len(data)
    while off < n:
        if off + 8 > n:
            return None, FORMAT
        (length,) = struct.unpack(">I", data[off:off + 4])
        ctype = data[off + 4:off + 8]
        # bytes.isalpha() is ASCII-only, which is exactly the chunk-type
        # alphabet; anything else means we are not tiling a real PNG.
        if not ctype.isalpha():
            return None, FORMAT
        end = off + 8 + length + 4
        # length is compared to n first so a declared 4 GB chunk cannot
        # overflow the offset arithmetic before the bounds check sees it.
        if length > n or end > n:
            return None, FORMAT
        body = data[off + 8:off + 8 + length]
        (want_crc,) = struct.unpack(">I", data[end - 4:end])
        if zlib.crc32(ctype + body) & 0xFFFFFFFF != want_crc:
            return None, FORMAT
        if ctype == b"IHDR":
            ihdrs += 1
            if not first or ihdrs > 1 or length != 13:
                return None, FORMAT
            width, height = struct.unpack(">II", body[:8])
            if width == 0 or height == 0:
                return None, FORMAT
            if not _bounded(width, height):
                return None, DIMENSIONS
            dims = (width, height)
        elif first:
            return None, FORMAT  # the first chunk must be IHDR
        first = False
        if ctype == b"IDAT":
            idats += 1
        if ctype == b"IEND":
            # A signature, an IHDR and an IEND is a valid-looking file
            # carrying no image at all; at least one IDAT is required.
            if length != 0 or idats == 0:
                return None, FORMAT
            off = end
            # IEND ends the datastream. Nothing may follow it — see the
            # module docstring for why PNG refuses where JPEG canonicalises.
            if off != n:
                return None, FORMAT
            return ImageFacts("image/png", "png", dims[0], dims[1], data), None
        off = end
    return None, FORMAT


# Markers that carry no length word at all: SOI, EOI, TEM and the eight
# restart markers.
_STANDALONE = {0xD8, 0xD9, 0x01} | set(range(0xD0, 0xD8))
# Start Of Frame in all its flavours; C4 (DHT), C8 (JPG) and CC (DAC) share
# the range but are ordinary segments.
_SOF = set(range(0xC0, 0xD0)) - {0xC4, 0xC8, 0xCC}


def _parse_jpeg(data):
    """Walk marker by marker, following every segment length, and scan the
    entropy-coded data for the marker that ends it."""
    if len(data) < 4 or data[0:2] != b"\xff\xd8":
        return None, FORMAT
    off = 2
    dims = None
    saw_sos = False
    n = len(data)
    while off < n:
        if data[off] != 0xFF:
            return None, FORMAT
        while off < n and data[off] == 0xFF:
            off += 1  # any number of FF fill bytes may precede a marker
        if off >= n:
            return None, FORMAT
        marker = data[off]
        off += 1
        if marker in _STANDALONE:
            if marker == 0xD9:
                # EOI. Refuse a file that never carried a frame or scan;
                # otherwise return the tiled span and drop any appendix.
                if not (saw_sos and dims):
                    return None, FORMAT
                return (
                    ImageFacts(
                        "image/jpeg", "jpg", dims[0], dims[1], data[:off]
                    ),
                    None,
                )
            continue
        if off + 2 > n:
            return None, FORMAT
        (seglen,) = struct.unpack(">H", data[off:off + 2])
        if seglen < 2 or off + seglen > n:
            return None, FORMAT
        if marker in _SOF:
            if seglen < 8:
                return None, FORMAT
            height, width = struct.unpack(">HH", data[off + 3:off + 7])
            if width == 0 or height == 0:
                return None, FORMAT
            if not _bounded(width, height):
                return None, DIMENSIONS
            dims = (width, height)
        off += seglen
        if marker == 0xDA:
            # SOS: entropy-coded data follows, in which FF 00 is a stuffed
            # literal and FF D0-D7 are restart markers. Anything else after
            # an FF is the next real marker. bytes.find does the scanning —
            # see the module docstring on what that costs.
            saw_sos = True
            while off < n - 1:
                hit = data.find(b"\xff", off)
                if hit < 0 or hit >= n - 1:
                    return None, FORMAT
                nxt = data[hit + 1]
                if nxt != 0x00 and not (0xD0 <= nxt <= 0xD7):
                    off = hit
                    break
                off = hit + 2
            else:
                return None, FORMAT
    return None, FORMAT


# One tuple, so a third format is one function and one entry.
_PARSERS = (_parse_png, _parse_jpeg)


def sniff_image(data):
    """The seam: -> (ImageFacts, None) on acceptance, (None, reason) on
    refusal, where reason is FORMAT or DIMENSIONS.

    DIMENSIONS wins over FORMAT when any parser got far enough to read a
    header and refuse it on the bound, so "your picture is too large" is
    never flattened into "your file is not an image".
    """
    reason = FORMAT
    for parser in _PARSERS:
        facts, why = parser(data)
        if facts is not None:
            return facts, None
        if why == DIMENSIONS:
            reason = DIMENSIONS
    return None, reason
