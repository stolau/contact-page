"""Plan step 1 — app/totp.py against the published RFC vectors.

This file carries the whole correctness burden for the TOTP arithmetic, and
it is deliberately independent of the app: no Flask, no database, no
fixture. The flow tests in tests/test_auth.py compute their expected codes
with app/totp.py itself, so they can only prove the FLOW — a rigged fixture
if they were the only proof. These vectors are published numbers nobody in
this repository chose.
"""

from app import totp

# RFC 4226 Appendix D, the standard seed for both RFCs.
RFC_SEED = b"12345678901234567890"

# RFC 4226 Appendix D — HOTP values for counters 0..9, six digits.
RFC4226_VALUES = [
    "755224",
    "287082",
    "359152",
    "969429",
    "338314",
    "254676",
    "287922",
    "162583",
    "399871",
    "520489",
]

# RFC 6238 Appendix B, SHA-1 rows ONLY: (T, expected 8-digit TOTP), with
# T0 = 0 and X = 30.
#
# The SHA-256 and SHA-512 rows are omitted ON PURPOSE and this comment is
# the omission being declared rather than hidden: those rows use different,
# longer seeds (20 bytes repeated up to 32 and 64), and app/totp.py
# implements SHA-1 only, which is what every authenticator app speaks.
RFC6238_SHA1 = [
    (59, "94287082"),
    (1111111109, "07081804"),
    (1111111111, "14050471"),
    (1234567890, "89005924"),
    (2000000000, "69279037"),
    (20000000000, "65353130"),
]


def test_hotp_matches_rfc_4226_appendix_d():
    """The ten published HOTP values, in order, from counter 0."""
    got = [totp.hotp(RFC_SEED, counter) for counter in range(10)]
    assert got == RFC4226_VALUES


def test_totp_matches_rfc_6238_appendix_b_sha1():
    """The six published SHA-1 TOTP values.

    digits=8 here, and that is why `digits` is a parameter of hotp() rather
    than the constant baked in: RFC 6238's vectors are eight digits, so an
    implementation that hard-coded six could not be checked against them at
    all — the detail that most often leaves a TOTP module untested.
    """
    for at, expected in RFC6238_SHA1:
        step = totp.step_for(at)
        assert totp.hotp(RFC_SEED, step, digits=8) == expected, at


def test_step_for_is_t0_zero_and_thirty_second_windows():
    assert totp.step_for(0) == 0
    assert totp.step_for(29) == 0
    assert totp.step_for(30) == 1
    assert totp.step_for(59) == 1
    # RFC 6238 Appendix B's own T-values, as decimal steps.
    assert totp.step_for(59) == 1
    assert totp.step_for(1111111109) == 37037036
    assert totp.step_for(20000000000) == 666666666


def _code_at(step):
    return totp.hotp(RFC_SEED, step)


def test_accepted_step_takes_the_current_step_and_one_either_side():
    at = 1000 * totp.TOTP_PERIOD + 15
    here = totp.step_for(at)
    for offset in (-1, 0, 1):
        assert (
            totp.accepted_step(RFC_SEED, _code_at(here + offset), None, at=at)
            == here + offset
        ), offset


def test_accepted_step_refuses_two_steps_away():
    """±1 and no wider — the window is the whole point of the constant."""
    at = 1000 * totp.TOTP_PERIOD + 15
    here = totp.step_for(at)
    for offset in (-2, 2, -3, 3):
        assert (
            totp.accepted_step(RFC_SEED, _code_at(here + offset), None, at=at)
            is None
        ), offset


