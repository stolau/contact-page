# Puheterapia Anna Virtanen — contact page

Single-page Flask + SQLite site. The page is rendered from the `sections`
table's published payloads; a fresh database is migrated and seeded with the
mockup content on first run.

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

The inner loop, without pytest in the way:

```sh
node --test tests/js/*.test.js
```
