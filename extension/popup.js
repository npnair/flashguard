const DEFAULTS = { enabled: true, sensitivity: 'wcag', liveAction: 'dim', scanAction: 'dim' };
const $ = (id) => document.getElementById(id);

// ---- settings
chrome.storage.sync.get(DEFAULTS, (s) => {
  $('enabled').checked = s.enabled;
  $('sensitivity').value = s.sensitivity === 'early' ? 'sensitive' : s.sensitivity;
  $('liveAction').value = s.liveAction;
  $('scanAction').value = s.scanAction;
});
$('enabled').addEventListener('change', (e) => { chrome.storage.sync.set({ enabled: e.target.checked }); refresh(); });
for (const id of ['sensitivity', 'liveAction', 'scanAction']) {
  $(id).addEventListener('change', (e) => chrome.storage.sync.set({ [id]: e.target.value }));
}

// ---- talking to the page
async function send(msg) {
  const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
  if (!tab) return { error: 'no-tab' };
  try {
    const res = await chrome.tabs.sendMessage(tab.id, msg);
    return res || { error: 'no-video' };
  } catch (e) {
    return { error: 'not-loaded' };   // page was open before FlashGuard was installed, or it's a Chrome page
  }
}

function setStatus(text, cls = '') {
  $('status').textContent = text;
  $('status').className = cls;
}

async function refresh() {
  const s = await send({ type: 'status' });
  const btn = $('check');
  $('bar').hidden = true;
  $('segments').hidden = true;
  btn.disabled = true;

  if (s.error === 'not-loaded') return setStatus('Reload this page to use FlashGuard here. (It can\u2019t run on Chrome\u2019s own pages.)');
  if (s.error) return setStatus('No video found on this page.');
  if (!$('enabled').checked) setStatus('Protection is off.', 'bad');
  else if (s.unsupported) return setStatus('This site doesn\u2019t let extensions read its video, so FlashGuard can\u2019t protect it.', 'bad');
  else if (s.protecting) setStatus('Flashing detected right now. Protection is on.', 'bad');
  else setStatus('Live protection is on for this video.', 'ok');

  const fmt = (x) => `${Math.floor(x / 60)}:${String(Math.floor(x % 60)).padStart(2, '0')}`;

  if (s.scanning) {
    setStatus('Checking this video\u2026 (it plays hidden and muted)');
    $('bar').hidden = false;
    $('fill').style.width = `${Math.round((s.progress || 0) * 100)}%`;
    return;
  }
  if (s.live) { btn.textContent = 'Live streams can\u2019t be checked ahead'; return; }
  btn.disabled = false;
  btn.textContent = s.checked ? 'Check this video again' : 'Check this video first';
  if (s.checked) {
    if (!s.segments.length) setStatus('Checked: no dangerous flashing found.', 'ok');
    else {
      setStatus(`Checked: flashing found in ${s.segments.length} ${s.segments.length === 1 ? 'place' : 'places'}.`, 'bad');
      $('segments').hidden = false;
      $('segments').replaceChildren(...s.segments.map((g) => {
        const li = document.createElement('li');
        li.textContent = `${g.start}\u2013${g.end}${g.red ? ' (red)' : ''}, up to ${g.peak} flashes/sec`;
        return li;
      }));
    }
  }
}

$('check').addEventListener('click', async () => {
  const r = await send({ type: 'check' });
  if (r && r.error && r.error !== 'no-video') setStatus(r.error, 'bad');
  refresh();
});

refresh();
setInterval(refresh, 700);
