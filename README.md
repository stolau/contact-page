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

## Develop

```sh
.venv/bin/pip install -r requirements-dev.txt
.venv/bin/ruff check .
.venv/bin/pytest
```
