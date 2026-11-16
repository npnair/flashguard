# FlashGuard for Chrome

A Chrome extension that protects you from flashing that can trigger photosensitive seizures, on any site with a normal video player (YouTube, Twitch, news sites and so on).

It runs the same WCAG flash check as the FlashGuard detector, rewritten in JavaScript, on every frame of the video you're watching.

## What it does

**Live protection.** When flashing goes over the WCAG limit, FlashGuard dims the video almost to black (or pauses it) and shows a banner. When the flashing stops, the picture comes back. In testing it reacts within about 0.7 seconds of a strobe starting.

**Check this video first.** Click the extension icon, then **Check this video first**. FlashGuard plays the video hidden and muted, maps every flashing section, and tells you where they are:

> Flashing found in 2 places: 0:05–0:08, 0:12–0:15 (red flashing)

When you watch, those sections are **skipped automatically** (or dimmed, if you prefer), so you're warned before the flashing ever reaches you.

The check and live protection use the same rule, so what a check reports is exactly what gets dimmed or skipped while you watch.

**How fast a check runs.** It plays as fast as your screen can show every frame: 2x on a normal 60 Hz screen (a 2-minute video takes about a minute) and up to 4x on a 120 or 144 Hz screen. Going faster would skip frames, and the frames it skipped could be the fastest strobes, which are the most dangerous ones. If your computer starts dropping frames, the check slows itself down. It pauses if you switch tabs, because the browser stops drawing video in background tabs.

## Settings

| Setting | Options |
|---|---|
| When flashing starts | Dim the video / Pause the video |
| React at | Over 3 flashes/sec (the WCAG limit, recommended) / 2 flashes/sec (extra sensitive, more false alarms) |
| Flashing found by a check | Dim it / Skip over it |

The extra-sensitive setting reacts below the WCAG limit. It catches more, but ordinary video edits like quick cuts and replay transitions can set it off.

## Install (developer mode)

1. Open `chrome://extensions` in Chrome.
2. Turn on **Developer mode** (top right).
3. Click **Load unpacked** and choose this `extension` folder.
4. Pin FlashGuard from the puzzle-piece menu so its icon is always visible.

Pages that were already open need a reload before FlashGuard can protect them.

## How it works

- Each frame is drawn from the video itself (not the screen) onto a small 160px-wide canvas, so the dimming never hides anything from the detector.
- `detector.js` converts the pixels to relative luminance, tracks brightness runs per pixel, and counts a transition when at least 25% net of a 10° field of view changes the same way. Counting the net area means camera motion cancels out. Saturated red is checked separately.
- **Flash size follows your screen.** WCAG measures a flash against your field of view, approximated as a third of the screen's width and height. A video in a normal YouTube player covers less of your view than a full-screen one, so a flash has to cover more of the video before it counts. Full screen, it's the same as the Python detector.
- Flashes are counted over the last second of **video time**, so 2x playback and dropped frames still measure a real second.
- When frames get dropped, a change is counted in the middle of the gap instead of at the frame where it was noticed, so dropped frames can't squeeze flashes together and push a borderline video over the limit.
- `test/parity.js` runs the JavaScript detector on the same synthetic clips as the Python tests. It matches the Python detector's verdict and peak flash rate on all 13 clips.

## Limits

- **It reacts, it can't predict.** Live protection needs a fraction of a second of flashing to recognize it. Use **Check this video first** to be warned ahead of time.
- **Streaming services with copy protection** (Netflix, Disney+, Prime Video and similar) don't let extensions read their frames, so FlashGuard can't see those videos.
- **Some sites block reading their video** for security reasons. The popup says so when that happens.
- **Live streams** can't be checked ahead of time. Live protection still works.
- **Videos right at the limit** (about 3 flashes a second) can occasionally get flagged when the computer drops frames. It errs toward flagging, never toward missing faster flashing.
- **Slow computers** may skip frames during a 2x check. The result says so if that happens, since very short flashes could be missed.
- **Pattern reversals** (flipping stripes or checkerboards) aren't detected yet, same as the Python detector.

This is a screening tool based on the WCAG limits, not a medical device. It doesn't replace other precautions.

## What I tried that didn't work

**Look-ahead on YouTube.** The idea was to play a hidden, muted copy of the video a few seconds ahead of you, so flashing could be dimmed from its first flash to its last. On test pages it dimmed within about 0.2 seconds of each edge. On real YouTube it never started: YouTube refuses to play its embedded player inside youtube.com itself (error 152-4), even though the same player plays fine on other sites. The code is still in `content.js` but switched off.
