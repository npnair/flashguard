-- The stricter "clear fail" line must always be a subset of "flagged".
-- Returns rows (= test fails) if any trailer is a clear fail but not flagged.
select movie_id
from {{ ref('fct_trailer_scans') }}
where is_clear_fail and not is_flagged
