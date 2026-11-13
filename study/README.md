# Study: how many Steam game trailers break seizure safety limits?

Game trailers are built to be intense: fast cuts, explosions, muzzle flashes, glitch effects. This study scans a random sample of Steam trailers with FlashGuard to see how many would fail the WCAG flash thresholds, and which kinds of games are most likely to.

## Questions

1. What share of Steam trailers fail? How many come close (CAUTION)?
2. Which genres fail most?
3. General (brightness) flashes vs red flashes: which is more common?
4. Where do failures happen: in the first few seconds (the hook) or later?
5. Do big releases (price, owners, publisher) fail more or less often than small indie games?
6. Has it changed over time (release year)?

## Pipeline

```
SteamSpy (games per genre) ──► collect_games.py ──► data/games.csv
Steam store API (details)  ─┘                   └► data/trailers.csv
                                                         │
             scan_trailers.py: download (never played) ──┤
                               FlashGuard scan           │
                               delete video              ▼
                                         data/scans.csv + data/incidents.csv
                                                         │
                         PostgreSQL ► dbt models ► Power BI dashboard  (next steps)
```

## Running it

```bash
pip install -r requirements.txt

# 1. collect a sample: 40 games per genre, 9 genres (takes ~20-25 min because of API rate limits)
python study/collect_games.py --per-genre 40

# 2. scan each game's main trailer (resumable: Ctrl+C any time, rerun to continue)
python study/scan_trailers.py
```

Quick test first: `python study/collect_games.py --per-genre 2 --genres Action Indie`, then `python study/scan_trailers.py --limit 3`.

## Data

| File | One row per | Key columns |
|---|---|---|
| `games.csv` | game | appid, name, sampled_genre, genres, price_usd, release_date, developers, publishers, owners_estimate, metacritic |
| `trailers.csv` | trailer | movie_id, appid, trailer_name, is_main, url |
| `scans.csv` | scan attempt | movie_id, verdict, peak_general_fps, peak_red_fps, n_incidents, first_incident_sec, failing_seconds, share_frames_failing, status, error |
| `incidents.csv` | failing section | movie_id, kind (general/red), start_sec, end_sec, peak_flashes_per_sec |

A trailer that failed to download gets a `status = error` row and is retried on the next run, so use the latest `ok` row per `movie_id`.

## Ground rules

- **No one watches the videos.** Each trailer is downloaded at low resolution to a temp folder, scanned, and deleted right away.
- **Only results are published**, never the videos.
- **Careful wording.** FlashGuard is a screening tool, not a certified Harding test. A failing trailer has been "flagged by an automated WCAG screen," not proven dangerous. Findings are reported in aggregate (by genre, etc.), not as a list of games to shame.
- **Known limits** (see the main README): pattern reversal isn't detected yet, so the true failure rate could be higher than measured.
