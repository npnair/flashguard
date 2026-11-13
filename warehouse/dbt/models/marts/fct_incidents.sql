-- One row per flagged section, with where it falls in the trailer.

with incidents as (
    select * from {{ ref('stg_incidents') }}
),
scans as (
    select movie_id, game_name, sampled_genre, price_band, release_era, duration_sec
    from {{ ref('fct_trailer_scans') }}
)

select
    i.incident_id,
    i.movie_id,
    i.appid,
    s.game_name,
    s.sampled_genre,
    s.price_band,
    s.release_era,
    i.flash_type,
    i.start_sec,
    i.end_sec,
    i.duration_sec,
    i.peak_flashes_per_sec,
    s.duration_sec                                                  as trailer_duration_sec,
    case when s.duration_sec > 0 then least(i.start_sec / s.duration_sec, 1) end as position_in_trailer,
    -- 10 buckets: 0-10% of the way through the trailer, 10-20%, ...
    least(floor(10 * i.start_sec / nullif(s.duration_sec, 0)), 9)::int as position_decile,
    i.start_sec < 10                                                as starts_in_first_10_sec
from incidents i
join scans s on s.movie_id = i.movie_id
