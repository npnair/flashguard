# FlashGuard

Scan a video for flashing that can trigger photosensitive seizures, and get a timeline of exactly where the problem spots are.

I have epilepsy, and most creators and game developers never check their content for this. FlashGuard checks a video against the WCAG accessibility rules for flashing and tells you what fails and when.

**📊 Interactive dashboard: [npnair.github.io/flashguard](https://npnair.github.io/flashguard)**

## What I found: 1 in 3 Steam game trailers fails

I used FlashGuard to scan the main trailer of 240 randomly sampled Steam games (40 per genre).

- **35% were flagged** for more than 3 flashes per second. With a stricter line of 4+ per second, it's still **30%**.
- **Action and Sports trailers fail most (48%)**, Simulation least (20%).
- **$40+ games fail most by price (82%)**, though that group is small (17 games).
- **Flashing clusters at 70 to 90% of the way through a trailer**, the big finale before the logo.
- **The fix is usually small:** a failing trailer has a median of about 4 seconds of flagged footage.

A spot check of still frames from 6 flagged trailers found 4 real flashes and 2 borderline false alarms, which is why the stricter 4+/sec line is reported too. Details and limits are on the dashboard.

## How the project fits together

| Part | Folder | What it does |
|---|---|---|
| Detector | `flashguard/` | Scans a video frame by frame against the WCAG flash rules, with 13 tests |
| Study pipeline | `study/` | Samples Steam games, downloads each trailer without playing it, scans it and deletes it |
| Warehouse | `warehouse/` | PostgreSQL in Docker plus dbt models (staging → marts) with 30 data tests |
| Dashboard | `docs/` | The interactive results page, hosted on GitHub Pages |

## What it checks

FlashGuard follows the WCAG 2.x "three flashes" threshold:

- **General flash.** A transition is a change in relative brightness of at least 10%, where the darker state is below 80% brightness. Two opposing transitions (bright to dark to bright) make one flash.
- **Red flash.** The same idea for saturated red, which is more dangerous at the same brightness.
- **Rate.** More than 3 flashes in any one second fails.
- **Area.** Flashing only counts if it covers at least 25% of a 10 degree field of view. WCAG approximates that as a third of the screen's width by a third of its height, and FlashGuard slides that window across every frame.

**Motion isn't flashing.** When the camera pans or something moves, lots of pixels change, but about as many get brighter as get darker. FlashGuard measures the *net* flashing area in each window (pixels brightening minus pixels darkening), so motion cancels out while a real flash, which pushes a whole area the same way, still counts. The first version counted every pixel on its own, and testing it on real phone footage showed that camera movement caused false alarms. The motion test clips below came out of that.

## How it works

1. Read each frame with OpenCV and convert the colors to linear light (the WCAG formula).
2. Downscale to 160 px wide for speed.
3. For every pixel, track brightness runs and record when a run changes by enough.
4. For every 10 degree window, a transition happens when the net share of pixels changing the same way is at least 25%.
5. Keep a rolling one-second count of opposing transitions per window.
6. Group failing seconds into incidents and write the reports.

## Usage

```bash
pip install -r requirements.txt
python -m flashguard my_video.mp4 --out reports
```

Each video produces:

- `*_report.html`: verdict, chart of flashes per second over time, list of incidents
- `*_frames.csv`: per-frame data (brightness, flash rates, flashing area, status)
- `*_summary.json`: verdict and incidents, for use in other tools

Verdicts: **PASS**, **CAUTION** (2.5 to 3 flashes/sec, close to the limit) or **FAIL**. The command exits with code 1 if any video fails, so it can run in CI.

## Testing without watching flashing video

```bash
python tools/make_test_clips.py test_clips   # generate clips with known answers
python -m pytest -q                            # check the detector gets them right
```

> ⚠️ Files starting with `UNSAFE_` really flash. Don't open them if you're photosensitive. The tests check them automatically, so nobody has to watch them.

| Clip | Expected | What it tests |
|---|---|---|
| safe_slow_fade | PASS | Big brightness change, but slow |
| safe_dim_flicker | PASS | Fast, but too small a brightness change |
| safe_small_flash | PASS | Fast and full contrast, but too small an area |
| caution_3_flashes_per_sec | CAUTION | Right at the limit |
| UNSAFE_fullscreen_5hz | FAIL | Classic strobe |
| safe_fast_camera_pan | PASS | Fast pan across a textured scene |
| safe_handheld_shake | PASS | Shaky handheld camera |
| safe_fast_moving_ball | PASS | Bright object moving fast across the screen |
| UNSAFE_flash_during_camera_pan | FAIL | Real flash on top of camera motion |
| UNSAFE_checkerboard_5hz | known limit | Pattern reversal. Marked as an expected failure in the tests |
| UNSAFE_red_flash_4hz | FAIL | Red vs equally bright gray: only the red test catches it |
| UNSAFE_flash_burst_mid_clip | FAIL | Checks the incident is placed at the right time |

## Checking a flagged section safely

```bash
python tools/snapshot.py my_video.mp4 3.1 5.0
```

Saves `snapshot.png`, a grid of still frames from 3.1s to 5.0s, so you can see what's there without playing the video.

## Limits

This is a screening tool, not a certified Harding or PEAT test, and not medical advice. It doesn't yet handle:

- Pattern reversal (a checkerboard or stripes flipping), where average brightness never changes
- Harmful spatial patterns (static stripes)
- Extended flashing rules (counted over longer windows)
- Viewing distance or screen size (it assumes the video fills a typical screen)

## Roadmap

- [ ] Scan YouTube links and real game footage
- [ ] Browser extension that warns before a dangerous section
- [ ] Batch study: scan a large set of trailers or music videos and publish the results
