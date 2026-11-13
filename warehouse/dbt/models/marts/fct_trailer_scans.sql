-- One row per scanned trailer, joined to its game. The main table for the dashboard.

with scans as (
    select * from {{ ref('stg_scans') }}
),
games as (
    select * from {{ ref('stg_games') }}
),
trailers as (
    select * from {{ ref('stg_trailers') }}
),

joined as (
    select
        s.movie_id,
        s.appid,
        g.game_name,
        t.trailer_name,
        g.sampled_genre,
        g.steam_genres,
        g.price_usd,
        g.price_band,
        g.price_band_order,
        g.release_date,
        g.release_year,
        g.release_era,
        g.developers,
        g.publishers,
        g.owners_estimate,
        g.review_score,
        g.metacritic,
        s.verdict,
        s.duration_sec,
        s.fps,
        case when s.fps >= 48 then '60 fps' else '30 fps or less' end      as fps_group,
        s.width,
        s.height,
        s.peak_general_flashes_per_sec,
        s.peak_red_flashes_per_sec,
        s.peak_flashes_per_sec,
        s.n_incidents,
        s.n_general_incidents,
        s.n_red_incidents,
        s.first_incident_sec,
        s.failing_seconds,
        s.share_frames_failing,
        ntile(4) over (order by g.owners_estimate)                         as owners_quartile
    from scans s
    left join games g on g.appid = s.appid
    left join trailers t on t.movie_id = s.movie_id
)

select
    *,
    -- WCAG line: more than 3 flashes per second
    peak_flashes_per_sec > {{ var('flag_threshold') }}                     as is_flagged,
    -- stricter sensitivity line
    peak_flashes_per_sec >= {{ var('clear_fail_threshold') }}              as is_clear_fail,
    verdict = 'CAUTION'                                                    as is_caution,
    case
        when n_red_incidents > 0 and n_general_incidents > 0 then 'Both'
        when n_red_incidents > 0 then 'Red only'
        when n_general_incidents > 0 then 'General only'
        else 'None'
    end                                                                    as flash_types,
    case when duration_sec > 0 then first_incident_sec / duration_sec end  as first_incident_position,
    case
        when owners_quartile = 1 then 'Q1 (smallest)'
        when owners_quartile = 4 then 'Q4 (biggest)'
        else 'Q' || owners_quartile
    end                                                                    as owners_quartile_label
from joined
