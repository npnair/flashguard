-- One row per sampled game, with proper types and a few handy derived columns.

with src as (
    select * from {{ source('raw', 'games') }}
),

typed as (
    select
        appid::bigint                                   as appid,
        name                                            as game_name,
        sampled_genre,
        string_to_array(nullif(genres, ''), '|')        as steam_genres,
        lower(is_free) = 'true'                         as is_free,
        nullif(price_usd, '')::numeric(10, 2)           as price_usd,
        release_date                                    as release_date_text,
        case
            when release_date ~ '^[A-Z][a-z]{2} \d{1,2}, \d{4}$' then to_date(release_date, 'Mon DD, YYYY')
            when release_date ~ '^\d{1,2} [A-Z][a-z]{2}, \d{4}$' then to_date(release_date, 'DD Mon, YYYY')
        end                                             as release_date,
        nullif(substring(release_date from '(\d{4})'), '')::int as release_year,
        lower(coming_soon) = 'true'                     as is_coming_soon,
        nullif(developers, '')                          as developers,
        nullif(publishers, '')                          as publishers,
        nullif(metacritic, '')::numeric::int            as metacritic,
        nullif(regexp_replace(required_age, '\D', '', 'g'), '')::int as required_age,
        nullif(owners_estimate, '')::bigint             as owners_estimate,
        nullif(positive_reviews, '')::numeric::bigint   as positive_reviews,
        nullif(negative_reviews, '')::numeric::bigint   as negative_reviews,
        nullif(n_trailers, '')::int                     as n_trailers
    from src
)

select
    *,
    case
        when is_free or price_usd = 0 then 'Free'
        when price_usd < 10 then 'Under $10'
        when price_usd < 20 then '$10-19.99'
        when price_usd < 40 then '$20-39.99'
        when price_usd >= 40 then '$40+'
        else 'Unknown'
    end                                                 as price_band,
    case
        when is_free or price_usd = 0 then 0
        when price_usd < 10 then 1
        when price_usd < 20 then 2
        when price_usd < 40 then 3
        when price_usd >= 40 then 4
        else 9
    end                                                 as price_band_order,
    case
        when release_year is null then 'Unknown'
        when release_year <= 2014 then '2014 and earlier'
        when release_year <= 2018 then '2015-2018'
        when release_year <= 2022 then '2019-2022'
        else '2023 and later'
    end                                                 as release_era,
    case
        when positive_reviews + negative_reviews > 0
        then round(positive_reviews::numeric / (positive_reviews + negative_reviews), 3)
    end                                                 as review_score
from typed
