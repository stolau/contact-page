"""LLM-COP-38 — app/passwords.py, against the REAL shipped deny-list.

Nothing here is stubbed and no fixture list is planted. Every assertion runs
against app/breached_passwords.txt exactly as it ships, which is what makes
"aaaaaaaaaaaa is refused" a fact about the data the product carries rather
than about a file this module wrote to make itself pass.

The two rules are proved to be INDEPENDENT rather than merely both present:
a twelve-character password that clears the length rule and is refused by the
list, and a twenty-five-character passphrase that clears it by a wide margin
and is refused by the list. Either control alone admits one of the two.
"""

import hashlib
import importlib
from pathlib import Path

from app import passwords

# The shipped file, located the way the module locates it rather than by a
# path spelled out again here — a test that found a different file than the
# loader does would prove nothing about what the loader reads.
LIST_PATH = Path(passwords.__file__).with_name("breached_passwords.txt")
SOURCE_PATH = Path(passwords.__file__).with_name(
    "breached_passwords.SOURCE.txt"
)

# The generated list's SHA-256, from the provenance record. See
# test_the_shipped_list_is_the_pinned_corpus for what may move it.
PINNED_SHA256 = (
    "6dcf84012a96d852a4eba1811d788f6a9aeb1c8a62861b6de2ce048536150566"
)
PINNED_LINES = 29954
PINNED_BYTES = 426955


def entries():
    """The file's lines, read here rather than through the module's cache."""
    return LIST_PATH.read_text(encoding="utf-8").splitlines()


# --- the two rules, and their independence -----------------------------------


def test_a_password_below_the_minimum_is_refused_and_the_reason_names_12():
    """Eleven characters: refused, and told how long it has to be.

    The message is read by an owner at their own terminal with no way to look
    the rule up, so it has to carry the number. Asserted as the number
    MIN_LENGTH actually is, so the rule and its message cannot drift apart.
    """
    reason = passwords.refusal("a" * 11)
    assert reason is not None
    assert str(passwords.MIN_LENGTH) in reason


def test_a_real_passphrase_is_accepted():
    """The suite's own admin password passes, which is why every existing
    CLI test still means what it meant."""
    assert passwords.refusal("oikea salasana 123") is None
    assert passwords.refusal("uusi salasana 456") is None


def test_twelve_characters_is_not_enough_because_the_list_is_a_second_rule():
    """THE test of this module: the two controls are independent.

    "aaaaaaaaaaaa" is exactly MIN_LENGTH characters, so the length rule
    admits it — and the deny-list refuses it anyway. Delete the list lookup
    and this goes red while every other length assertion stays green, which
    is the only shape of test that can tell "two rules" from "one rule with
    two error messages".
    """
    assert len("aaaaaaaaaaaa") == passwords.MIN_LENGTH
    reason = passwords.refusal("aaaaaaaaaaaa")
    assert reason is not None
    # And it is refused for the RIGHT reason: not the length message.
    assert str(passwords.MIN_LENGTH) not in reason


def test_a_long_famous_passphrase_is_refused():
    """Twenty-five characters, and one of the most-typed passphrases alive.

    The length rule alone admits it by thirteen characters. This is the case
    that makes a length-only policy insufficient rather than merely weak.
    """
    assert len("correcthorsebatterystaple") > passwords.MIN_LENGTH
    assert passwords.refusal("correcthorsebatterystaple") is not None


def test_the_lookup_is_case_folded():
    """"Password1234" is not meaningfully harder to crack than
    "password1234", and the file holds only the folded form — so the fold has
    to happen on the lookup side or the capital would walk straight past it.
    """
    assert "Password1234" not in entries()  # only the folded form is stored
    assert passwords.refusal("Password1234") is not None
    assert passwords.refusal("password1234") is not None
    # The Finnish case, because casefold() and lower() differ outside ASCII
    # and the file was built with casefold(). SALASANA1234's fold is in the
    # list; a lower()-only lookup would still catch this one, so it is a
    # sanity check on the direction of the fold rather than a fold-vs-lower
    # discriminator — that discrimination is a property of the FILE, asserted
    # in test_every_entry_equals_its_own_casefold below.
    assert passwords.refusal("SALASANA1234") is not None


def test_a_refusal_message_is_a_sentence_not_a_code():
    """Both messages are shown verbatim by click.ClickException, so they have
    to read as instructions to a person standing at a terminal."""
    for password in ("a" * 11, "aaaaaaaaaaaa"):
        reason = passwords.refusal(password)
        assert reason and reason == reason.strip()
        assert " " in reason


# --- the file's shape --------------------------------------------------------


def test_every_entry_is_at_least_the_minimum_length():
    """A shorter entry is dead weight: the length rule refuses everything
    below MIN_LENGTH before the list is ever consulted, so a shorter line
    could never be reached. Its presence would mean the build filter did not
    run."""
    short = [e for e in entries() if len(e) < passwords.MIN_LENGTH]
    assert short == []


def test_every_entry_equals_its_own_casefold():
    """The fold the file was built with must be the fold the lookup uses, or
    an entry is unreachable. This is the file half of that symmetry; the
    lookup half is test_the_lookup_is_case_folded above."""
    unfolded = [e for e in entries() if e != e.casefold()]
    assert unfolded == []


def test_no_entry_carries_surrounding_whitespace():
    """Nothing is stripped when the file is built, and nothing is stripped
    from the typed password either — so an entry that arrived with a stray
    space would be an entry nobody could ever match, and would invite someone
    to "fix" it by stripping the submitted password instead."""
    padded = [e for e in entries() if e != e.strip()]
    assert padded == []


