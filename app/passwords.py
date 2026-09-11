"""The admin password policy: one question, asked before anything is written.

refusal(password) answers a reason string, or None when the password is
acceptable. Two rules and no others — a minimum length, and absence from a
bundled list of common breached passwords. No maximum length, no "must contain
a symbol": composition rules push people towards P@ssw0rd1! and away from the
long passphrases that actually resist an offline crack.

The two rules compose deliberately. Length alone admits
"correcthorsebatterystaple", which is twenty-five characters and one of the
most-typed passphrases in existence; the list alone would let a one-character
password through. Each catches what the other cannot.

This module is a separate file rather than an addition to app/auth.py because
app/auth.py is the session and audit seam. This one owns a single question and
a data file, imports nothing from the application, and is imported only by the
two CLI commands in app/__init__.py — which is what makes "no web request ever
pays for loading the list" structural rather than a promise.

The list's provenance — the upstream project, the pinned commit, both
checksums, the exact filter that produced it, and the SecLists MIT notice
reproduced in full — lives in the sibling file app/breached_passwords.SOURCE.txt.

THE LIST IS A SNAPSHOT, NOT A CORPUS. It is roughly thirty thousand common
passwords of MIN_LENGTH characters or more, not the ~850-million-entry Have I
Been Pwned set. It must not be described as breached-password checking without
that qualifier: it means "this is not one of the obvious ones", never "this
password has never been breached".
"""

from pathlib import Path

MIN_LENGTH = 12

# WHY AN OFFLINE FILE AND NOT api.pwnedpasswords.com. The usual route to this
# control is the Pwned Passwords k-anonymity range API. It was considered and
# rejected, for four reasons, and the decision is recorded here rather than
# only in a pull request nobody will read again:
#
#   1. This application makes no outbound network call today. requirements.txt
#      is the single line flask==3.1.3, and the only networking name anywhere
#      under app/ is urllib.parse.quote in app/totp.py. An HTTPS call to a
#      third party would be the first socket this product ever opens, and it
#      would open it from the password-changing path.
#   2. Both callers are server CLI commands, run WITHOUT the server.
#      admin-reset-password in particular is what an owner runs while
#      recovering from a suspected compromise — possibly on a firewalled box,
#      possibly offline, possibly on a machine whose DNS is the thing that was
#      tampered with.
#   3. The failure mode has no good answer online. Failing open silently skips
#      the very check we claim to perform. Failing closed turns a transient
#      network fault into "you cannot change your password" — the recovery
#      action denied at the exact moment it is needed. A local file has
#      neither failure mode.
#   4. It leaks, for nothing. The first five hex digits of SHA-1 of the
#      owner's NEW password would go to a third party, from a command run at
#      the moment of compromise. k-anonymity makes that a fair trade for a
#      large site; for a single-owner app, where source IP and timing identify
#      the owner anyway, it is disclosure bought for no benefit.
#
# The list stays small because the length rule refuses everything shorter than
# MIN_LENGTH first, so a shorter entry can never be reached and is filtered out
# when the file is built. That is what turns a million-line corpus into thirty
# thousand lines.
_LIST_PATH = Path(__file__).with_name("breached_passwords.txt")

# The lazy cache. None means "the file has not been read yet", and it stays
# None through import: the list is ~427 KB and is needed by exactly two CLI
# commands, so reading it at import time would charge every web request and
# every test module for a file neither will ever consult. Never at import.
_ENTRIES = None


def refusal(password):
    """Why this password may not be used, or None if it may.

    The returned string is shown to the owner at their own terminal, so it
    says what to do rather than merely that something was wrong.
    """
    # Length is measured on the string EXACTLY as typed: no .strip(), no NFKC
    # normalisation, no truncation. Two reasons. Those are the same bytes
    # generate_password_hash will hash, so a rule measured on anything else
    # would be a rule about a different string than the one that becomes the
    # credential. And silently modifying a submitted password is the thing
    # ASVS forbids outright — an owner who deliberately padded their
    # passphrase with a trailing space must be told the truth about what they
    # typed. (Verified through click.testing.CliRunner against the click this
    # repository resolves: click.prompt re-prompts on empty input and does not
    # strip surrounding whitespace. No version number is written here — click
    # is unpinned, arriving transitively through flask==3.1.3, so a literal
    # would be a claim the repository does not make.)
    if len(password) < MIN_LENGTH:
        return (
            f"the password must be at least {MIN_LENGTH} characters;"
            " a passphrase of a few words is the easiest way there"
        )
    # casefold() on the lookup side, matching the fold the file was built with
    # — see the SOURCE file, where that symmetry is one of four load-bearing
    # properties of the pipeline. A deny-list should over-refuse rather than
    # under-refuse: "Password1234" is not meaningfully harder to crack than
    # "password1234", and refusing both costs an owner one more attempt at
    # something better.
    if password.casefold() in _entries():
        return (
            "that password appears in a list of common breached passwords;"
            " choose one that is not in it"
        )
    return None


def _entries():
    """The deny-list, read once on first use and kept.

    set(text.splitlines()) with no filtering at all, and the data file carries
    no header, which is what makes that safe: a comment filter on a deny-list
    is silently lossy the day a breached password begins with "#". See
    app/breached_passwords.SOURCE.txt.
    """
    global _ENTRIES
    if _ENTRIES is None:
        text = _LIST_PATH.read_text(encoding="utf-8")
        _ENTRIES = frozenset(text.splitlines())
    return _ENTRIES
