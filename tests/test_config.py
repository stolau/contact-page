"""LLM-COP-34 — the two data paths come from the environment.

The artifact was found when the server was started with `DATABASE=...
UPLOAD_DIR=... flask run` from a worktree and answered a blank, freshly
seeded site: the factory read no environment variable, so both names were
read by nobody and failed silently. Every test here is a thing that goes
red if that behaviour comes back, and the reproduction itself is the last
test in the file.

No spec on the server governs configuration — every contact-page spec is a
screen or component spec — so these tests cite the plan's steps rather than
inventing spec addresses.
"""

import logging
import os

import pytest

from app import create_app
from tests.conftest import edit_published_payload

# --- step 1: the environment names the paths, the defaults do not move -------


def test_database_from_the_environment_opens_that_file_and_nothing_beside(
    tmp_path, monkeypatch
):
    """The artifact's reviewer check, for DATABASE: the named file is what
    is opened, and no database appears in the instance directory."""
    named = tmp_path / "real.sqlite3"
    instance = tmp_path / "instance"
    monkeypatch.setenv("DATABASE", str(named))

    app = create_app(instance_path=str(instance))

    assert app.config["DATABASE"] == str(named)
    assert named.exists(), "the configured file was never opened"
    assert "site.sqlite3" not in os.listdir(instance)


def test_upload_dir_from_the_environment_is_where_uploads_live(
    tmp_path, monkeypatch
):
    """The same for UPLOAD_DIR: the named directory is created, and no
    uploads directory appears in the instance directory."""
    named = tmp_path / "real-uploads"
    instance = tmp_path / "instance"
    monkeypatch.setenv("UPLOAD_DIR", str(named))

    app = create_app(instance_path=str(instance))

    assert app.config["UPLOAD_DIR"] == str(named)
    assert named.is_dir()
    assert "uploads" not in os.listdir(instance)


def test_the_defaults_are_byte_identical_when_nothing_is_set(tmp_path):
    """The artifact's first hazard: a checkout with no environment set must
    behave exactly as it did. Compared as exact strings, not as paths, so
    the assertion states the shipped value rather than a normalised
    equivalent of it. It does not, and cannot, catch an abspath() on the
    default branch: instance_path is always absolute, so abspath is a no-op
    there."""
    instance = tmp_path / "instance"

    app = create_app(instance_path=str(instance))

    assert app.config["DATABASE"] == os.path.join(
        app.instance_path, "site.sqlite3"
    )
    assert app.config["UPLOAD_DIR"] == os.path.join(
        app.instance_path, "uploads"
    )


def test_an_exported_but_empty_variable_is_treated_as_unset(
    tmp_path, monkeypatch
):
    """`DATABASE=` is a shell accident, not a request for a database at the
    empty path: sqlite3.connect("") quietly opens a private on-disk
    temporary database, which is the blank-site symptom this artifact is
    about."""
    instance = tmp_path / "instance"
    monkeypatch.setenv("DATABASE", "")
    monkeypatch.setenv("UPLOAD_DIR", "")

    app = create_app(instance_path=str(instance))

    assert app.config["DATABASE"] == os.path.join(
        app.instance_path, "site.sqlite3"
    )
    assert app.config["UPLOAD_DIR"] == os.path.join(
        app.instance_path, "uploads"
    )


def test_a_relative_environment_path_is_resolved_to_an_absolute_one(
    tmp_path, monkeypatch
):
    """Every route opens its own connection, so a stored relative path
    would be re-resolved against whatever the process's working directory
    happens to be at that moment — and it is also the path the startup line
    prints. The chdir is what makes this test's claim real rather than
    incidental: the value is resolved against the cwd of create_app."""
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("DATABASE", "real.sqlite3")

    app = create_app(instance_path=str(tmp_path / "instance"))

    resolved = app.config["DATABASE"]
    assert os.path.isabs(resolved), resolved
    assert resolved == os.path.join(os.getcwd(), "real.sqlite3")
    assert os.path.exists(resolved)


# --- step 1b: an environment-named parent directory must already exist -------


def test_a_missing_database_parent_refuses_to_start_and_creates_nothing(
    tmp_path, monkeypatch
):
    """Recursive creation would make a mistyped value, or a persistent
    volume that failed to mount, look like a successful start with a
    freshly seeded empty site — the very failure this artifact exists to
    remove. So it refuses, and it says which variable, which path and which
    directory."""
    absent = tmp_path / "absent"
    named = absent / "site.sqlite3"
    monkeypatch.setenv("DATABASE", str(named))

    with pytest.raises(ValueError) as raised:
        create_app(instance_path=str(tmp_path / "instance"))

    message = str(raised.value)
    assert "DATABASE" in message
    assert str(named) in message
    assert str(absent) in message
    assert not absent.exists(), "the refusal created the tree anyway"


def test_a_missing_upload_dir_parent_refuses_to_start_the_same_way(
    tmp_path, monkeypatch
):
    """The symmetry is the point: UPLOAD_DIR gets a recursive makedirs for
    free from the pre-existing line further down, so without the check the
    two keys would behave differently for no reason a reader could
    predict."""
    absent = tmp_path / "absent"
    named = absent / "uploads"
    monkeypatch.setenv("UPLOAD_DIR", str(named))

    with pytest.raises(ValueError) as raised:
        create_app(instance_path=str(tmp_path / "instance"))

    message = str(raised.value)
    assert "UPLOAD_DIR" in message
    assert str(named) in message
    assert str(absent) in message
    assert not absent.exists(), "the refusal created the tree anyway"


