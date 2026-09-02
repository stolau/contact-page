# This project is created as part of benchmarking and testing TDD tooling, agent analyzing. Procceed to use it with caution

# Contact page — a generic, admin-editable one-page site

Single-page Flask + SQLite site. The page is rendered from the `sections`
table's published payloads; a fresh database is migrated and seeded with
neutral placeholder content on first run. Every word on the page — including
the site name, the browser title and the footer — is the owner's to set from
the admin panel; the shipped seed names no person, place or register.

## Run

```sh
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/flask --app app run
```

Open http://127.0.0.1:5000/. The database is created at `instance/site.sqlite3`
on the first start.

## Admin account

The site has a single admin account, created and reset only from the server
command line (there is no email reset flow):

```sh
.venv/bin/flask --app app admin-create <username>   # prompts for the password
.venv/bin/flask --app app admin-reset-password      # prompts for a new one
```

Both commands open the database file directly through the app factory, so
they work whether or not the server is running. Sign in at `/yllapito`
(the Ylläpito link in the page footer).

## Contact messages

The page's Ota yhteyttä dialog posts to `/api/messages`; every message is
stored in the database and read at `/yllapito/viestit` (admin only), newest
first, where each one can be deleted.

A mail notification is sent only when both `SMTP_HOST` and `MAIL_TO` are
set — with `SMTP_HOST` set and `MAIL_TO` missing, nothing is sent and a
warning is logged. The message is always stored first, so a mail failure
never loses it.

| Variable | Meaning |
| --- | --- |
| `SMTP_HOST` | Mail server host. Unset means no notifications. |
| `SMTP_PORT` | Port, default `25`. |
| `SMTP_USER`, `SMTP_PASSWORD` | Optional; a login is attempted only when both are set. |
| `MAIL_TO` | Recipient. Unset means no notifications. |
| `MAIL_FROM` | Sender, defaults to `MAIL_TO`. |
| `TRUSTED_PROXY` | See below. |

Posting is rate limited to 5 messages per hour per client. The limiter
assumes the app is reached directly (as `flask --app app run` above serves
it) and keys on the client address; the windows live in the process, so a
restart clears them. Behind a reverse proxy, set `TRUSTED_PROXY` to any
non-empty value and the key becomes the rightmost `X-Forwarded-For` entry —
the one the proxy itself appended. Left unset, the header is ignored
entirely, so a forged `X-Forwarded-For` cannot win a fresh window.

## Uploaded images

The portrait is uploaded from the side panel's Vaihda button. The bytes are
validated structurally (PNG and JPEG only, no other format, no decoder and
no image dependency), stored under `instance/uploads/` named by the SHA-256
of the bytes we stored, and served from `/kuvat/<digest>`. The section
payload carries only that digest, so drafts and publishes stay small.

Four things about that storage are worth knowing before you rely on it:

- **`instance/` is gitignored and is not backed up, so uploads are lost on
  redeploy** — exactly as the database already is. Deletion below is
  therefore irreversible, and everything about it is built to fail towards
  keeping a file rather than losing one.
- **A picture leaves when nothing names it any more.** Every digest is
  counted across the `draft`, `published` *and* `previous_published`
  payloads of every section, and the row and the file go together the moment
  the count reaches zero. The counting happens inside the three writes that
  can drop a reference — a draft save, a Julkaise, a *Palauta edellinen
  versio* — and nowhere else: there is no timer and no sweep at startup.
  Because `previous_published` counts, a replaced picture survives exactly
  one more publish, which is the depth *Palauta edellinen versio* can reach;
  the publish past that collects it.
- **A freshly uploaded picture is held for fifteen minutes whatever the
  count says.** An upload lands before the save that names it, so without
  that floor an autosave firing in between would collect the picture the
  owner is placing. The clock runs from the last time `POST /api/kuvat`
  answered that digest, not from the first upload of those bytes — so
  re-uploading a picture restarts it.
- **Poista takes the picture off the page, and the file follows on the
  save** — once nothing else names the digest and the floor has passed. To
  remove one immediately, `DELETE /api/kuvat/<digest>` with an admin session
  deletes the row and the file at once, bypassing the floor; it answers
  `409` instead if a payload still names the digest. There is no panel
  button for it, because there is no screen listing stored uploads.

## Develop

```sh
.venv/bin/pip install -r requirements-dev.txt
.venv/bin/ruff check .
.venv/bin/pytest
```

`.venv/bin/pytest` is the whole gate. It runs the Python tests and, through
`tests/test_js_suite.py`, the JavaScript suite under `tests/js/` on Node's
built-in test runner — so a JavaScript failure fails pytest. The suite has no
third-party dependency and no `node_modules`; the modules under `app/static/`
are loaded into a `vm` sandbox straight from disk.

**Node 22.x must be on `PATH`.** 22.x specifically: the suite uses
`mock.timers`, which is experimental, and newer is the untested direction. The
runner also pins `--test-reporter=tap`, because Node 23 changed the default
reporter and the gate reads TAP counters. The gate resolves `node` from `PATH`
and **fails rather than skips** when it is absent — a skip would be false
assurance — so an nvm-only install that your login shell can see is not a gate
for a cron or container shell.

The same command also runs the browser suite under `tests/browser/`, which
drives the three client state machines — the first-run wizard, direct
in-place edit and the side panel — in real Google Chrome through Playwright,
against the real app on a real port with a fresh database per test.

**Google Chrome must be on `PATH`**, as `google-chrome` or
`google-chrome-stable`, or named by `$CONTACT_PAGE_CHROME` (which wins when
set, and fails rather than falling back when it points at nothing runnable).
`playwright install` is **not** part of setup: the bundled Chromium is a
separate ~150 MB download this suite never launches, because the fixtures pass
an explicit `executable_path`. Like the Node half, the browser half **fails
rather than skips** when the package or the browser is absent — a skip would
be false assurance — so `pip install -r requirements-dev.txt` plus a system
Chrome is the whole story.

The inner loops, without the rest of the gate in the way:

```sh
node --test tests/js/*.test.js
.venv/bin/pytest tests/browser/
```