def test_accepted_step_refuses_a_replayed_or_older_step():
    """The replay rule: at or below last_step is refused, full stop.

    And refused OUTRIGHT, not fallen through to another candidate — a
    fall-through would quietly reinstate the replay this exists to stop,
    which is why the equal case and the strictly-older case are both named.
    """
    at = 1000 * totp.TOTP_PERIOD + 15
    here = totp.step_for(at)
    assert (
        totp.accepted_step(RFC_SEED, _code_at(here), here, at=at) is None
    )
    assert (
        totp.accepted_step(RFC_SEED, _code_at(here), here + 1, at=at) is None
    )
    assert (
        totp.accepted_step(RFC_SEED, _code_at(here - 1), here, at=at) is None
    )
    # A step ABOVE last_step still verifies: the guard is not a lockout.
    assert (
        totp.accepted_step(RFC_SEED, _code_at(here + 1), here, at=at)
        == here + 1
    )


def test_a_wrong_code_is_refused():
    at = 1000 * totp.TOTP_PERIOD + 15
    assert totp.accepted_step(RFC_SEED, "000000", None, at=at) is None
    assert totp.accepted_step(RFC_SEED, "", None, at=at) is None


def test_a_non_ascii_code_is_refused_rather_than_raising():
    """compare_digest raises TypeError on a non-ASCII str; this refuses.

    accepted_step owns the compare_digest rule, so it owns the one input
    that rule cannot be handed. The fullwidth and Arabic-Indic rows are the
    subtle half: str.isdigit() is True for both, so a shape check written
    with isdigit() alone would wave them straight through to the crash.
    """
    at = 1000 * totp.TOTP_PERIOD + 15
    here = totp.step_for(at)
    codes = [
        "12345ä",  # a Finnish keyboard's typo
        "１２３４５６",  # fullwidth digits
        "١٢٣٤٥٦",  # Arabic-Indic digits
        _code_at(here)[:-1] + "ä",  # the right code but for one key
    ]
    for code in codes:
        assert totp.accepted_step(RFC_SEED, code, None, at=at) is None, code


def test_the_now_seam_and_an_explicit_at_agree(monkeypatch):
    """The seam itself is tested, so it cannot rot.

    Every flow test pins app.totp._now to freeze the clock. If _now stopped
    being what accepted_step reads for `at=None`, those tests would go
    quietly non-deterministic instead of red — so the equivalence is
    asserted here, where it is the subject.
    """
    frozen = 1234 * totp.TOTP_PERIOD + 15
    here = totp.step_for(frozen)
    code = _code_at(here)
    monkeypatch.setattr(totp, "_now", lambda: frozen)
    assert totp.accepted_step(RFC_SEED, code, None) == here
    assert totp.accepted_step(RFC_SEED, code, None, at=frozen) == here


def test_random_secret_round_trips_through_decode_secret():
    secret = totp.random_secret()
    assert len(secret) == 32  # 20 bytes of base32, padding stripped
    assert "=" not in secret
    assert len(totp.decode_secret(secret)) == totp.SECRET_BYTES
    # Two draws differ — a constant "random" secret would pass everything
    # else in this file.
    assert totp.random_secret() != secret


def test_decode_secret_accepts_what_a_person_pastes_back():
    secret = totp.random_secret()
    raw = totp.decode_secret(secret)
    assert totp.decode_secret(secret.lower()) == raw
    assert totp.decode_secret(f" {secret[:16]} {secret[16:]} ") == raw
    assert totp.decode_secret(secret + "====") == raw


def test_otpauth_uri_percent_encodes_the_label():
    uri = totp.otpauth_uri("ABCDEF", "an owner:x", "Brand & Co")
    assert uri.startswith("otpauth://totp/")
    # The label separator IS a colon, so a colon inside either half must be
    # encoded or the app reads the label wrong; a space must not break it.
    label = uri[len("otpauth://totp/"):].split("?")[0]
    assert ":" not in label
    assert " " not in label
    assert "Brand%20%26%20Co%3Aan%20owner%3Ax" == label
    assert "secret=ABCDEF" in uri
    assert "algorithm=SHA1" in uri
    assert f"digits={totp.TOTP_DIGITS}" in uri
    assert f"period={totp.TOTP_PERIOD}" in uri
