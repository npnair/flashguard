-- One row per trailer. The URL is kept out on purpose: nothing downstream needs it.

select
    movie_id::bigint                as movie_id,
    appid::bigint                   as appid,
    nullif(trailer_name, '')        as trailer_name,
    nullif(position, '')::int       as trailer_position,
    lower(is_main) = 'true'         as is_main_trailer
from {{ source('raw', 'trailers') }}
