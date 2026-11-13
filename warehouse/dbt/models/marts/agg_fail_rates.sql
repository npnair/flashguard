-- Fail rates broken down several ways, in one "long" table:
--   dimension = what we're slicing by (genre, price band, ...)
--   segment   = the value (Action, $40+, ...)
-- In Power BI, filter on `dimension` and chart `segment` vs the rates.
-- Every rate comes with a 95% Wilson interval, so small groups show their uncertainty.

with t as (
    select * from {{ ref('fct_trailer_scans') }}
),

long as (
    select 'Overall' as dimension, 'All trailers' as segment, 0 as segment_order, * from t
    union all
    select 'Genre', sampled_genre, 0, * from t
    union all
    select 'Price', price_band, price_band_order, * from t
    union all
    select 'Release era', release_era,
           case release_era when '2014 and earlier' then 1 when '2015-2018' then 2
                            when '2019-2022' then 3 when '2023 and later' then 4 else 9 end, * from t
    union all
    select 'Popularity (owners)', owners_quartile_label, owners_quartile, * from t
    union all
    select 'Frame rate', fps_group, case when fps_group = '60 fps' then 2 else 1 end, * from t
),

agg as (
    select
        dimension,
        segment,
        min(segment_order)                                  as segment_order,
        count(*)                                            as n_trailers,
        count(*) filter (where is_flagged)                  as n_flagged,
        count(*) filter (where is_clear_fail)               as n_clear_fail,
        count(*) filter (where is_caution)                  as n_caution,
        count(*) filter (where verdict = 'PASS')            as n_pass,
        percentile_cont(0.5) within group (order by peak_flashes_per_sec) as median_peak_flashes_per_sec,
        avg(failing_seconds) filter (where is_flagged)      as avg_failing_seconds_when_flagged
    from long
    group by dimension, segment
)

select
    dimension,
    segment,
    segment_order,
    n_trailers,
    n_flagged,
    n_clear_fail,
    n_caution,
    n_pass,
    round(n_flagged::numeric / n_trailers, 4)                       as flagged_rate,
    round({{ wilson_low('n_flagged', 'n_trailers') }}, 4)           as flagged_rate_low,
    round({{ wilson_high('n_flagged', 'n_trailers') }}, 4)          as flagged_rate_high,
    round(n_clear_fail::numeric / n_trailers, 4)                    as clear_fail_rate,
    round({{ wilson_low('n_clear_fail', 'n_trailers') }}, 4)        as clear_fail_rate_low,
    round({{ wilson_high('n_clear_fail', 'n_trailers') }}, 4)       as clear_fail_rate_high,
    round(n_caution::numeric / n_trailers, 4)                       as caution_rate,
    round(median_peak_flashes_per_sec::numeric, 2)                  as median_peak_flashes_per_sec,
    round(avg_failing_seconds_when_flagged, 2)                      as avg_failing_seconds_when_flagged,
    n_trailers < 20                                                 as is_small_sample
from agg