def test_the_file_has_no_carriage_returns():
    """LF only. A CRLF checkout would append \\r to every entry, making the
    whole list unmatchable while every lookup still silently returned None —
    the quietest possible failure. .gitattributes pins this; the assertion is
    what proves the pin works."""
    assert b"\r" not in LIST_PATH.read_bytes()


def test_the_list_holds_no_duplicates():
    lines = entries()
    assert len(lines) == len(set(lines))


def test_the_list_is_not_truncated():
    """THE ANTI-VACUITY GUARD. Every assertion above is also true of an empty
    file, and a deny-list that refuses nothing passes all of them in silence.
    A thousand is far below the real count and far above any plausible
    accident, so this fails on a truncation without being a second copy of
    the pinned line count."""
    assert len(entries()) >= 1000


def test_the_loaded_set_is_the_whole_file():
    """The loader filters NOTHING — no comment prefix, no blank-line skip —
    and the file carries no header, which is what makes that safe. A filter
    on a deny-list is silently lossy the day a breached password begins with
    "#"."""
    assert passwords._entries() == frozenset(entries())
    assert len(passwords._entries()) == len(entries())


# --- the provenance tripwire -------------------------------------------------


def test_the_shipped_list_is_the_pinned_corpus():
    """A literal that exists to go red and be MOVED, never silenced.

    The same shape as tests/test_db.py's migration-head test. It turns
    "reproducible from a pinned SecLists commit" from a sentence in a comment
    into a claim the gate checks on every run.

    RED LEGITIMATELY: somebody deliberately regenerates the list — a newer
    SecLists commit, a changed MIN_LENGTH, a different filter. That is a real
    change to what the product refuses, and the answer is to update this hash
    AND the generated-SHA-256 row in app/breached_passwords.SOURCE.txt, in
    the same commit, so the file and the record never disagree. The last
    assertion below is what makes forgetting the second half impossible.

    ALSO UPDATE, and nothing here can check it for you: the line count, the
    byte count, the zlib figure and the mojibake tally in that same SOURCE
    file — 21 lines above U+007F, 358 characters, 818 bytes, 27 code points,
    3 lines with a control character. Those four mojibake figures are the
    only numbers in the record no test pins, which is precisely why they are
    the ones that will go stale. They were wrong once already, in the commit
    that introduced them, and a wrong number in a paragraph whose whole job
    is to stop a reader concluding the file is corrupt does the opposite of
    its job.

    RED ILLEGITIMATELY, and these must be fixed rather than re-pinned: a
    checkout that rewrote LF to CRLF (.gitattributes pins the file -text
    precisely so this cannot happen, and test_the_file_has_no_carriage_returns
    names it directly), an editor that stripped or added a trailing newline,
    or a stray hand edit to a data file nobody should ever edit by hand. In
    every one of those the DATA is unchanged and only its bytes moved, so
    re-pinning would be recording the damage as the new truth.
    """
    body = LIST_PATH.read_bytes()
    assert hashlib.sha256(body).hexdigest() == PINNED_SHA256
    # Stated two more ways, so a failure says WHICH kind of drift happened
    # instead of only that two hex strings differ.
    assert len(body) == PINNED_BYTES
    assert len(entries()) == PINNED_LINES
    # And the record agrees with the file. Regenerate the data and forget the
    # provenance file, and this is the assertion that says so.
    assert PINNED_SHA256 in SOURCE_PATH.read_text(encoding="utf-8")


def test_the_provenance_record_reproduces_the_upstream_licence():
    """SecLists is MIT, and MIT requires the copyright line and the permission
    notice to travel with a redistribution — naming "MIT" is not compliance.
    The notice lives in the sibling file rather than in a header, because a
    header would force the loader to filter and a filter on a deny-list is
    lossy."""
    record = SOURCE_PATH.read_text(encoding="utf-8")
    assert "Copyright (c) 2018 Daniel Miessler" in record
    assert "Permission is hereby granted, free of charge" in record
    assert 'THE SOFTWARE IS PROVIDED "AS IS"' in record
    # The data file itself carries none of it: no header at all is what lets
    # sha256sum of the file equal the pipeline's output exactly.
    assert "Copyright" not in LIST_PATH.read_text(encoding="utf-8")


# --- the list is read on first use, never at import --------------------------


def test_the_list_is_read_on_first_use_and_not_at_import():
    """Both directions, and ORDER-INDEPENDENT.

    The cache is module-level and lives for the whole pytest session, and
    tests/test_auth.py sorts before this file and calls refusal() through the
    CLI — so "assert the cache is unset" at import time would pass or fail on
    what ran earlier, not on what the module does. importlib.reload puts the
    module back to its just-imported state in place (same module object, so
    app/__init__.py's `from . import passwords` keeps working), which makes
    the question answerable no matter what ran before.

    Both directions are asserted, so the test is falsifiable in the way it
    claims: move the read to module scope and the first assertion fails;
    delete the cache and the last one does.
    """
    importlib.reload(passwords)
    assert passwords._ENTRIES is None  # import alone read nothing

    assert passwords.refusal("oikea salasana 123") is None

    assert passwords._ENTRIES is not None  # the first call did read it
    assert len(passwords._ENTRIES) == PINNED_LINES


def test_a_reloaded_module_still_refuses_what_it_refused_before():
    """The reload above is a real reload, not a no-op that would make the
    laziness test vacuous: after it, the module has to work."""
    importlib.reload(passwords)
    assert passwords.refusal("aaaaaaaaaaaa") is not None
    assert passwords.refusal("a" * 11) is not None
    assert passwords.refusal("oikea salasana 123") is None
