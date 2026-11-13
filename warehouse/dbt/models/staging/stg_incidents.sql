-- One row per flagged section of a trailer.

select
    md5(movie_id || '|' || kind || '|' || start_sec)    as incident_id,
    movie_id::bigint                                    as movie_id,
    appid::bigint                                       as appid,
    kind                                                as flash_type,
    start_sec::numeric                                  as start_sec,
    end_sec::numeric                                    as end_sec,
    duration_sec::numeric                               as duration_sec,
    peak_flashes_per_sec::numeric                       as peak_flashes_per_sec
from {{ source('raw', 'incidents') }}