def test_the_upload_dir_leaf_is_still_created_when_its_parent_exists(
    tmp_path, monkeypatch
):
    """The rule is about the directory the path sits in, not the path
    itself: UPLOAD_DIR=/srv/data/uploads requires /srv/data and creates
    `uploads` itself, exactly as it creates `uploads` under instance/
    today. Goes red if the check over-corrects into demanding the leaf."""
    parent = tmp_path / "exists"
    parent.mkdir()
    named = parent / "uploads"
    monkeypatch.setenv("UPLOAD_DIR", str(named))

    app = create_app(instance_path=str(tmp_path / "instance"))

    assert app.config["UPLOAD_DIR"] == str(named)
    assert named.is_dir()


def test_a_deep_instance_path_still_creates_the_whole_tree(tmp_path):
    """A defaults-did-not-move regression test, and only that.

    No existing test builds an app at an instance_path several levels below
    anything that exists, so this is worth having. It is NOT evidence that
    scoping the parent-directory check to the environment branch is
    load-bearing: os.makedirs(app.instance_path, exist_ok=True) is already
    recursive and both defaults sit inside app.instance_path, so a check
    applied universally would still pass here.
    """
    instance = tmp_path / "deep" / "nested" / "instance"

    app = create_app(instance_path=str(instance))

    assert (instance / "site.sqlite3").exists()
    assert (instance / "uploads").is_dir()
    assert app.config["DATABASE"] == str(instance / "site.sqlite3")


# --- step 2: the startup line, at a level an operator actually sees ----------
#
# Neither test below calls caplog.set_level(). That is not an oversight:
# the startup record is at WARNING, which caplog captures with no set_level
# at all, and set_level(DEBUG) would raise the root level and make the
# effective-level assertion below contradict itself.


def _startup_lines(caplog):
    """The startup records caplog saw, at WARNING or above."""
    return [
        record.getMessage()
        for record in caplog.records
        if record.levelno >= logging.WARNING
        and "data paths" in record.getMessage()
    ]


def test_the_startup_line_names_the_default_path_and_says_default(
    tmp_path, caplog
):
    """The cure for the misspelling trap that produced this artifact: an
    operator who typed DATBASE= sees `(default)` and a path inside the
    checkout, and knows in one line that their variable did not take. The
    path alone would require them to already know what to expect.

    The app is built inside the call phase on purpose — a record emitted
    during fixture setup does not reach caplog.records here.
    """
    app = create_app(instance_path=str(tmp_path / "instance"))

    lines = _startup_lines(caplog)
    assert lines, "no startup line at WARNING or above"
    # The path and the source word are pinned TOGETHER, as one substring, so
    # the assertion reads the pair an operator reads rather than two words
    # that happen to be somewhere in the line. This test cannot catch the two
    # source arguments being swapped in app.logger.warning: with nothing set
    # both sources are "default", so the swapped line is identical. The
    # environment case below is the one that catches that mutant.
    assert any(
        f"DATABASE={app.config['DATABASE']} (default)" in line
        for line in lines
    ), lines

    # The visibility claim itself, standing, on the app just built. INFO
    # was rejected because this logger — logging.getLogger("app"), from
    # Flask(__name__) — is at NOTSET and inherits WARNING from root, so an
    # INFO startup line is a line nobody ever sees. If a future Flask
    # starts configuring the app logger at INFO or DEBUG it does so on
    # getLogger(app.name), so this goes red and the level gets re-argued
    # rather than silently outliving its reason.
    assert app.logger.name == "app"
    assert app.logger.getEffectiveLevel() > logging.INFO


def test_the_startup_line_says_environment_when_the_variable_is_set(
    tmp_path, caplog, monkeypatch
):
    """The other half of the source word: the resolved path is named, and
    it is named as having come from the environment."""
    named = tmp_path / "real.sqlite3"
    monkeypatch.setenv("DATABASE", str(named))

    app = create_app(instance_path=str(tmp_path / "instance"))

    assert app.config["DATABASE"] == str(named)
    lines = _startup_lines(caplog)
    # Pinned as one substring: path and source word together. This is the
    # assertion that catches the two source arguments being swapped in
    # app.logger.warning — under that mutant it goes red reading
    # "DATABASE=<named> (default)". That mutant is this artifact's headline
    # failure restored: an operator told "(environment)" for a variable that
    # did not take.
    assert any(
        f"DATABASE={named} (environment)" in line for line in lines
    ), lines


# --- step 4: the reproduction that started the artifact ----------------------


def test_a_second_instance_directory_serves_the_configured_database(
    tmp_path, monkeypatch
):
    """The supervisor's reproduction, modelled in process.

    App A is the checkout that was already running; app B is the second
    worktree — a DIFFERENT instance directory — with the same DATABASE
    still exported. B must serve A's content, and B must not have seeded a
    database of its own: before this change B would have opened
    <b>/site.sqlite3, found it empty, filled it with placeholder content
    and served the blank site the artifact is named for.
    """
    shared = tmp_path / "shared.sqlite3"
    monkeypatch.setenv("DATABASE", str(shared))

    checkout = create_app(instance_path=str(tmp_path / "a"))
    edit_published_payload(
        checkout,
        "hero",
        lambda payload: payload.update(
            page_title="Jaetun tietokannan otsikko"
        ),
    )

    worktree = create_app(instance_path=str(tmp_path / "b"))
    response = worktree.test_client().get("/")

    assert response.status_code == 200
    assert (
        "<title>Jaetun tietokannan otsikko</title>"
        in response.get_data(as_text=True)
    )
    assert "site.sqlite3" not in os.listdir(tmp_path / "b")
