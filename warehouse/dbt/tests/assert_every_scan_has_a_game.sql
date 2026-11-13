-- Every scanned trailer should join to a sampled game.
select movie_id, appid
from {{ ref('fct_trailer_scans') }}
where game_name is null
