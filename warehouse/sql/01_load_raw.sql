-- Load the study CSVs into the raw schema, exactly as they are.
-- Every column is text on purpose: raw = untouched copy of the source,
-- and all type casting / cleaning happens in dbt (models/staging).
--
-- Runs automatically the first time the container starts.
-- To reload after re-running the study:
--   docker compose exec db psql -U flashguard -d flashguard -f /docker-entrypoint-initdb.d/01_load_raw.sql

create schema if not exists raw;

drop table if exists raw.games;
create table raw.games (
    appid text, name text, sampled_genre text, genres text, is_free text, price_usd text,
    release_date text, coming_soon text, developers text, publishers text, metacritic text,
    required_age text, owners_estimate text, positive_reviews text, negative_reviews text,
    n_trailers text
);

drop table if exists raw.trailers;
create table raw.trailers (
    movie_id text, appid text, trailer_name text, position text, is_main text, url text
);

drop table if exists raw.scans;
create table raw.scans (
    movie_id text, appid text, status text, error text, verdict text, duration_sec text,
    fps text, width text, height text, peak_general_fps text, peak_red_fps text,
    n_incidents text, n_general_incidents text, n_red_incidents text, first_incident_sec text,
    failing_seconds text, share_frames_failing text, scanned_at text
);

drop table if exists raw.incidents;
create table raw.incidents (
    movie_id text, appid text, kind text, start_sec text, end_sec text, duration_sec text,
    peak_flashes_per_sec text
);

copy raw.games     from '/data/games.csv'     with (format csv, header true, encoding 'UTF8');
copy raw.trailers  from '/data/trailers.csv'  with (format csv, header true, encoding 'UTF8');
copy raw.scans     from '/data/scans.csv'     with (format csv, header true, encoding 'UTF8');
copy raw.incidents from '/data/incidents.csv' with (format csv, header true, encoding 'UTF8');

-- quick receipt so you can see it worked
select 'games' as table_name, count(*) as row_count from raw.games
union all select 'trailers', count(*) from raw.trailers
union all select 'scans', count(*) from raw.scans
union all select 'incidents', count(*) from raw.incidents;
