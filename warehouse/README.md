# Warehouse: PostgreSQL + dbt for the trailer study

Turns the study CSVs into tested, analysis-ready tables for the Power BI dashboard.

```
study/data/*.csv ──► PostgreSQL (Docker) raw schema ──► dbt staging views ──► dbt marts tables ──► Power BI
                     all text, untouched              typed + cleaned        fail rates, incidents
```

## Models

| Layer | Model | One row per | What it adds |
|---|---|---|---|
| staging | `stg_games` | game | types, price band, release era, review score |
| staging | `stg_trailers` | trailer | types, main-trailer flag |
| staging | `stg_scans` | trailer | latest successful scan only (retries de-duplicated), overall peak |
| staging | `stg_incidents` | flagged section | types, stable id |
| marts | `fct_trailer_scans` | scanned trailer | joined to its game; `is_flagged` (> 3 flashes/sec, WCAG) and `is_clear_fail` (4+/sec, sensitivity check) |
| marts | `fct_incidents` | flagged section | where it falls in the trailer (0-100%, deciles) |
| marts | `agg_fail_rates` | dimension × segment | flagged and clear-fail rates by genre, price, release era, popularity, frame rate, each with a 95% Wilson interval |
| marts | `agg_incident_timing` | tenth of a trailer | how many flagged sections start there |

`dbt build` also runs 30 data tests: unique / not-null keys, allowed values, every scan joins to a game, the clear-fail line is always stricter than the flagged line, and dbt's flag agrees with FlashGuard's own verdict for every trailer.

Thresholds live in `dbt/dbt_project.yml` (`flag_threshold`, `clear_fail_threshold`).

## Running it (Windows, PowerShell)

Needs Docker Desktop running.

```powershell
cd warehouse
docker compose up -d                         # starts Postgres and loads the CSVs on first start
pip install -r requirements.txt              # dbt
cd dbt
dbt build --profiles-dir .                   # builds all models and runs the tests
```

To reload after re-running the study:

```powershell
docker compose exec db psql -U flashguard -d flashguard -f /docker-entrypoint-initdb.d/01_load_raw.sql
```

then `dbt build --profiles-dir .` again.

## Connecting Power BI

Get Data → PostgreSQL database → Server `localhost:5433`, Database `flashguard` → Database credentials, user `flashguard`, password `flashguard`. If it says it can't connect with encryption, choose to connect without it (the local container has no SSL). Load the four tables from the `marts` schema.

Credentials are local-only demo values for a container on your own machine.
