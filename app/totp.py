"""RFC 6238 TOTP arithmetic — pure, standard library only.

No Flask import and no database import: this module is testable as
arithmetic, against the published RFC vectors, and that is the whole point
of keeping it separate. The flow tests in tests/test_auth.py compute their
expected codes with this module, so they prove the FLOW; correctness of the
algorithm is proved in tests/test_totp.py against RFC 4226 Appendix D and
RFC 6238 Appendix B instead.

Only SHA-1 is supported. RFC 6238's SHA-256 and SHA-512 vectors use
different, longer seeds, and every authenticator app in practice speaks
SHA-1 — claiming the other two without testing them would be a lie the
tests could not catch.
"""

import base64
import hashlib
import hmac
import secrets
import struct
import time
from urllib.parse import quote

TOTP_DIGITS = 6
TOTP_PERIOD = 30
TOTP_SKEW = 1  # ±1 step, and no wider
SECRET_BYTES = 20  # 160 bits, the RFC 4226 recommendation

# Injection point so tests can pin the step boundary without waiting.
# The idiom is app/messages.py's _now: a test monkeypatches this one name
# and both the replay and the skew assertions become deterministic, with no
# clock faked inside the app and no time.sleep anywhere.
_now = time.time


def hotp(secret, counter, digits=TOTP_DIGITS):
    """The RFC 4226 HOTP value for a counter, as a zero-padded string.

    `digits` is a PARAMETER and not the constant baked in on purpose:
    RFC 6238's published test vectors are 8-digit, so an implementation
    that hard-codes six cannot be checked against them at all.
    """
    digest = hmac.new(
        secret, struct.pack(">Q", counter), hashlib.sha1
    ).digest()
    offset = digest[-1] & 0x0F
    truncated = struct.unpack(">I", digest[offset:offset + 4])[0] & 0x7FFFFFFF
    return str(truncated % (10 ** digits)).zfill(digits)


def step_for(at, period=TOTP_PERIOD):
    """The RFC 6238 time step containing `at` (T0 = 0)."""
    return int(at) // period


def accepted_step(secret, code, last_step, at=None, skew=TOTP_SKEW):
    """The step a code verifies at, or None.

    Both of the rules a second factor lives or dies by are enforced here,
    in one place, so no caller can hold one and forget the other:

      - codes are compared with hmac.compare_digest, never ==, so a wrong
        code costs the same time whatever prefix it shares with the right
        one;
      - a match at a step at or below `last_step` is REFUSED outright and
        does not fall through to another candidate — that is the replay
        rule, and falling through would quietly reinstate the replay it
        exists to stop.

    at=None means "now", resolved through the module's _now seam.
    """
    if at is None:
        at = _now()
    current = step_for(at)
    for offset in range(-skew, skew + 1):
        step = current + offset
        if step < 0:
            continue
        candidate = hotp(secret, step)
        if hmac.compare_digest(candidate, code):
            if last_step is not None and step <= last_step:
                return None
            return step
    return None


def random_secret():
    """A fresh shared secret as unpadded base32 — what an app is given."""
    return base64.b32encode(secrets.token_bytes(SECRET_BYTES)).decode(
        "ascii"
    ).rstrip("=")


def decode_secret(b32):
    """The raw bytes of a stored base32 secret, re-padding as needed.

    random_secret strips the padding because that is the form authenticator
    apps show and accept; b32decode insists on it, so it is put back here
    rather than stored. Any padding already there is stripped first, so a
    secret pasted back with or without it decodes the same — as do the
    spaces and the lower case a person copying it off a screen will add.
    """
    text = b32.strip().replace(" ", "").upper().rstrip("=")
    text += "=" * (-len(text) % 8)
    return base64.b32decode(text)


def otpauth_uri(secret_b32, account, issuer):
    """The otpauth:// URI an authenticator app imports.

    Everything a person typed is percent-encoded: an account name or brand
    containing a space or a colon would otherwise break the label, and the
    label separator IS a colon.
    """
    label = quote(f"{issuer}:{account}", safe="")
    query = (
        f"secret={quote(secret_b32, safe='')}"
        f"&issuer={quote(issuer, safe='')}"
        f"&algorithm=SHA1&digits={TOTP_DIGITS}&period={TOTP_PERIOD}"
    )
    return f"otpauth://totp/{label}?{query}"
