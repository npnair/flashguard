-- One row per successfully scanned trailer.
-- scan_trailers.py appends a row per attempt, so a trailer that failed to download
-- and was retried has several rows: keep the latest successful one.

with src as (
    select
        movie_id::bigint                                    as movie_id,
        appid::bigint                                       as appid,
        status,
        verdict,
        nullif(duration_sec, '')::numeric                   as duration_sec,
        nullif(fps, '')::numeric                            as fps,
        nullif(width, '')::int                              as width,
        nullif(height, '')::int                             as height,
        nullif(peak_general_fps, '')::numeric               as peak_general_flashes_per_sec,
        nullif(peak_red_fps, '')::numeric                   as peak_red_flashes_per_sec,
        nullif(n_incidents, '')::int                        as n_incidents,
        nullif(n_general_incidents, '')::int                as n_general_incidents,
        nullif(n_red_incidents, '')::int                    as n_red_incidents,
        nullif(first_incident_sec, '')::numeric             as first_incident_sec,
        nullif(failing_seconds, '')::numeric                as failing_seconds,
        nullif(share_frames_failing, '')::numeric           as share_frames_failing,
        nullif(scanned_at, '')::timestamptz                 as scanned_at
    from {{ source('raw', 'scans') }}
),

ranked as (
    select
        *,
        row_number() over (partition by movie_id order by scanned_at desc) as rn
    from src
    where status = 'ok'
)

select
    movie_id, appid, verdict, duration_sec, fps, width, height,
    peak_general_flashes_per_sec, peak_red_flashes_per_sec,
    greatest(peak_general_flashes_per_sec, peak_red_flashes_per_sec) as peak_flashes_per_sec,
    n_incidents, n_general_incidents, n_red_incidents,
    first_incident_sec, failing_seconds, share_frames_failing, scanned_at
from ranked
where rn = 1
