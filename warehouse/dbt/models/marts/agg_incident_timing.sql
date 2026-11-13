-- Where in a trailer do flagged sections start? Counted in tenths of the trailer.

with i as (
    select * from {{ ref('fct_incidents') }}
),
deciles as (
    select generate_series(0, 9) as position_decile
)

select
    d.position_decile,
    (d.position_decile * 10) || '-' || (d.position_decile * 10 + 10) || '%'    as position_label,
    count(i.incident_id)                                                        as n_incidents,
    count(i.incident_id) filter (where i.flash_type = 'general')                as n_general,
    count(i.incident_id) filter (where i.flash_type = 'red')                    as n_red,
    round(count(i.incident_id)::numeric / nullif(sum(count(i.incident_id)) over (), 0), 4) as share_of_incidents
from deciles d
left join i on i.position_decile = d.position_decile
group by d.position_decile
order by d.position_decile
