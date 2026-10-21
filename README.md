# Mini DLP

A small Data Loss Prevention service: administrators define Data Types (keyword
detectors with a match threshold) and group them into Data Sets, then scan text
against a Data Set to find which Data Types it contains. Built with FastAPI,
SQLAlchemy 2.0, Alembic and PostgreSQL.

## At a glance

- One command to run: `docker compose up --build -d --wait`.
- 6 paths, 12 operations, all documented at `/docs`.
- 240 automated tests (170 unit, 70 integration against real PostgreSQL), runnable with Docker only.
- Scan text limit: 1,000,000 characters.
- A Postman collection with 29 requests and 48 assertions that cleans up after itself.

## Run

Prerequisites: Docker, running, with Compose v2 (`docker compose`; Docker Desktop includes it).
Nothing else needs to be installed. Ports 8000 and 5433 must be free (see below to change them).
With the older standalone binary, use `docker-compose up --build -d` instead.

```sh
docker compose up --build -d --wait
```

Then open http://localhost:8000/docs.

The database is published on `127.0.0.1:5433` and the app on port `8000`. If either port is
taken, copy `.env.example` to `.env` and set `DB_HOST_PORT` (and the port in its two URLs) or
`APP_HOST_PORT`. `docker compose down -v` removes the stack and its data.

## API

| Path | Methods | Purpose |
|------|---------|---------|
| `/health` | GET | Health check, including the database |
| `/api/datatypes` | GET, POST | List or create Data Types |
| `/api/datatypes/{id}` | GET, PUT, DELETE | Read, replace or delete one Data Type |
| `/api/datasets` | GET, POST | List or create Data Sets |
| `/api/datasets/{id}` | GET, PUT, DELETE | Read, replace or delete one Data Set |
| `/api/scan` | POST | Scan text against a Data Set |

- Matching is case-insensitive; a match never starts or ends inside a word. `match_count` is the
  total number of non-overlapping keyword occurrences in the text; a Data Type is detected when
  `match_count >= threshold`.
- `detected_objects` lists only detected Data Types, ordered by `match_count` descending.
- Scan request: `{"text": "...", "data_set_id": "<uuid>"}`. Response: either
  `{"status": "match", "detected_objects": [{"id", "name", "match_count"}]}` or
  `{"status": "not matched"}`.
- Unknown `data_set_id` returns 404. Text longer than 1,000,000 characters returns 413 (fixed for
  the compose stack). Empty text, or a Data Set with no Data Types, returns `not matched`.
- Deleting a Data Type that a Data Set references returns 409; detach it first.
- `PUT` replaces the whole resource. Names are unique ignoring case; a duplicate returns 409.
- Every error uses one envelope: `{"error": {"code", "message", "details"}}`.

## Tests

```sh
docker compose --profile test run --build --rm tests
```

This needs Docker only. With uv installed on the host: `make test`.

## Postman

Import `postman/mini-dlp.postman_collection.json` into Postman. If the stack is not on
`localhost:8000`, set the collection variable `base_url`. Run the collection
**in order**; it creates, scans and deletes its own data and can be run repeatedly.
Optional, with Node installed: `make postman`.

## Limitations

- The scan runs inside the request, so a very large text blocks the process for the scan's
  duration.
- No authentication.
- No pagination.
- Keywords match exact word forms: `passwords`, `DB_PASSWORD`, `apiKey` and `internal-only` need
  their own keywords; a keyword inside running Chinese, Japanese or Thai text (no spaces) misses.
- A keyword made only of punctuation (`+`, `--`) matches anywhere; number keywords match inside
  punctuated numbers (`100` in `100,000`).
- `match_count` counts every occurrence, so a repeated confidentiality footer can reach a
  threshold that one sensitive value does not: the threshold is the false-positive control.
- Matching is accent-sensitive (`resume` does not match `résumé`); ligatures and full-width letters
  are folded (NFKC), soft hyphens and zero-width spaces are ignored.
