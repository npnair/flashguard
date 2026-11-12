# FlashGuard

Scan a video for flashing that can trigger photosensitive seizures, and get a timeline of exactly where the problem spots are.

I have epilepsy, and most creators and game developers never check their content for this. FlashGuard checks a video against the WCAG accessibility rules for flashing and tells you what fails and when.

## What it checks

FlashGuard follows the WCAG 2.x "three flashes" threshold:

- **General flash.** A transition is a change in relative brightness of at least 10%, where the darker state is below 80% brightness. Two opposing transitions (bright to dark to bright) make one flash.
- **Red flash.** The same idea for saturated red, which is more dangerous at the same brightness.
- **Rate.** More than 3 flashes in any one second fails.
- **Area.** Flashing only counts if it covers at least 25% of a 10 degree field of view. WCAG approximates that as a third of the screen's width by a third of its height, and FlashGuard slides that window across every frame.

Flashes are counted **per pixel**. So patterns like a flipping checkerboard or stripes, where the average brightness never changes but every pixel is strobing, are still caught.

## How it works

1. Read each frame with OpenCV and convert the colors to linear light (the WCAG formula).
2. Downscale to 160 px wide for speed.
3. For every pixel, track brightness runs and record a transition when a run changes by enough.
4. Keep a rolling one-second count of transitions per pixel.
5. For every 10 degree window, find the flash rate that at least 25% of its pixels reach.
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
| UNSAFE_checkerboard_5hz | FAIL | Average brightness constant, every pixel flashing |
| UNSAFE_red_flash_4hz | FAIL | Red vs equally bright gray: only the red test catches it |
| UNSAFE_flash_burst_mid_clip | FAIL | Checks the incident is placed at the right time |

## Limits

This is a screening tool, not a certified Harding or PEAT test, and not medical advice. It doesn't yet handle:

- Harmful spatial patterns (static stripes)
- Extended flashing rules (counted over longer windows)
- Viewing distance or screen size (it assumes the video fills a typical screen)

## Roadmap

- [ ] Scan YouTube links and real game footage
- [ ] Browser extension that warns before a dangerous section
- [ ] Batch study: scan a large set of trailers or music videos and publish the results
