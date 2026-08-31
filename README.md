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

## Develop

```sh
.venv/bin/pip install -r requirements-dev.txt
.venv/bin/ruff check .
.venv/bin/pytest
```
