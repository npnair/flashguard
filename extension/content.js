/*
 * FlashGuard content script.
 *
 * 1. Live protection: watches every playing video, runs the WCAG flash check on
 *    each frame, and dims (or pauses) the video when flashing goes over the limit.
 * 2. Look-ahead (YouTube): a hidden, muted copy of the same video plays ahead of
 *    you at 2x or more and sends back where the flashing is. The video you watch
 *    is dimmed exactly while flashing is on screen, starting with the first flash.
 * 3. "Check this video first": plays the video hidden and muted to map all of it.
 *
 * Live protection and the check share one rule (the "React at" setting), and so
 * does look-ahead, so all three always agree.
 *
 * The same script also runs inside the hidden copy (an iframe whose address has
 * fg_lookahead=1), where it only scans and reports.
 */
(() => {
  'use strict';
  if (window.__flashguardLoaded) return;
  window.__flashguardLoaded = true;

  const D = globalThis.FlashGuardDetector;
  const hasChrome = typeof chrome !== 'undefined' && !!(chrome.runtime && chrome.runtime.id && chrome.storage);
  const params = new URLSearchParams(location.search);
  const IS_SHADOW = params.get('fg_lookahead') === '1';

  // ---------------------------------------------------------------- settings
  const DEFAULTS = {
    enabled: true,
    sensitivity: 'wcag',    // wcag: act above 3 flashes/sec (the WCAG limit); sensitive: act at 2 flashes/sec
    liveAction: 'dim',      // dim | pause, for flashing nobody saw coming
    scanAction: 'dim',      // dim | skip, for flashing found ahead of time (look-ahead or a check)
    lookahead: true,        // hidden copy on YouTube
  };
  // act when transitions in the last second exceed this. Everything uses the same number.
  const THRESHOLD = { wcag: D.MAX_TRANSITIONS, sensitive: 3, early: 3 };
  const limit = () => THRESHOLD[settings.sensitivity] ?? THRESHOLD.wcag;
  let settings = { ...DEFAULTS };
  if (hasChrome) {
    chrome.storage.sync.get(DEFAULTS, (s) => { settings = { ...DEFAULTS, ...s }; });
    chrome.storage.onChanged.addListener((changes, area) => {
      if (area !== 'sync') return;
      for (const [k, v] of Object.entries(changes)) settings[k] = v.newValue;
      if (!settings.enabled) monitors.forEach((m) => m.resetProtection());
    });
  }

  const fmt = (s) => {
    s = Math.max(0, Math.floor(s));
    const h = Math.floor(s / 3600), m = Math.floor((s % 3600) / 60), sec = s % 60;
    return (h ? `${h}:${String(m).padStart(2, '0')}` : `${m}`) + `:${String(sec).padStart(2, '0')}`;
  };

  // how many frames per second the screen draws (60 on most screens, 120-144 on gaming laptops)
  function measureRefresh() {
    return new Promise((resolve) => {
      const times = [];
      const step = (t) => {
        times.push(t);
        if (times.length < 25) requestAnimationFrame(step);
        else {
          const d = times.slice(1).map((x, i) => x - times[i]).sort((a, b) => a - b);
          resolve(1000 / d[Math.floor(d.length / 2)]);
        }
      };
      if (document.hidden) resolve(60); else requestAnimationFrame(step);
      setTimeout(() => resolve(60), 1500);   // a throttled frame never finishes measuring
    });
  }
  // fastest speed at which every frame of a 30 fps video still gets drawn
  const speedFor = (hz) => (isFinite(hz) && hz > 0 ? Math.max(1, Math.min(4, Math.floor(hz / 30 + 0.1))) : 2);
  // the hidden copy runs a bit under that, so it doesn't drop frames, and still gains time on you
  const aheadSpeedFor = (hz) => (isFinite(hz) && hz > 0 ? Math.max(1.25, Math.min(4, Math.round(hz / 30 * 0.85 * 20) / 20)) : 1.7);

  /** Reads small frames from a video and runs the detector on them. */
  class FrameReader {
    constructor(video) {
      this.video = video;
      this.canvas = document.createElement('canvas');
      this.ctx = this.canvas.getContext('2d', { willReadFrequently: true });
      this.det = null;
      this.window = [1 / 3, 1 / 3];
      this.blocked = false;
    }
    setWindow(win) {
      if (Math.abs(win[0] - this.window[0]) > 0.05 || Math.abs(win[1] - this.window[1]) > 0.05) {
        this.window = win;
        this.det = null;
      }
    }
    reset() { if (this.det) this.det.reset(); }
    push(t) {
      const v = this.video;
      if (this.blocked || !v.videoWidth || !v.videoHeight) return null;
      const { w, h } = D.analysisSize(v.videoWidth, v.videoHeight);
      if (!this.det || this.det.width !== w || this.det.height !== h) {
        this.canvas.width = w;
        this.canvas.height = h;
        this.det = new D.FlashDetector(w, h, this.window);
      }
      try {
        this.ctx.drawImage(v, 0, 0, w, h);
        return this.det.push(this.ctx.getImageData(0, 0, w, h).data, t);
      } catch (e) {
        this.blocked = true;   // the site serves this video in a way that blocks reading its frames
        return null;
      }
    }
  }

  // merge [start, end] ranges that touch or overlap
  function mergeRanges(ranges, gap = 0.5) {
    const r = ranges.slice().sort((a, b) => a[0] - b[0]);
    const out = [];
    for (const x of r) {
      const last = out[out.length - 1];
      if (last && x[0] <= last[1] + gap) last[1] = Math.max(last[1], x[1]);
      else out.push([x[0], x[1]]);
    }
    return out;
  }

  // ================================================================= HIDDEN COPY (inside the iframe)
  if (IS_SHADOW) {
    runShadow();
    return;
  }

  function runShadow() {
    const post = (msg) => window.parent.postMessage({ __flashguard: 'lookahead', ...msg }, '*');
    let video = null, reader = null, rate = 1.7, paused = false;
    let from = null, batch = [], lastPost = 0, lastT = -1, gotFrame = false;
    const config = { window: [1 / 3, 1 / 3] };

    window.addEventListener('message', (e) => {
      if (e.source !== window.parent || !e.data || e.data.__flashguard !== 'control') return;
      const m = e.data;
      if (m.type === 'config') {
        config.window = m.window;
        if (reader) reader.setWindow(m.window);
        if (m.rate && m.rate !== rate) { rate = m.rate; if (video && !paused) video.playbackRate = rate; }
      }
      if (m.type === 'seek' && video) { video.currentTime = m.t; from = null; if (reader) reader.reset(); }
      if (m.type === 'pause' && video) { paused = true; video.pause(); }
      if (m.type === 'play' && video) { paused = false; video.playbackRate = rate; video.play().catch(() => {}); }
    });

    const adShowing = () => !!document.querySelector('.ad-showing, .ad-interrupting');

    function frame(t) {
      if (adShowing()) return;                 // ads play in the same player: never mix them into the map
      gotFrame = true;
      lastT = t;
      if (video.muted !== true) video.muted = true;
      if (!paused && video.playbackRate !== rate) video.playbackRate = rate;
      const res = reader.push(t);
      if (!res) { if (reader.blocked) post({ type: 'error', reason: 'blocked' }); return; }
      if (from === null) from = t;
      if (res.worst >= 3) batch.push({ t: res.t, worst: res.worst, red: res.red, general: res.general, first: res.first, last: res.last });
      const now = performance.now();
      if (now - lastPost > 200) {
        post({ type: 'progress', from, to: t, samples: batch, duration: video.duration, rate });
        batch = [];
        lastPost = now;
      }
    }

    function loop() {
      if ('requestVideoFrameCallback' in video) video.requestVideoFrameCallback((n, meta) => { frame(meta.mediaTime); loop(); });
    }

    function attach(v) {
      video = v;
      reader = new FrameReader(v);
      reader.setWindow(config.window);
      v.muted = true;
      v.addEventListener('seeking', () => { from = null; reader.reset(); });
      v.addEventListener('ended', () => post({ type: 'progress', from: from ?? lastT, to: v.duration, samples: batch, duration: v.duration, done: true }));
      v.playbackRate = rate;
      v.play().catch(() => {});
      loop();
      // if this hidden frame isn't getting draw callbacks, read frames on a timer instead
      setTimeout(() => {
        if (gotFrame) return;
        setInterval(() => { if (!v.paused && v.currentTime !== lastT) frame(v.currentTime); }, 12);
      }, 2000);
      post({ type: 'ready' });
    }

    const started = Date.now();
    const find = setInterval(() => {
      const v = document.querySelector('video');
      if (v && v.readyState > 0) { clearInterval(find); attach(v); }
      else if (Date.now() - started > 15000) { clearInterval(find); post({ type: 'error', reason: 'unavailable' }); }
    }, 250);
  }

  // ================================================================= MAIN PAGE

  // ---------------------------------------------------------------- on-screen UI (shadow DOM, so site CSS can't touch it)
  class Overlay {
    constructor(video) {
      this.video = video;
      this.host = document.createElement('flashguard-overlay');
      this.host.style.cssText = 'all: initial; position: fixed; z-index: 2147483647; pointer-events: none; left: 0; top: 0;';
      this.root = this.host.attachShadow({ mode: 'open' });
      this.root.innerHTML = `
        <style>
          .box { pointer-events: auto; font: 14px/1.4 system-ui, -apple-system, "Segoe UI", Roboto, sans-serif;
                 color: #fff; background: rgba(20, 20, 24, .92); border: 1px solid rgba(255,255,255,.18);
                 border-radius: 10px; padding: 10px 14px; box-shadow: 0 6px 24px rgba(0,0,0,.45); max-width: 420px; }
          .title { font-weight: 600; display: flex; align-items: center; gap: 8px; }
          .title::before { content: ""; width: 10px; height: 10px; border-radius: 50%; background: var(--dot, #f5a524); flex: none; }
          .text { margin-top: 4px; color: #d6d6dc; }
          .text:empty { display: none; }
          .row { display: flex; gap: 8px; margin-top: 8px; flex-wrap: wrap; }
          button { font: inherit; font-size: 13px; color: #fff; background: rgba(255,255,255,.12); border: 1px solid rgba(255,255,255,.25);
                   border-radius: 6px; padding: 4px 10px; cursor: pointer; }
          button:hover { background: rgba(255,255,255,.22); }
          .bar { height: 6px; border-radius: 3px; background: rgba(255,255,255,.15); margin-top: 8px; overflow: hidden; }
          .fill { height: 100%; width: 0%; background: #5b8def; transition: width .2s; }
          ul { margin: 6px 0 0; padding-left: 18px; color: #d6d6dc; }
          [hidden] { display: none !important; }
        </style>
        <div class="box" hidden>
          <div class="title"></div>
          <div class="text"></div>
          <div class="bar" hidden><div class="fill"></div></div>
          <ul hidden></ul>
          <div class="row"></div>
        </div>`;
      this.box = this.root.querySelector('.box');
      this.titleEl = this.root.querySelector('.title');
      this.textEl = this.root.querySelector('.text');
      this.barEl = this.root.querySelector('.bar');
      this.fillEl = this.root.querySelector('.fill');
      this.listEl = this.root.querySelector('ul');
      this.rowEl = this.root.querySelector('.row');
      this.hideTimer = null;
      this.raf = null;
    }

    mount() {
      const parent = document.fullscreenElement || document.body || document.documentElement;
      if (this.host.parentNode !== parent) parent.appendChild(this.host);
    }

    place() {
      const r = this.video.getBoundingClientRect();
      const w = this.box.offsetWidth || 300;
      const left = Math.max(8, Math.min(window.innerWidth - w - 8, r.left + r.width / 2 - w / 2));
      const top = Math.max(8, Math.min(window.innerHeight - 60, r.top + 12));
      this.host.style.transform = `translate(${left}px, ${top}px)`;
    }

    show({ title, text = '', color = '#f5a524', progress = null, list = null, buttons = [], autoHide = 0 }) {
      this.mount();
      this.box.hidden = false;
      this.box.style.setProperty('--dot', color);
      this.titleEl.textContent = title;
      this.textEl.textContent = text;
      this.barEl.hidden = progress === null;
      if (progress !== null) this.fillEl.style.width = `${Math.round(progress * 100)}%`;
      this.listEl.hidden = !list || !list.length;
      this.listEl.replaceChildren(...(list || []).map((t) => { const li = document.createElement('li'); li.textContent = t; return li; }));
      this.rowEl.replaceChildren(...buttons.map(([label, fn]) => {
        const b = document.createElement('button');
        b.textContent = label;
        b.addEventListener('click', (e) => { e.stopPropagation(); fn(); });
        return b;
      }));
      this.rowEl.hidden = !buttons.length;
      clearTimeout(this.hideTimer);
      if (autoHide) this.hideTimer = setTimeout(() => this.hide(), autoHide);
      const follow = () => { this.place(); this.raf = requestAnimationFrame(follow); };
      cancelAnimationFrame(this.raf);
      follow();
    }

    hide() {
      this.box.hidden = true;
      cancelAnimationFrame(this.raf);
      clearTimeout(this.hideTimer);
    }
  }

  // ---------------------------------------------------------------- stored maps of flashing, per video
  const savedScans = new Map();   // key -> { samples, choppy }  from "Check this video first"
  const aheadMaps = new Map();    // key -> { samples, covered: [[from, to]] }  from look-ahead

  // ---------------------------------------------------------------- one monitor per video
  const monitors = new Map();

  class Monitor {
    constructor(video) {
      this.video = video;
      this.reader = new FrameReader(video);
      this.protecting = false;      // live protection engaged
      this.quietUntil = 0;
      this.overridden = false;      // "show anyway" for the current episode
      this.aheadDim = false;        // inside a section found ahead of time (look-ahead or a check)
      this.aheadSeg = null;
      this.dimmed = false;
      this.savedFilter = null;
      this.scan = null;
      this.lastT = -1;
      this.overlay = new Overlay(video);
      this.stopped = false;
      video.addEventListener('seeking', () => { this.reader.reset(); lookahead.onSeek(this); });
      video.addEventListener('ended', () => { if (this.scan) this.finishScan(); });
      this.loop();
    }

    loop() {
      if (this.stopped) return;
      const v = this.video;
      if (!v.isConnected) { this.stop(); return; }
      if ('requestVideoFrameCallback' in v) {
        v.requestVideoFrameCallback((now, meta) => { this.onFrame(meta.mediaTime); this.loop(); });
      } else {
        requestAnimationFrame(() => { if (!v.paused && v.currentTime !== this.lastT) this.onFrame(v.currentTime); this.loop(); });
      }
    }

    stop() {
      this.stopped = true;
      this.resetProtection();
      this.overlay.hide();
      monitors.delete(this.video);
    }

    get unsupported() { return this.reader.blocked; }

    // how much of the video one 10-degree field of view covers, from its size on screen
    viewWindow() {
      const r = this.video.getBoundingClientRect();
      return D.windowFor(r.width, r.height, screen.width, screen.height);
    }

    key() {
      const u = new URL(location.href);
      u.searchParams.delete('t');
      u.hash = '';
      return `${u.toString()}|${Math.round(this.video.duration || 0)}`;
    }

    onFrame(t) {
      this.lastT = t;
      if (!this.scan && !settings.enabled) return;
      if (!this.scan) {
        const now = performance.now();
        if (!this.windowAt || now - this.windowAt > 1000) { this.windowAt = now; this.reader.setWindow(this.viewWindow()); }
      }
      // sections found ahead of time are applied before this frame's own check, so they act on time
      if (!this.scan) this.applyFound(t);
      const res = this.reader.push(t);
      if (!res) return;
      if (this.scan) { this.scanFrame(res); return; }
      this.live(res);
    }

    // ---- dimming: on while ANY reason says so
    updateDim() {
      const live = this.protecting && !this.overridden && settings.liveAction === 'dim';
      this.dim(settings.enabled && (live || (this.aheadDim && !this.overridden)));
    }

    dim(on) {
      const s = this.video.style;
      if (on && !this.dimmed) {
        this.savedFilter = [s.getPropertyValue('filter'), s.getPropertyPriority('filter')];
        s.setProperty('filter', 'brightness(0.08) contrast(0.5) blur(4px)', 'important');
        this.dimmed = true;
      } else if (!on && this.dimmed) {
        const [val, prio] = this.savedFilter || ['', ''];
        if (val) s.setProperty('filter', val, prio); else s.removeProperty('filter');
        this.dimmed = false;
      }
    }

    resetProtection() {
      this.protecting = false;
      this.overridden = false;
      this.aheadDim = false;
      this.aheadSeg = null;
      this.dim(false);
      this.overlay.hide();
    }

    // is this moment already mapped (by the look-ahead or a full check)?
    isCovered(t) {
      const k = this.key();
      if (savedScans.has(k)) return true;
      const map = aheadMaps.get(k);
      return !!map && map.covered.some((r) => t >= r[0] && t <= r[1]);
    }

    // ---- live protection (flashing nobody saw coming)
    live(res) {
      // Where the map already covers this moment, it decides, so dimming starts at the first flash and ends
      // at the last one. Live protection only steps in if it sees flashing clearly over the limit that the
      // map missed, and not in the second after a mapped section (its count still includes those flashes).
      const covered = this.isCovered(res.t);
      if (covered && (this.aheadDim || res.t - (this.aheadEndedAt ?? -9) < 1.0)) return;
      const bar = covered ? limit() + 2 : limit();
      if (res.worst > bar) {
        this.quietUntil = res.t + 1.5;
        if (!this.protecting) this.engage(res);
      } else if (this.protecting && res.t > this.quietUntil) {
        this.protecting = false;
        this.overridden = this.aheadDim ? this.overridden : false;
        this.updateDim();
        if (!this.aheadDim) this.overlay.show({ title: 'Flashing stopped', text: 'Picture restored.', color: '#46a758', autoHide: 2000 });
      }
    }

    engage(res) {
      this.protecting = true;
      if (this.overridden || this.aheadDim) { this.updateDim(); return; }   // already handled ahead of time
      const kind = res.red > res.general ? 'Red flashing' : 'Flashing';
      if (settings.liveAction === 'pause') {
        this.video.pause();
        this.overlay.show({
          title: `${kind} detected \u2014 video paused`,
          text: 'This part has rapid flashing that could trigger a seizure.',
          color: '#e5484d',
          buttons: [
            ['Skip ahead 5s', () => { this.video.currentTime = Math.min(this.video.duration || Infinity, this.video.currentTime + 5); this.resetProtection(); this.video.play(); }],
            ['Resume anyway', () => { this.overridden = true; this.overlay.hide(); this.video.play(); }],
          ],
        });
      } else {
        this.updateDim();
        this.overlay.show({
          title: `${kind} detected \u2014 video dimmed`,
          text: 'FlashGuard will bring the picture back when it stops.',
          color: '#e5484d',
          buttons: [['Show anyway', () => { this.overridden = true; this.updateDim(); this.overlay.hide(); }]],
        });
      }
    }

    // ---- sections found ahead of time (look-ahead or a check)
    foundSegments() {
      const k = this.key();
      const samples = [];
      const scan = savedScans.get(k);
      if (scan) samples.push(...scan.samples);
      const ahead = aheadMaps.get(k);
      if (ahead) samples.push(...ahead.samples);
      if (!samples.length) return scan || ahead ? [] : null;
      samples.sort((a, b) => a.t - b.t);
      return D.toSegments(samples, limit());
    }

    applyFound(t) {
      if (!settings.enabled) return;
      const segs = this.foundSegments();
      const LEAD = 0.15, TAIL = 0.2;   // a little margin so the first and last flash frames are covered
      const hit = segs && segs.find((s) => t >= s.start - LEAD && t <= s.end + TAIL);
      if (hit && settings.scanAction === 'skip') {
        this.video.currentTime = Math.min(this.video.duration, hit.end + 0.3);
        this.overlay.show({ title: `Skipped flashing (${fmt(hit.start)}\u2013${fmt(hit.end)})`, color: '#5b8def', autoHide: 2500 });
        return;
      }
      if (hit && !this.aheadDim) {
        this.aheadDim = true;
        this.aheadSeg = hit;
        this.updateDim();
        if (!this.overridden) {
          this.overlay.show({
            title: `Flashing (${fmt(hit.start)}\u2013${fmt(hit.end)}) \u2014 dimmed until it passes`,
            text: 'FlashGuard saw this coming and dimmed it before the first flash.',
            color: '#5b8def',
            buttons: [['Show anyway', () => { this.overridden = true; this.updateDim(); this.overlay.hide(); }]],
          });
        }
      } else if (!hit && this.aheadDim) {
        this.aheadDim = false;
        this.aheadEndedAt = t;
        this.aheadSeg = null;
        if (!this.protecting) this.overridden = false;
        this.updateDim();
        if (!this.protecting) this.overlay.show({ title: 'Flashing passed', text: 'Picture restored.', color: '#46a758', autoHide: 1800 });
      }
    }

    // ---- "Check this video first"
    startScan() {
      const v = this.video;
      if (this.unsupported) return { ok: false, error: 'This site doesn\u2019t let extensions read its video, so it can\u2019t be checked.' };
      if (!isFinite(v.duration) || v.duration <= 0) return { ok: false, error: 'Live streams can\u2019t be checked ahead of time. Live protection still works.' };
      if (this.scan) return { ok: true };
      this.resetProtection();
      this.scan = {
        samples: [], gaps: [], rate: 2, check: null, seen: 0,
        saved: { time: v.currentTime, muted: v.muted, rate: v.playbackRate },
      };
      measureRefresh().then((hz) => {
        if (!this.scan) return;
        this.scan.rate = speedFor(hz);
        v.playbackRate = this.scan.rate;
        this.showScanProgress(Math.min(1, (this.lastT || 0) / v.duration));
      });
      v.muted = true;
      const s = v.style;
      this.scan.savedFilter = [s.getPropertyValue('filter'), s.getPropertyPriority('filter')];
      s.setProperty('filter', 'brightness(0)', 'important');   // hidden while it plays
      this.reader.setWindow(this.viewWindow());
      this.reader.reset();
      v.currentTime = 0;
      v.playbackRate = this.scan.rate;
      if (!document.hidden) v.play().catch(() => {});
      this.showScanProgress(0);
      return { ok: true };
    }

    showScanProgress(p) {
      this.overlay.show({
        title: 'Checking this video for flashing\u2026',
        text: `It plays hidden and muted at ${this.scan ? this.scan.rate : 2}x speed. You won\u2019t see anything.` +
              (document.hidden ? ' Paused while this tab is in the background.' : ''),
        color: '#5b8def',
        progress: p,
        buttons: [['Cancel', () => this.finishScan(true)]],
      });
    }

    scanFrame(res) {
      const sc = this.scan;
      const v = this.video;
      if (sc.lastT !== undefined) sc.gaps.push(res.t - sc.lastT);
      sc.lastT = res.t;
      if (res.worst >= 3) sc.samples.push({ t: res.t, worst: res.worst, red: res.red, general: res.general, first: res.first, last: res.last });
      sc.seen += 1;
      if (v.playbackRate !== sc.rate) v.playbackRate = sc.rate;     // some players reset the speed
      // every 2 seconds of video: if frames are being dropped, slow down so no flash is missed
      const q = v.getVideoPlaybackQuality ? v.getVideoPlaybackQuality() : null;
      const snap = () => ({ t: res.t, seen: sc.seen, dropped: q ? q.droppedVideoFrames : 0, total: q ? q.totalVideoFrames : 0 });
      if (!sc.check) sc.check = snap();
      else if (res.t - sc.check.t >= 2) {
        const perSec = (sc.seen - sc.check.seen) / (res.t - sc.check.t);
        const dropped = q ? q.droppedVideoFrames - sc.check.dropped : 0;
        const total = q ? q.totalVideoFrames - sc.check.total : 0;
        if (sc.rate > 1 && perSec < 27 && total > 0 && dropped / total > 0.1) sc.rate -= 1;
        sc.check = snap();
      }
      if (sc.seen % 15 === 0) this.showScanProgress(Math.min(1, res.t / v.duration));
      if (res.t >= v.duration - 0.3) this.finishScan();
    }

    finishScan(cancelled = false) {
      const sc = this.scan;
      if (!sc) return;
      this.scan = null;
      const v = this.video;
      v.pause();
      v.playbackRate = sc.saved.rate;
      v.muted = sc.saved.muted;
      const [val, prio] = sc.savedFilter;
      if (val) v.style.setProperty('filter', val, prio); else v.style.removeProperty('filter');
      v.currentTime = sc.saved.time;
      this.reader.reset();
      if (cancelled) { this.overlay.hide(); return; }

      const gaps = sc.gaps.slice().sort((a, b) => a - b);
      const medianGap = gaps.length ? gaps[Math.floor(gaps.length / 2)] : 0;
      const choppy = medianGap > 0.05;   // fewer than ~20 frames per second of video were seen
      const entry = { samples: sc.samples, choppy, at: Date.now() };
      savedScans.set(this.key(), entry);
      if (hasChrome) chrome.storage.local.set({ [`scan:${this.key()}`]: entry });
      const segs = D.toSegments(sc.samples, limit());
      const play = () => { this.overlay.hide(); v.play(); };
      if (!segs.length) {
        this.overlay.show({
          title: 'No dangerous flashing found',
          text: choppy ? 'Note: your computer skipped some frames during the check, so very short flashes could be missed. Live protection stays on.' : 'Live protection stays on while you watch.',
          color: '#46a758',
          buttons: [['Play', play], ['Close', () => this.overlay.hide()]],
        });
      } else {
        const action = settings.scanAction === 'skip' ? 'skipped' : 'dimmed';
        this.overlay.show({
          title: `Flashing found in ${segs.length} ${segs.length === 1 ? 'place' : 'places'}`,
          text: `These parts will be ${action} automatically while you watch:`,
          color: '#e5484d',
          list: segs.map((s) => `${fmt(s.start)}\u2013${fmt(s.end)}${s.red ? ' (red flashing)' : ''}, up to ${s.peak} flashes/sec`),
          buttons: [['Play', play], ['Close', () => this.overlay.hide()]],
        });
      }
    }

    status() {
      const k = this.key();
      const scan = savedScans.get(k);
      const segs = scan ? D.toSegments(scan.samples, limit()) : null;
      return {
        hasVideo: true,
        unsupported: this.unsupported,
        protecting: this.protecting || this.aheadDim,
        scanning: !!this.scan,
        progress: this.scan && this.video.duration ? Math.min(1, this.lastT / this.video.duration) : null,
        live: !isFinite(this.video.duration),
        checked: !!segs,
        segments: (segs || []).map((s) => ({ start: fmt(s.start), end: fmt(s.end), red: s.red, peak: s.peak })),
        lookahead: lookahead.status(this),
      };
    }
  }

  // ================================================================= LOOK-AHEAD (main page side)
  //
  // On a YouTube watch page, loads the same video as a hidden, muted embed. The
  // copy plays faster than you watch, so it gets further ahead every second, and
  // sends back where the flashing is. Live protection covers the moment before it
  // gets ahead and any part it hasn't reached yet.
  const MAX_LEAD = 180, RESUME_LEAD = 120;   // don't run more than 3 minutes ahead

  function lookaheadUrl() {
    if (typeof window.__fgLookaheadUrl === 'function') return window.__fgLookaheadUrl();   // automated tests
    const host = location.hostname.replace(/^(www|m)\./, '');
    if (host !== 'youtube.com' || location.pathname !== '/watch') return null;
    const id = new URLSearchParams(location.search).get('v');   // read fresh: YouTube changes videos without reloading
    if (!id || !/^[\w-]{6,20}$/.test(id)) return null;
    return `https://www.youtube.com/embed/${id}?autoplay=1&mute=1&controls=0&disablekb=1&playsinline=1&rel=0&iv_load_policy=3&fg_lookahead=1`;
  }

  const lookahead = {
    frame: null, url: null, monitor: null, ready: false, error: null, paused: false, rate: null, lastTo: null, startedAt: 0, speed: 1.7,

    tick() {
      const url = settings.enabled && settings.lookahead ? lookaheadUrl() : null;
      const v = mainVideo();
      if (!url || !v || !isFinite(v.duration) || v.duration <= 0) { this.stop(); return; }
      watch(v);
      const m = monitors.get(v);
      if (m.unsupported) { this.stop(); return; }
      if (this.url !== url || this.monitor !== m) this.start(url, m);
      if (!this.ready) {
        if (!this.error && Date.now() - this.startedAt > 20000) { this.error = 'unavailable'; this.removeFrame(); }
        return;
      }
      this.send({ type: 'config', window: m.viewWindow(), rate: this.speed });
      // keep the copy ahead of you, but not too far
      const map = this.map(m);
      const t = v.currentTime;
      const range = map.covered.find((r) => t >= r[0] - 0.5 && t <= r[1] + 0.5);
      const lead = range ? range[1] - t : 0;
      if (!range && (this.lastTo === null || this.lastTo < t)) this.send({ type: 'seek', t });   // it fell behind: catch up from here
      if (lead > MAX_LEAD && !this.paused) { this.paused = true; this.send({ type: 'pause' }); }
      if (lead < RESUME_LEAD && this.paused) { this.paused = false; this.send({ type: 'play' }); }
    },

    start(url, m) {
      this.stop();
      this.url = url;
      this.monitor = m;
      this.ready = false;
      this.error = null;
      this.paused = false;
      this.lastTo = null;
      this.startedAt = Date.now();
      if (!aheadMaps.has(m.key())) aheadMaps.set(m.key(), { samples: [], covered: [] });
      const f = document.createElement('iframe');
      f.src = url;
      f.allow = 'autoplay';
      f.title = 'FlashGuard look-ahead (hidden)';
      f.setAttribute('aria-hidden', 'true');
      f.tabIndex = -1;
      // on the page (so the browser keeps playing it) but invisible and out of the way
      f.style.cssText = 'position:fixed;right:0;bottom:0;width:320px;height:180px;border:0;opacity:0;pointer-events:none;z-index:-1;';
      (document.body || document.documentElement).appendChild(f);
      this.frame = f;
      f.addEventListener('load', () => this.send({ type: 'config', window: m.viewWindow(), rate: this.speed }));
      measureRefresh().then((hz) => { this.speed = aheadSpeedFor(hz); });
    },

    removeFrame() { if (this.frame) this.frame.remove(); this.frame = null; this.ready = false; },

    stop() {
      this.removeFrame();
      this.url = null;
      this.monitor = null;
      this.error = null;
    },

    send(msg) { if (this.frame && this.frame.contentWindow) this.frame.contentWindow.postMessage({ __flashguard: 'control', ...msg }, '*'); },

    map(m) {
      const k = m.key();
      if (!aheadMaps.has(k)) aheadMaps.set(k, { samples: [], covered: [] });
      return aheadMaps.get(k);
    },

    onMessage(e) {
      if (!this.frame || e.source !== this.frame.contentWindow) return;
      const d = e.data;
      if (!d || d.__flashguard !== 'lookahead') return;
      if (d.type === 'ready') { this.ready = true; this.send({ type: 'config', window: this.monitor.viewWindow(), rate: this.speed }); return; }
      if (d.type === 'error') { this.error = d.reason; this.removeFrame(); return; }
      if (d.type === 'progress' && this.monitor) {
        this.ready = true;
        this.rate = d.rate;
        this.lastTo = d.to;
        const map = this.map(this.monitor);
        for (const s of d.samples || []) map.samples.push(s);
        if (typeof d.from === 'number' && typeof d.to === 'number' && d.to >= d.from) {
          map.covered = mergeRanges([...map.covered, [d.from, d.to]]);
        }
      }
    },

    onSeek(m) {
      if (m !== this.monitor || !this.ready) return;
      const t = m.video.currentTime;
      const map = this.map(m);
      if (!map.covered.some((r) => t >= r[0] && t <= r[1] - 1)) this.send({ type: 'seek', t });
    },

    status(m) {
      if (!settings.lookahead) return { state: 'off' };
      if (m !== this.monitor) return { state: lookaheadUrl() ? 'starting' : 'not-youtube' };
      if (this.error) return { state: 'unavailable', reason: this.error };
      if (!this.ready) return { state: 'starting' };
      const map = this.map(m);
      const t = m.video.currentTime;
      const range = map.covered.find((r) => t >= r[0] - 0.5 && t <= r[1] + 0.5);
      return { state: 'on', lead: range ? Math.max(0, range[1] - t) : 0, rate: this.rate, done: range && range[1] >= m.video.duration - 0.5 };
    },
  };
  window.addEventListener('message', (e) => lookahead.onMessage(e));

  // ---------------------------------------------------------------- finding videos
  function watch(video) {
    if (!(video instanceof HTMLVideoElement) || monitors.has(video)) return;
    monitors.set(video, new Monitor(video));
  }

  function mainVideo() {
    let best = null, bestScore = -1;
    for (const v of document.querySelectorAll('video')) {
      const r = v.getBoundingClientRect();
      const area = Math.max(0, r.width) * Math.max(0, r.height);
      const score = area * (v.paused ? 1 : 4) * (v.readyState > 0 ? 1 : 0.1);
      if (score > bestScore) { best = v; bestScore = score; }
    }
    return best && bestScore > 0 ? best : null;
  }

  document.querySelectorAll('video').forEach(watch);
  document.addEventListener('play', (e) => watch(e.target), true);
  document.addEventListener('loadedmetadata', (e) => watch(e.target), true);
  new MutationObserver((muts) => {
    for (const m of muts) for (const n of m.addedNodes) {
      if (n instanceof HTMLVideoElement) watch(n);
      else if (n.querySelectorAll) n.querySelectorAll('video').forEach(watch);
    }
  }).observe(document.documentElement, { childList: true, subtree: true });
  document.addEventListener('fullscreenchange', () => monitors.forEach((m) => { if (!m.overlay.box.hidden) m.overlay.mount(); }));

  // a check can't run in a background tab (the browser stops drawing frames), so it pauses and resumes
  document.addEventListener('visibilitychange', () => {
    monitors.forEach((m) => {
      if (!m.scan) return;
      if (document.hidden) m.video.pause();
      else { m.video.playbackRate = m.scan.rate; m.video.play().catch(() => {}); }
      m.showScanProgress(Math.min(1, (m.lastT || 0) / m.video.duration));
    });
  });

  // look-ahead follows the page (YouTube changes videos without reloading the page)
  if (window === window.top) setInterval(() => lookahead.tick(), 500);

  // load earlier "Check this video first" results
  if (hasChrome) {
    chrome.storage.local.get(null, (all) => {
      for (const [k, v] of Object.entries(all || {})) if (k.startsWith('scan:') && v.samples) savedScans.set(k.slice(5), v);
    });
  }

  // ---------------------------------------------------------------- messages from the popup
  function handle(msg) {
    const v = mainVideo();
    if (!v) return null;
    watch(v);
    const m = monitors.get(v);
    if (msg.type === 'status') return m.status();
    if (msg.type === 'check') return m.startScan();
    return null;
  }

  if (hasChrome) {
    chrome.runtime.onMessage.addListener((msg, sender, sendResponse) => {
      const res = handle(msg);
      if (res) sendResponse(res);   // frames without a video stay silent so the right frame answers
      return false;
    });
  }

  // used by the automated tests
  window.__flashguard = { handle, monitors, lookahead, aheadMaps, settings: () => settings, setSettings: (s) => Object.assign(settings, s) };
})();
