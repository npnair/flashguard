/*
 * FlashGuard detector, JavaScript version.
 *
 * The same WCAG 2.x logic as flashguard/detector.py, made to run live on
 * frames from a playing video:
 *   - brightness is measured in linear light (relative luminance)
 *   - a transition is a change of at least 0.1 where the darker state is below 0.8
 *   - red: a change of more than 20 in (R-G-B)*320 involving a saturated red
 *   - a 10-degree window (1/3 x 1/3 of the frame) has a transition when the NET
 *     share of its pixels changing the same way is at least 25% (so camera
 *     motion cancels out)
 *   - flashes are counted over the last 1 second of video time
 *
 * Frames come in with their media time, so dropped frames or 2x playback still
 * count against a real one-second window.
 */
(function (root) {
  'use strict';

  const LUM_DELTA = 0.10;
  const LUM_DARK_MAX = 0.80;
  const RED_DELTA = 20.0;
  const RED_SAT = 0.80;
  const AREA_FRAC = 0.25;
  const MAX_TRANSITIONS = 6;   // more than 6 transitions (3 flashes) in 1 second fails WCAG
  const ANALYSIS_WIDTH = 160;
  const WINDOW_SEC = 0.96;     // ~ 29 frames at 30 fps

  // sRGB 0-255 -> linear light (WCAG 2.2 formula)
  const SRGB_TO_LINEAR = new Float32Array(256);
  for (let i = 0; i < 256; i++) {
    const c = i / 255;
    SRGB_TO_LINEAR[i] = c <= 0.04045 ? c / 12.92 : Math.pow((c + 0.055) / 1.055, 2.4);
  }

  // windows are fy x fx of the frame; 1/3 x 1/3 matches the Python detector (video filling the screen)
  function regionsFor(h, w, fy, fx) {
    fy = fy || 1 / 3; fx = fx || 1 / 3;
    const rh = Math.max(1, Math.min(h, Math.round(h * fy)));
    const rw = Math.max(1, Math.min(w, Math.round(w * fx)));
    const sh = Math.max(1, Math.floor(rh / 2));
    const sw = Math.max(1, Math.floor(rw / 2));
    const out = [];
    for (let y = 0; y + rh <= h; y += sh) {
      for (let x = 0; x + rw <= w; x += sw) out.push({ y, x, h: rh, w: rw, n: rh * rw });
    }
    return out;
  }

  /** Tracks per-pixel monotonic runs and emits +1/-1 when a run first qualifies. */
  class TransitionTracker {
    constructor(size, qualifies) {
      this.size = size;
      this.qualifies = qualifies;
      this.prev = null;
      this.prevAux = null;
      this.runStart = new Float32Array(size);
      this.runStartAux = new Uint8Array(size);
      this.direction = new Int8Array(size);
      this.registered = new Uint8Array(size);
      this.events = new Int8Array(size);
    }

    update(value, aux) {
      const n = this.size;
      const ev = this.events;
      if (this.prev === null) {
        this.prev = Float32Array.from(value);
        this.runStart.set(value);
        if (aux) { this.runStartAux.set(aux); this.prevAux = Uint8Array.from(aux); }
        ev.fill(0);
        return ev;
      }
      const prev = this.prev, start = this.runStart, dir = this.direction, reg = this.registered;
      const sAux = this.runStartAux, pAux = this.prevAux;
      const q = this.qualifies;
      for (let i = 0; i < n; i++) {
        const v = value[i];
        const d = v - prev[i];
        const nd = Math.abs(d) < 1e-5 ? 0 : (d > 0 ? 1 : -1);
        if (nd !== 0 && nd !== dir[i]) {          // reversal: a new run starts at the previous value
          start[i] = prev[i];
          if (aux) sAux[i] = pAux[i];
          dir[i] = nd;
          reg[i] = 0;
        }
        ev[i] = 0;
        if (!reg[i] && q(start[i], v, aux ? sAux[i] : 0, aux ? aux[i] : 0)) {
          ev[i] = v > start[i] ? 1 : -1;
          reg[i] = 1;
        }
        prev[i] = v;
        if (aux) pAux[i] = aux[i];
      }
      return ev;
    }
  }

  const lumQualifies = (start, now) =>
    Math.abs(now - start) >= LUM_DELTA && Math.min(now, start) < LUM_DARK_MAX;
  const redQualifies = (start, now, satStart, satNow) =>
    Math.abs(now - start) > RED_DELTA && (satStart || satNow);

  /** Region-level opposing transitions, counted over the last second of video time. */
  class FlashCounter {
    constructor(regions, width) {
      this.regions = regions;
      this.width = width;
      this.lastSign = new Int8Array(regions.length);
      this.history = regions.map(() => []);
    }

    update(t, events, tEff) {
      const w = this.width;
      let best = 0, bestHist = null;
      if (tEff === undefined) tEff = t;
      for (let r = 0; r < this.regions.length; r++) {
        const R = this.regions[r];
        let pos = 0, neg = 0;
        for (let y = R.y; y < R.y + R.h; y++) {
          const row = y * w;
          for (let x = R.x; x < R.x + R.w; x++) {
            const e = events[row + x];
            if (e > 0) pos++; else if (e < 0) neg++;
          }
        }
        const net = (pos - neg) / R.n;
        if (Math.abs(net) >= AREA_FRAC) {
          const sign = net > 0 ? 1 : -1;
          if (sign !== this.lastSign[r]) {        // only opposing changes build flashes
            this.history[r].push(tEff);
            this.lastSign[r] = sign;
          }
        }
        const h = this.history[r];
        // the last second of video, like the Python detector's last 30 frames: just under 1.0s, with room
        // for the small timing jitter browsers add at 2x speed so a borderline 3/sec can't flip to a fail
        while (h.length && h[0] <= t - WINDOW_SEC) h.shift();
        if (h.length > best) { best = h.length; bestHist = h; }
      }
      this.first = bestHist ? bestHist[0] : null;            // when the busiest window's flashing started
      this.last = bestHist ? bestHist[bestHist.length - 1] : null;   // and its latest flash
      return best;
    }
  }

  /**
   * Live detector. Feed it frames (RGBA pixels at analysis size) with their
   * media time; get back how many transitions happened in the last second.
   */
  class FlashDetector {
    /**
     * window: [fy, fx], the share of the frame's height and width that one
     * 10-degree field of view covers. 1/3 x 1/3 when the video fills the screen;
     * bigger when the video is smaller on screen (see windowFor).
     */
    constructor(width, height, window) {
      this.width = width;
      this.height = height;
      const size = width * height;
      this.size = size;
      this.lum = new Float32Array(size);
      this.red = new Float32Array(size);
      this.sat = new Uint8Array(size);
      this.window = window || [1 / 3, 1 / 3];
      this.regions = regionsFor(height, width, this.window[0], this.window[1]);
      this.reset();
    }

    reset() {
      this.lumTracker = new TransitionTracker(this.size, lumQualifies);
      this.redTracker = new TransitionTracker(this.size, redQualifies);
      this.lumCounter = new FlashCounter(this.regions, this.width);
      this.redCounter = new FlashCounter(this.regions, this.width);
      this.lastTime = null;
    }

    /** rgba: Uint8ClampedArray of width*height*4, t: seconds of video time */
    push(rgba, t) {
      // a jump backwards or a gap of more than a second (seek, ad, buffering) restarts the count
      if (this.lastTime !== null && (t < this.lastTime || t - this.lastTime > 1.0)) this.reset();
      // After dropped frames, a change seen now happened somewhere since the last frame we saw.
      // Count it in the middle of that gap instead of at the end, so dropped frames can't squeeze
      // flashes together and push a borderline video over the limit.
      let tEff = t;
      if (this.lastTime !== null) {
        const gap = t - this.lastTime;
        if (gap > 1e-4) this.frameGap = this.frameGap ? Math.min(this.frameGap, gap) : gap;
        if (this.frameGap && gap > 1.5 * this.frameGap) tEff = (this.lastTime + this.frameGap + t) / 2;
      }
      this.lastTime = t;
      const L = SRGB_TO_LINEAR, lum = this.lum, red = this.red, sat = this.sat;
      for (let i = 0, p = 0; i < this.size; i++, p += 4) {
        const r = L[rgba[p]], g = L[rgba[p + 1]], b = L[rgba[p + 2]];
        lum[i] = 0.2126 * r + 0.7152 * g + 0.0722 * b;
        const tot = r + g + b;
        sat[i] = tot > 1e-4 && r / tot >= RED_SAT ? 1 : 0;
        const rv = r - g - b;
        red[i] = rv > 0 ? rv * 320 : 0;
      }
      const general = this.lumCounter.update(t, this.lumTracker.update(lum, null), tEff);
      const redT = this.redCounter.update(t, this.redTracker.update(red, sat), tEff);
      const c = general >= redT ? this.lumCounter : this.redCounter;
      return { t, general, red: redT, worst: Math.max(general, redT), first: c.first, last: c.last };
    }
  }

  /** Turn per-frame results into flagged sections (same rules as the Python incidents). */
  function toSegments(samples, threshold) {
    const limit = threshold === undefined ? MAX_TRANSITIONS : threshold;
    const out = [];
    let cur = null;
    for (const s of samples) {
      if (s.worst > limit) {
        // the flashing that makes this second fail started at its first flash and runs to its latest one
        const start = Math.max(0, s.first != null ? s.first : s.t - 1.0);
        const end = s.last != null ? s.last : s.t;
        if (cur && start <= cur.end + 0.5) {
          cur.start = Math.min(cur.start, start);
          cur.end = Math.max(cur.end, end);
          cur.peak = Math.max(cur.peak, s.worst / 2);
          if (s.red > limit) cur.red = true;
        } else {
          cur = { start, end, peak: s.worst / 2, red: s.red > limit };
          out.push(cur);
        }
      }
    }
    return out;
  }

  function analysisSize(videoWidth, videoHeight) {
    const w = Math.min(ANALYSIS_WIDTH, videoWidth || ANALYSIS_WIDTH);
    const h = Math.max(1, Math.round((videoHeight || 90) * w / (videoWidth || 160)));
    return { w, h };
  }

  /**
   * WCAG approximates a 10-degree field of view as a third of the screen's width
   * by a third of its height. A video shown smaller than full screen covers less
   * of your view, so one 10-degree field covers MORE of the video. Returns [fy, fx].
   */
  function windowFor(videoWidthOnScreen, videoHeightOnScreen, screenWidth, screenHeight) {
    const clamp = (v) => Math.max(1 / 3, Math.min(1, v));
    if (!videoWidthOnScreen || !videoHeightOnScreen || !screenWidth || !screenHeight) return [1 / 3, 1 / 3];
    return [clamp(screenHeight / 3 / videoHeightOnScreen), clamp(screenWidth / 3 / videoWidthOnScreen)];
  }

  const api = { FlashDetector, toSegments, analysisSize, windowFor, MAX_TRANSITIONS, ANALYSIS_WIDTH, SRGB_TO_LINEAR };
  if (typeof module !== 'undefined' && module.exports) module.exports = api;
  root.FlashGuardDetector = api;
})(typeof globalThis !== 'undefined' ? globalThis : this);
