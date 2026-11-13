-- FlashGuard's own verdict and the dbt flag should agree:
-- FAIL  <=> more than 3 flashes/sec. Returns the trailers where they disagree.
select movie_id, verdict, peak_flashes_per_sec, is_flagged
from {{ ref('fct_trailer_scans') }}
where (verdict = 'FAIL') <> is_flagged
