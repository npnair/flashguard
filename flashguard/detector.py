"""
Core flash detection.

Based on the WCAG 2.x "general flash" and "red flash" thresholds:

* A transition is a change in relative luminance of at least 0.1 (10% of max)
  where the darker of the two states is below 0.8.
* A flash is a pair of opposing transitions (bright -> dark -> bright, etc).
* Content fails if there are more than 3 flashes (more than 6 transitions)
  in any one second, AND the flashing area is big enough: at least 25% of
  any 10 degree field of view. WCAG approximates that field as a 341 x 256
  rectangle on a 1024 x 768 screen, i.e. one third of the width by one third
  of the height. We slide that window across the frame.
* Red flash: same counting, but the transition is a change of more than 20 in
  (R - G - B) * 320 where the color is a saturated red (R / (R+G+B) >= 0.8).

This is a screening tool, not a certified Harding test.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, List, Optional

import cv2
import numpy as np

# ---- thresholds -----------------------------------------------------------
LUM_DELTA = 0.10          # min relative luminance change for a transition
LUM_DARK_MAX = 0.80       # darker state must be below this
RED_DELTA = 20.0          # min change in (R-G-B)*320
RED_SAT = 0.80            # R/(R+G+B) needed to count as saturated red
AREA_FRAC = 0.25          # share of a 10 degree window that must flash
MAX_TRANSITIONS = 6       # more than 6 transitions/sec (= >3 flashes) fails
CAUTION_TRANSITIONS = 5   # 5-6 transitions/sec is close to the limit
ANALYSIS_WIDTH = 160      # frames are downscaled to this width for speed


# sRGB 0-255 -> linear light lookup table (WCAG 2.2 formula)
_c = np.arange(256, dtype=np.float64) / 255.0
_SRGB_TO_LINEAR = np.where(_c <= 0.04045, _c / 12.92, ((_c + 0.055) / 1.055) ** 2.4).astype(np.float32)


@dataclass
class Incident:
    kind: str              # "general" or "red"
    start_time: float
    end_time: float
    peak_flashes_per_sec: float


@dataclass
class AnalysisResult:
    fps: float
    frame_count: int
    duration: float
    width: int
    height: int
    times: np.ndarray                 # seconds, per frame
    avg_luminance: np.ndarray         # mean relative luminance per frame
    general_tps: np.ndarray           # max luminance transitions in the last 1s (any region)
    red_tps: np.ndarray               # max red transitions in the last 1s (any region)
    peak_area: np.ndarray             # biggest flashing share of any 10 degree window this frame
    incidents: List[Incident] = field(default_factory=list)

    @property
    def verdict(self) -> str:
        if self.incidents:
            return "FAIL"
        worst = max(int(self.general_tps.max(initial=0)), int(self.red_tps.max(initial=0)))
        return "CAUTION" if worst >= CAUTION_TRANSITIONS else "PASS"

    def frame_status(self) -> np.ndarray:
        worst = np.maximum(self.general_tps, self.red_tps)
        status = np.full(worst.shape, "pass", dtype=object)
        status[worst >= CAUTION_TRANSITIONS] = "caution"
        status[worst > MAX_TRANSITIONS] = "fail"
        return status


class _TransitionTracker:
    """Tracks, per pixel, monotonic runs of a signal and emits +1/-1 events
    when a run first becomes a qualifying transition."""

    def __init__(self, shape):
        self.prev = None
        self.run_start = np.zeros(shape, np.float32)
        self.run_start_aux = np.zeros(shape, bool)   # extra state saved at run start (red saturation)
        self.direction = np.zeros(shape, np.int8)
        self.registered = np.zeros(shape, bool)

    def update(self, value: np.ndarray, qualifies: Callable, aux: Optional[np.ndarray] = None):
        if self.prev is None:
            self.prev = value.copy()
            self.run_start[:] = value
            if aux is not None:
                self.run_start_aux[:] = aux
            self.prev_aux = aux
            return np.zeros(value.shape, np.int8)

        d = value - self.prev
        newdir = np.sign(d).astype(np.int8)
        newdir[np.abs(d) < 1e-5] = 0
        reversed_ = (newdir != 0) & (newdir != self.direction)

        # a reversal starts a new run from the previous frame's value
        self.run_start[reversed_] = self.prev[reversed_]
        if aux is not None:
            self.run_start_aux[reversed_] = self.prev_aux[reversed_]
        self.direction[reversed_] = newdir[reversed_]
        self.registered[reversed_] = False

        ok = qualifies(self.run_start, value, self.run_start_aux, aux) & ~self.registered
        events = np.zeros(value.shape, np.int8)
        change = value - self.run_start
        events[ok & (change > 0)] = 1
        events[ok & (change < 0)] = -1
        self.registered |= ok

        self.prev = value.copy()
        self.prev_aux = aux
        return events


def _lum_qualifies(start, now, _a0, _a1):
    return (np.abs(now - start) >= LUM_DELTA) & (np.minimum(now, start) < LUM_DARK_MAX)


def _red_qualifies(start, now, sat_start, sat_now):
    return (np.abs(now - start) > RED_DELTA) & (sat_start | sat_now)


def _regions(h: int, w: int):
    """Overlapping 10 degree windows (1/3 x 1/3 of the frame), stepping by 1/6."""
    rh, rw = max(1, round(h / 3)), max(1, round(w / 3))
    sh, sw = max(1, rh // 2), max(1, rw // 2)
    out = []
    for y in range(0, h - rh + 1, sh):
        for x in range(0, w - rw + 1, sw):
            out.append((slice(y, y + rh), slice(x, x + rw)))
    return out


class _FlashCounter:
    """Turns pixel events into region-level transitions and counts them over the last second.

    A region has a transition when its NET flashing area is at least 25%:
    (share of pixels that just brightened enough) minus (share that just
    darkened enough). When the camera pans or an object moves, about as many
    pixels brighten as darken, so they cancel out and motion isn't counted as
    flashing. A real flash pushes a whole area the same way at once."""

    def __init__(self, n_regions: int, window: int):
        self.window = window
        self.last_sign = np.zeros(n_regions, np.int8)
        self.history: List[List[int]] = [[] for _ in range(n_regions)]

    def update(self, frame_idx: int, events: np.ndarray, regions) -> tuple[int, float]:
        pos = (events > 0).astype(np.float32)
        neg = (events < 0).astype(np.float32)
        best = 0
        peak_area = 0.0
        for i, (ys, xs) in enumerate(regions):
            net = float(pos[ys, xs].mean()) - float(neg[ys, xs].mean())
            peak_area = max(peak_area, abs(net))
            if abs(net) >= AREA_FRAC:
                sign = 1 if net > 0 else -1
                if sign != self.last_sign[i]:      # only opposing changes build flashes
                    self.history[i].append(frame_idx)
                    self.last_sign[i] = sign
            h = self.history[i]
            while h and h[0] <= frame_idx - self.window:
                h.pop(0)
            best = max(best, len(h))
        return best, peak_area


def _incidents(times, tps, kind, fps) -> List[Incident]:
    out = []
    bad = tps > MAX_TRANSITIONS
    i = 0
    n = len(tps)
    while i < n:
        if bad[i]:
            j = i
            while j + 1 < n and bad[j + 1]:
                j += 1
            # the failing 1s window started up to a second before the first failing frame
            start = max(0.0, float(times[i]) - 1.0 + 1.0 / fps)
            end = float(times[j])
            peak = float(tps[i:j + 1].max()) / 2
            if out and start <= out[-1].end_time + 0.5:   # overlapping or nearly touching: merge
                prev = out[-1]
                prev.end_time = round(end, 3)
                prev.peak_flashes_per_sec = max(prev.peak_flashes_per_sec, round(peak, 1))
            else:
                out.append(Incident(kind, round(start, 3), round(end, 3), round(peak, 1)))
            i = j + 1
        else:
            i += 1
    return out


def analyze_video(path: str, progress: Optional[Callable[[int, int], None]] = None) -> AnalysisResult:
    cap = cv2.VideoCapture(path)
    if not cap.isOpened():
        raise ValueError(f"Could not open video: {path}")
    fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
    total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
    width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))

    aw = min(ANALYSIS_WIDTH, width)
    ah = max(1, round(height * aw / width))
    regions = _regions(ah, aw)
    window = max(1, round(fps))

    lum_tracker = _TransitionTracker((ah, aw))
    red_tracker = _TransitionTracker((ah, aw))
    lum_counter = _FlashCounter(len(regions), window)
    red_counter = _FlashCounter(len(regions), window)

    avg_lum, g_tps, r_tps, areas = [], [], [], []
    idx = 0
    while True:
        ok, frame = cap.read()
        if not ok:
            break
        lin = _SRGB_TO_LINEAR[frame]                       # BGR, linear light
        lin = cv2.resize(lin, (aw, ah), interpolation=cv2.INTER_AREA)
        b, g, r = lin[..., 0], lin[..., 1], lin[..., 2]
        lum = 0.2126 * r + 0.7152 * g + 0.0722 * b

        total_rgb = r + g + b
        sat = (r / np.maximum(total_rgb, 1e-6) >= RED_SAT) & (total_rgb > 1e-4)
        red_val = np.maximum(r - g - b, 0) * 320.0

        lum_ev = lum_tracker.update(lum, _lum_qualifies)
        red_ev = red_tracker.update(red_val, _red_qualifies, sat)

        gt, area = lum_counter.update(idx, lum_ev, regions)
        rt, _ = red_counter.update(idx, red_ev, regions)

        avg_lum.append(float(lum.mean()))
        g_tps.append(gt)
        r_tps.append(rt)
        areas.append(area)
        idx += 1
        if progress and idx % 30 == 0:
            progress(idx, total)
    cap.release()

    if idx == 0:
        raise ValueError(f"No frames could be read from: {path}")

    times = np.arange(idx) / fps
    g_tps = np.array(g_tps)
    r_tps = np.array(r_tps)
    result = AnalysisResult(
        fps=fps, frame_count=idx, duration=idx / fps, width=width, height=height,
        times=times, avg_luminance=np.array(avg_lum),
        general_tps=g_tps, red_tps=r_tps, peak_area=np.array(areas),
    )
    result.incidents = _incidents(times, g_tps, "general", fps) + _incidents(times, r_tps, "red", fps)
    result.incidents.sort(key=lambda x: x.start_time)
    return result
