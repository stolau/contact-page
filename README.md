> This project was created as part of benchmarking and testing TDD tooling and
> agent analysis. Treat it accordingly before putting anything real behind it —
> in particular, read **Before you expose this to the internet** below.

# Contact page — a generic, admin-editable one-page site

A single-page Flask + SQLite site. The public page is rendered from the
`sections` table's published payloads; a fresh database is migrated and seeded
with neutral placeholder content on first run. Every word on the page — the
site name, the browser title, the section headings, the footer — is the
owner's to set from the admin panel. The shipped seed names no person, place
or register.

Two visual styles ship with it (`Perus` and `Kuvallinen`), switchable from the
admin panel without touching content, and the owner picks a main and a
secondary colour.

## What you need

| | |
| --- | --- |
| **Python** | 3.12 (what CI runs). Anything 3.11+ is likely fine; only 3.12 is tested. |
| **Disk** | A few MB, plus whatever uploaded images come to. |
| **To run the app** | Nothing but Python and `requirements.txt` (one package: Flask). |
| **To run the test suite** | Additionally Node 22.x and a system Google Chrome — see [Develop](#develop). |

No database server, no Redis, no build step, no `node_modules`. SQLite is a
file, and the front end is hand-written CSS and plain JavaScript served as-is.

## Run it locally

```sh
git clone <this repository> contact-page
cd contact-page
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/flask --app app run
```

Open <http://127.0.0.1:5000/>. On first start the app creates
`instance/site.sqlite3`, applies every migration and seeds placeholder
content, so the page renders immediately with nothing configured.

### First run: claim the site

The seeded site has **no admin account**, and there is no sign-up page — an
account is created only from the command line, which is what keeps a freshly
deployed site from being claimed by whoever finds it first.

```sh
.venv/bin/flask --app app admin-create <username>    # prompts for a password
```

Then open `/yllapito` (the *Ylläpito* link in the page footer) and sign in.
Because nothing has been published yet, you land on the first-run wizard at
`/yllapito/alustus`, which walks through the basics; afterwards you can edit
from any of three modes:

| Route | What it is |
| --- | --- |
| `/muokkaa` | Side panel: one section at a time, every field, with live preview. |
| `/muokkaa/sivu` | Direct edit: click text on the page and type. |
| `/muokkaa/osiot` | Section list: reorder, publish state, add and remove sections. |
| `/yllapito/viestit` | The contact inbox, newest first. |

Changes are saved as a **draft** and go public only when you press *Julkaise*.
*Palauta edellinen versio* steps back exactly one publish.

## Configuration

Two environment variables say where this site's data lives. With neither set,
a checkout behaves exactly as it always has — the defaults below are what
`flask --app app run` has always used, so nothing needs to be set to run
locally.

| Variable | Meaning |
| --- | --- |
| `DATABASE` | The SQLite file to open. Default `instance/site.sqlite3` inside the checkout. |
| `UPLOAD_DIR` | Where uploaded images are written. Default `instance/uploads/`. |

Both are read once, when the app is built, and a relative value is resolved
against the working directory at that moment. The resolved pair is logged as a
warning at startup, each path followed by `(environment)` or `(default)`, so a
misspelled variable name shows up in the log as a path inside the checkout
instead of failing silently.

**The directory a configured path sits in must already exist; the app will not
create it for you.** `DATABASE=/srv/contact-page/site.sqlite3` needs
`/srv/contact-page` to be there, and the app refuses to start — naming the
variable, the path and the missing directory — if it is not. `UPLOAD_DIR`
likewise needs its parent, and creates the leaf itself. That is deliberate:
creating the tree instead would make a mistyped path, or a persistent volume
that failed to mount, look like a successful start serving a freshly seeded
empty site.

**This is how data survives a redeploy:** point both at a directory outside
the checkout. `instance/` is gitignored and is not backed up.

The mail and proxy settings (`SMTP_*`, `MAIL_*`, `TRUSTED_PROXY`) are read per
request rather than at startup, and are documented under
[Contact messages](#contact-messages).

## Secrets, and what this app logs

**No secret is ever written to `app.config`, and nothing sensitive is
logged.** The application emits exactly three log lines of its own:

- the two resolved data paths at startup, with where each came from;
- a warning when `SMTP_HOST` is set but `MAIL_TO` is not — deliberately
  field-free, because the operator needs the misconfiguration, not the
  visitor's message;
- a warning that a mail notification failed, carrying **the message id only**,
  never the message or the sender.

Passwords are never logged, and are stored only as hashes. Session tokens are
stored only as a SHA-256 of the token, so a copy of the database yields no
usable session.

Keep it that way when you deploy:

- **Never commit secrets.** Nothing in this repository holds one, and no
  credential has a default in code. `instance/` is gitignored; keep it that
  way.
- **Keep secrets out of shell history.** `SMTP_PASSWORD=… flask run` on a
  command line lands in `~/.bash_history` and in the process list where any
  local user can read it with `ps`. Put them in a file readable only by the
  service user (an `EnvironmentFile=`, or your platform's secret store) and
  reference it.
- The admin password and the two-step secret are typed at an interactive
  prompt, never passed as arguments, for the same reason.

## Running it on a server over SSH

Nothing here is specific to a provider. The examples use placeholders —
`example.com`, `/srv/contact-page`, `contactpage` — substitute your own.

### 1. Get the code and its dependencies onto the server

```sh
ssh you@example.com
sudo adduser --system --group --home /srv/contact-page contactpage
sudo -u contactpage -H bash
cd /srv/contact-page
git clone <this repository> app
cd app
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
```

Running as a dedicated unprivileged user matters more than usual here: the
SQLite file is the entire site, including password hashes and any two-step
secret, and file permissions are the only thing protecting it.

### 2. Put the data outside the checkout

```sh
mkdir -p /srv/contact-page/data
```

Then set `DATABASE=/srv/contact-page/data/site.sqlite3` and
`UPLOAD_DIR=/srv/contact-page/data/uploads`. A `git pull` in the checkout now
cannot touch the site's content, and the startup log will confirm both paths
came from `(environment)`.

### 3. Do not serve it with the development server

`flask run` prints a warning about this and means it: it is single-process,
has no request queueing, and is not written to face the internet.

**No production server is bundled**, deliberately — `requirements.txt` is one
package, and picking a WSGI server is a deployment decision, not this app's.
Install one alongside, for example:

```sh
.venv/bin/pip install gunicorn
.venv/bin/gunicorn --workers 3 --bind 127.0.0.1:8000 "app:create_app()"
```

**Bind to `127.0.0.1`, not `0.0.0.0`.** The app should be reachable only
through a reverse proxy that terminates TLS — see below.

One caveat if you run more than one worker: the **contact form's** rate-limit
windows live in process memory, so each worker keeps its own and the effective
limit is multiplied by the worker count. The **admin login's** limiter does
not have this problem — it lives in the database and is shared.

### 4. Terminate TLS in front of it

Put a reverse proxy in front (nginx, Caddy, or whatever you already run),
terminate HTTPS there with a certificate from your CA of choice, and forward
to `127.0.0.1:8000`. Then set `TRUSTED_PROXY=1` so both rate limiters key on
the rightmost `X-Forwarded-For` entry rather than on the proxy's own address —
without it, behind a proxy, every visitor shares one window.

### 5. Keep it running

A minimal systemd unit — adjust paths, and put the environment in a file the
service user alone can read:

```ini
[Unit]
Description=Contact page
After=network.target

[Service]
User=contactpage
Group=contactpage
WorkingDirectory=/srv/contact-page/app
EnvironmentFile=/srv/contact-page/contact-page.env
ExecStart=/srv/contact-page/app/.venv/bin/gunicorn \
    --workers 3 --bind 127.0.0.1:8000 "app:create_app()"
Restart=on-failure

# Hardening worth having for a service that owns one SQLite file.
NoNewPrivileges=yes
PrivateTmp=yes
ProtectSystem=strict
ReadWritePaths=/srv/contact-page/data

[Install]
WantedBy=multi-user.target
```

`/srv/contact-page/contact-page.env` holds `DATABASE=…`, `UPLOAD_DIR=…`,
`TRUSTED_PROXY=1` and any `SMTP_*` values — `chmod 600`, owned by the service
user. It is not in the repository and must never be.

### 6. Create the admin account on the server

```sh
sudo -u contactpage /srv/contact-page/app/.venv/bin/flask --app app admin-create <username>
```

Run it from the checkout directory with the same environment as the service —
otherwise it opens the *default* database inside the checkout and creates an
account on a site nobody is serving. Confirm the startup log's `(environment)`
lines if you are unsure which file is live.

### 7. Upgrading

```sh
sudo -u contactpage git -C /srv/contact-page/app pull
sudo -u contactpage /srv/contact-page/app/.venv/bin/pip install -r requirements.txt
sudo systemctl restart contact-page
```

**Migrations run automatically at startup** and are one-way — there is no
downgrade path. Back up the database file first; it is a single file, so
`cp site.sqlite3 site.sqlite3.bak` while the service is stopped is a complete
backup. Uploaded images live beside it in `uploads/` and are equally worth
copying.

## Before you expose this to the internet

Stated plainly, because a deployment guide that hides its gaps is worse than
none:

- **The session cookie is never marked `Secure`.** It is `HttpOnly` and
  `SameSite=Lax`, but the `Secure` flag is not set anywhere in the code, so
  the browser will send it over plain HTTP if it ever gets the chance.
  Terminating TLS is necessary but does not by itself set that flag.
- **There are no security headers on HTML responses** — no
  `Content-Security-Policy`, no `X-Frame-Options`, no
  `X-Content-Type-Options`. Your reverse proxy is the practical place to add
  them today. (Uploaded images *are* served with a strict CSP.)
- **Contact messages are personal data, stored in plain text, kept forever.**
  There is a per-message delete in the inbox and nothing else: no retention
  period, no bulk erasure, no export. If real people will use the form,
  that is your obligation to meet.
- **The privacy statement shipped with the app is placeholder text** and says
  so on the page. Replace it before publishing.
- **Two-step sign-in is off by default** and is worth turning on once TLS is
  in place — see below.

None of these is exotic; all are known and none is hidden in the code.

## Admin account

The site has a single admin account, created and reset only from the server
command line (there is no email reset flow):

```sh
.venv/bin/flask --app app admin-create <username>   # prompts for the password
.venv/bin/flask --app app admin-reset-password      # prompts for a new one
.venv/bin/flask --app app login-unlock              # clears every login lockout
.venv/bin/flask --app app admin-totp-enable         # turns on two-step sign-in
.venv/bin/flask --app app admin-totp-disable        # turns it back off
```

Every command above opens the database file directly through the app
factory, so they work whether or not the server is running. Sign in at
`/yllapito` (the Ylläpito link in the page footer).

Failed sign-ins are limited (see Contact messages below for the client key).
A successful sign-in clears the counter only while you are still under the
limit; once the limit is reached, attempts are refused before the password is
looked at, so a correct password will not let you in — wait for the window to
pass, or run `flask --app app login-unlock` on the server.

### Two-step sign-in

Off by default; nothing changes until you turn it on. `admin-totp-enable`
prints a secret and an `otpauth://` URI for an authenticator app, then asks
for one code and **refuses to enable anything unless that code verifies** —
so an account can never end up holding a secret it cannot prove. It then
prints ten recovery codes **once**; they are stored only as hashes and
cannot be shown again, so write them down there and then. Each is good for
a single sign-in. With the factor on, the password step hands you a second
dialog asking for the six-digit code (or one recovery code), and no session
exists until that step passes. `admin-totp-disable` is the way back in when
the authenticator is lost — it clears the secret and the recovery codes and
returns the account to a one-step sign-in.

Two things this does not do, stated plainly. **The secret is a bearer
credential at rest.** It sits in `instance/site.sqlite3` beside the password
hash, and anyone holding a copy of that file can generate valid codes — the
mitigation is file permissions and backup discipline, not anything in this
application. **And over plain HTTP it buys nothing against an
eavesdropper**: they do not need your code, they take the session cookie
minted a moment after it. What it does buy is real — a stolen, guessed or
reused password is no longer enough on its own. TLS remains the
prerequisite for the rest.

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
| `TRUSTED_PROXY` | See below. Governs both rate limiters. |

Posting is rate limited to 5 messages per hour per client. The limiter
assumes the app is reached directly (as `flask --app app run` above serves
it) and keys on the client address; the windows live in the process, so a
restart clears them. Behind a reverse proxy, set `TRUSTED_PROXY` to any
non-empty value and the key becomes the rightmost `X-Forwarded-For` entry —
the one the proxy itself appended. Left unset, the header is ignored
entirely, so a forged `X-Forwarded-For` cannot win a fresh window.

`TRUSTED_PROXY` decides the same key for the admin login, where failed
sign-ins are limited to 5 per 15 minutes per client. Unlike the contact
form's, that counter lives in the database, so it survives a restart and is
shared by every worker or thread. A throttled attempt is answered exactly
like a wrong password, on purpose: the response never says whether it was
refused, and never says whether the username exists. Set `TRUSTED_PROXY`
when you run behind a proxy — with it unset behind one, every request keys
on the proxy's own address and the whole internet shares one window.

## Uploaded images

The portrait is uploaded from the side panel's Vaihda button. The bytes are
validated structurally (PNG and JPEG only, no other format, no decoder and
no image dependency), stored under `instance/uploads/` named by the SHA-256
of the bytes we stored, and served from `/kuvat/<digest>`. The section
payload carries only that digest, so drafts and publishes stay small.

Four things about that storage are worth knowing before you rely on it:

- **`instance/` is gitignored and is not backed up, so uploads are lost on
  redeploy** — exactly as the database already is. That is true of the
  default location only: set `UPLOAD_DIR` (and `DATABASE`) to a persistent
  volume outside the checkout and both survive, which is what Configuration
  above is for. Wherever they live, deletion below is therefore
  irreversible, and everything about it is built to fail towards keeping a
  file rather than losing one.
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

`.venv/bin/pytest` with no arguments remains the whole gate and will stay
that way. What the `browser` marker adds is a way to *leave tests out
deliberately for a minute*, not a new default: `.venv/bin/pytest -m "not
browser"` is the fast local loop, and it drops 89 tests — including the three
preconditions in `tests/browser/test_browser_gate.py` that assert Playwright
is installed and Chrome is resolvable. A green fast loop is therefore a
weaker claim than a green gate, and it is the gate that decides.

Nothing marks those tests by hand. `tests/browser/conftest.py`'s
`pytest_collection_modifyitems` marks every item whose path lies under that
directory, subdirectories included, so a new file under `tests/browser/`
needs no `pytestmark` line added to it and cannot be forgotten out of the
marker. The cost is that opening one of those files shows no marker; the
mechanism is named in `pytest.ini`'s marker description and in
`tests/test_browser_marker.py`, which fails if the marker and the directory
ever stop meaning the same set.

CI runs that same argument-free `pytest` — the whole gate, browser layer
included — on every pull request and every push to `main`
(`.github/workflows/ci.yml`). It also runs `ruff check .` and, in an isolated
venv of its own, `pip-audit` against `requirements.txt`. On a CI host
`tests/test_browser_marker.py` additionally fails when any module file under
`tests/browser/` contributed nothing to the run, so a workflow that quietly
grew an `-m "not browser"` is a red test rather than a green run nobody
reads: the fast loop cannot become the only loop by accident. `playwright
install` is not part of CI either, for the same reason it is not part of
setup — the runner's own Google Chrome is what `executable_path` resolves to.

The inner loops, without the rest of the gate in the way:

```sh
node --test tests/js/*.test.js
.venv/bin/pytest tests/browser/
```
