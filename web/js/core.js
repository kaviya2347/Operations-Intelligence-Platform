/* OIP core: utilities, API client (live server or offline snapshot), global state, metric engine, router, shared UI. */
'use strict';

const $ = (s, r = document) => r.querySelector(s);
const $$ = (s, r = document) => [...r.querySelectorAll(s)];
const esc = s => String(s ?? '').replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
const clamp = (x, a, b) => Math.max(a, Math.min(b, x));
const sum = a => a.reduce((s, x) => s + (x || 0), 0);
const mean = a => a.length ? sum(a) / a.length : null;
const lsGet = k => { try { return localStorage.getItem(k); } catch { return null; } };
const lsSet = (k, v) => { try { v == null ? localStorage.removeItem(k) : localStorage.setItem(k, v); } catch { } };

/* ---------- formatting ---------- */
const F = {
  int: v => v == null || !isFinite(v) ? '—' : Math.round(v).toLocaleString('en-IN'),
  compact: v => v == null || !isFinite(v) ? '—' : Math.abs(v) >= 1e5 ? (v / 1e5).toFixed(1) + ' L' : Math.abs(v) >= 1e3 ? (v / 1e3).toFixed(1) + 'k' : Math.round(v).toString(),
  pct: (v, d = 1) => v == null || !isFinite(v) ? '—' : (v * 100).toFixed(d) + '%',
  pct0: v => F.pct(v, 0),
  sec: v => { if (v == null || !isFinite(v)) return '—'; const m = Math.floor(v / 60), s = Math.round(v - m * 60); return m ? `${m}:${String(s).padStart(2, '0')}` : `${Math.round(v)}s`; },
  secs: v => v == null || !isFinite(v) ? '—' : Math.round(v) + 's',
  ratio: (v, d = 2) => v == null || !isFinite(v) ? '—' : v.toFixed(d),
  num: (v, d = 1) => v == null || !isFinite(v) ? '—' : Number(v).toFixed(d),
  date: s => { const d = new Date(s + 'T00:00:00'); return d.toLocaleDateString('en-GB', { day: 'numeric', month: 'short' }); },
  dateLong: s => { const d = new Date(s + 'T00:00:00'); return d.toLocaleDateString('en-GB', { weekday: 'short', day: 'numeric', month: 'short', year: 'numeric' }); },
};
function fmtMetric(id, v) {
  const m = M.reg[id]; if (!m) return F.num(v);
  return m.unit === 'pct' ? F.pct(v) : m.unit === 'sec' ? F.sec(v) : m.unit === 'count' ? F.int(v) : F.ratio(v);
}
function deltaText(id, cur, prev) {
  const m = M.reg[id]; if (cur == null || prev == null || !isFinite(cur) || !isFinite(prev)) return null;
  const d = cur - prev;
  const txt = m.unit === 'pct' ? `${d >= 0 ? '+' : '−'}${Math.abs(d * 100).toFixed(1)} pts` : m.unit === 'sec' ? `${d >= 0 ? '+' : '−'}${Math.abs(Math.round(d))}s` : `${d >= 0 ? '+' : '−'}${prev ? Math.abs(d / prev * 100).toFixed(1) + '%' : F.int(Math.abs(d))}`;
  const good = m.direction === 'up' ? d > 0 : m.direction === 'down' ? d < 0 : null;
  const flat = Math.abs(m.unit === 'pct' ? d * 100 : m.unit === 'sec' ? d : prev ? d / prev * 100 : d) < (m.unit === 'count' ? 0.5 : 0.05);
  return { txt, cls: flat || good === null ? 'flat' : good ? 'up' : 'down' };
}
const dk2s = k => { const s = String(k); return `${s.slice(0, 4)}-${s.slice(4, 6)}-${s.slice(6, 8)}`; };
const s2dk = s => +s.replaceAll('-', '');
const addDays = (s, n) => { const d = new Date(s + 'T00:00:00Z'); d.setUTCDate(d.getUTCDate() + n); return d.toISOString().slice(0, 10); };
const daysBetween = (a, b) => Math.round((new Date(b + 'T00:00:00Z') - new Date(a + 'T00:00:00Z')) / 864e5);

/* ---------- toast, overlay, dropdown ---------- */
function toast(msg, ms = 2800) { const t = document.createElement('div'); t.className = 'toast'; t.setAttribute('role', 'status'); t.textContent = msg; document.body.append(t); setTimeout(() => t.remove(), ms); }
function drawer(title, html, opts = {}) {
  const ov = document.createElement('div'); ov.className = 'overlay';
  ov.innerHTML = `<aside class="drawer" role="dialog" aria-modal="true" aria-label="${esc(title)}"><div class="drawer-h"><div><h3>${esc(title)}</h3>${opts.sub ? `<small class="muted">${esc(opts.sub)}</small>` : ''}</div><button class="btn btn-ghost icon-btn" data-close style="margin-left:auto" aria-label="Close">${ICON.x}</button></div><div class="drawer-b">${html}</div></aside>`;
  const close = () => { ov.remove(); document.removeEventListener('keydown', onKey); };
  const onKey = e => { if (e.key === 'Escape') close(); };
  ov.addEventListener('click', e => { if (e.target === ov || e.target.closest('[data-close]')) close(); });
  document.addEventListener('keydown', onKey); document.body.append(ov);
  setTimeout(() => ov.querySelector('[data-close]')?.focus(), 20);
  return { el: ov.querySelector('.drawer-b'), close };
}
function closeMenus() { $$('.menu.floating').forEach(m => m.remove()); }
document.addEventListener('click', e => { if (!e.target.closest('.menu') && !e.target.closest('[data-dd]')) closeMenus(); });
function dropdown(anchor, html, cls = '') {
  closeMenus(); const m = document.createElement('div'); m.className = 'menu floating ' + cls; m.innerHTML = html;
  anchor.parentElement.classList.add('dropdown'); anchor.parentElement.append(m); return m;
}
function seg(el, fn) { if (!el) return; el.addEventListener('click', e => { const b = e.target.closest('button'); if (!b || !el.contains(b)) return; el.querySelectorAll(':scope > button').forEach(x => x.setAttribute('aria-pressed', String(x === b))); fn(b.dataset.v, b); }); }

const ICON = {
  x: '<svg viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.7"><path d="m4 4 8 8M12 4l-8 8"/></svg>',
  menu: '<svg viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.6"><path d="M2.5 4h11M2.5 8h11M2.5 12h11"/></svg>',
  cal: '<svg viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.5"><rect x="2" y="3" width="12" height="11" rx="2"/><path d="M2 6.5h12M5.5 1.5v3M10.5 1.5v3"/></svg>',
  spark: '<svg viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.5"><path d="M8 1.5 9.6 6.4 14.5 8 9.6 9.6 8 14.5 6.4 9.6 1.5 8l4.9-1.6z"/></svg>',
  arrow: '<svg viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.6"><path d="M3 8h10M9 4l4 4-4 4"/></svg>',
  play: '<svg viewBox="0 0 16 16" fill="currentColor"><path d="M4.5 2.8v10.4L13 8z"/></svg>',
  down: '<svg viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.6"><path d="M8 2.5v8M4.5 7.5 8 11l3.5-3.5M3 13.5h10"/></svg>',
  sun: '<svg viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.5"><circle cx="8" cy="8" r="3"/><path d="M8 1v1.5M8 13.5V15M1 8h1.5M13.5 8H15M3 3l1 1M12 12l1 1M3 13l1-1M12 4l1-1"/></svg>',
  bell: '<svg viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.5"><path d="M4 11V7a4 4 0 0 1 8 0v4l1.3 1.5H2.7zM6.5 14a1.6 1.6 0 0 0 3 0"/></svg>',
  ext: '<svg viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.5"><path d="M9 2.5h4.5V7M13.5 2.5 7 9M12 9.5V13a.5.5 0 0 1-.5.5h-8A.5.5 0 0 1 3 13V5a.5.5 0 0 1 .5-.5H7"/></svg>',
};

/* ---------- API: live server or offline snapshot ---------- */
const API = {
  mode: 'live', user: lsGet('oip_user') || 'ops-admin', snap: null,
  async init() {
    try {
      const r = await fetch('api/health', { cache: 'no-store' });
      if (r.ok) { const j = await r.json(); if (j.ok) { this.mode = 'live'; return; } }
    } catch { }
    if (!window.OIP_SNAPSHOT) await new Promise(res => { const s = document.createElement('script'); s.src = 'static/snapshot.js'; s.onload = s.onerror = res; document.head.append(s); });
    if (window.OIP_SNAPSHOT) { this.mode = 'static'; this.snap = window.OIP_SNAPSHOT; if (!this.snap.users.some(u => u.id === this.user)) this.user = this.snap.users[0].id; return; }
    throw new Error('No API and no snapshot available. Run "python -m oip serve".');
  },
  async get(path) {
    if (this.mode === 'static') return StaticAPI.get(path);
    const r = await fetch('api/' + path, { headers: { 'X-OIP-User': this.user } });
    const j = await r.json().catch(() => ({}));
    if (!r.ok) { const e = new Error(j.detail || j.error || `Request failed (${r.status})`); e.status = r.status; throw e; }
    return j;
  },
  async post(path, body, opts) {
    if (this.mode === 'static') return StaticAPI.post(path, body, opts);
    const r = await fetch('api/' + path, { method: 'POST', headers: { 'content-type': 'application/json', 'X-OIP-User': this.user }, body: JSON.stringify(body || {}) });
    const j = await r.json().catch(() => ({}));
    if (!r.ok) { const e = new Error(j.detail || j.error || `Request failed (${r.status})`); e.status = r.status; throw e; }
    return j;
  },
};

/* ---------- state & metric engine ---------- */
const STATE = { meta: null, cube: null, agents: null, cache: {}, filters: null, route: 'overview', params: {} };
const M = { reg: {}, list: [] };

function initFilters() {
  const end = STATE.meta.period.end;
  const saved = (() => { try { return JSON.parse(lsGet('oip_filters')); } catch { return null; } })();
  STATE.filters = Object.assign({ preset: '30', start: addDays(end, -29), end, client: 'all', queues: null, channel: 'all' }, saved || {});
  applyPreset(STATE.filters.preset, true);
}
function applyPreset(p, silent) {
  const { start: ps, end: pe } = STATE.meta.period; const f = STATE.filters; f.preset = p;
  if (p === '7') { f.end = pe; f.start = addDays(pe, -6); }
  else if (p === '30') { f.end = pe; f.start = addDays(pe, -29); }
  else if (p === 'all') { f.start = ps; f.end = pe; }
  f.start = f.start < ps ? ps : f.start; f.end = f.end > pe ? pe : f.end;
  if (!silent) saveFilters();
}
function saveFilters() { lsSet('oip_filters', JSON.stringify(STATE.filters)); }
function queueById(id) { return STATE.meta.queues.find(q => q.queue_id === id); }
function selectedQueues(over = {}) {
  const f = Object.assign({}, STATE.filters, over);
  return STATE.meta.queues.filter(q => (f.client === 'all' || q.client_id === f.client) && (f.channel === 'all' || q.channel === f.channel) && (!f.queues || f.queues.includes(q.queue_id))).map(q => q.queue_id);
}
function prevRange(start, end) { const n = daysBetween(start, end) + 1; return { start: addDays(start, -n), end: addDays(start, -1) }; }

const Cube = {
  load(c) {
    this.n = c.n; this.d = c.data;
    const dates = new Map(STATE.meta.dates.map(d => [d.date_key, d]));
    this.dateStr = this.d.date_key.map(k => dk2s(k));
    this.weekday = this.d.date_key.map(k => dates.get(k)?.weekday);
  },
  rows({ start, end, queues }) {
    const s = s2dk(start), e = s2dk(end), qs = new Set(queues); const out = [];
    const dk = this.d.date_key, q = this.d.queue_id;
    for (let i = 0; i < this.n; i++) if (dk[i] >= s && dk[i] <= e && qs.has(q[i])) out.push(i);
    return out;
  },
  sums(rows, cols) { const o = {}; for (const c of cols) { const a = this.d[c]; let t = 0; for (const i of rows) t += a[i] || 0; o[c] = t; } return o; },
  group(rows, keyFn, cols) {
    const g = new Map();
    for (const i of rows) { const k = keyFn(i); let o = g.get(k); if (!o) { o = { _rows: 0 }; for (const c of cols) o[c] = 0; g.set(k, o); } o._rows++; for (const c of cols) o[c] += this.d[c][i] || 0; }
    return g;
  },
};
function metricCols(ids) { const s = new Set(); ids.forEach(id => { const m = M.reg[id]; m.num.forEach(t => s.add(t[0])); (m.den || []).forEach(t => s.add(t[0])); }); return [...s]; }
function metricValue(id, sums) {
  const m = M.reg[id]; const ev = terms => terms.reduce((t, [c, sg]) => t + sg * (sums[c] || 0), 0);
  const n = ev(m.num); if (!m.den) return n; const d = ev(m.den); return d ? n / d : null;
}
function compute(ids, rows) { const s = Cube.sums(rows, metricCols(ids)); const o = {}; ids.forEach(id => o[id] = metricValue(id, s)); return o; }
function targetFor(id, rows) {
  const key = { sl: ['sl_target', 'sl_den'], aht: ['aht_target_sec', 'handled'], abandon_rate: ['abandon_target', 'rt_offered'] }[id];
  if (!key) { const t = M.reg[id]?.target_key; return t && STATE.meta.targets[t] != null ? STATE.meta.targets[t] : null; }
  const g = Cube.group(rows, i => Cube.d.queue_id[i], [key[1]]); let w = 0, t = 0;
  g.forEach((o, qid) => { const q = queueById(qid); if (!q) return; w += o[key[1]]; t += o[key[1]] * q[key[0]]; });
  return w ? t / w : null;
}
function meetsTarget(id, v, t) { if (v == null || t == null) return null; const d = M.reg[id].direction; return d === 'up' ? v >= t : d === 'down' ? v <= t : Math.abs(v - t) <= 0.07; }

/* ---------- shared UI pieces ---------- */
function kpiTile(id, cur, prev, target, spark, opts = {}) {
  const m = M.reg[id]; const dl = deltaText(id, cur, prev); const ok = meetsTarget(id, cur, target);
  return `<div class="kpi" title="${esc(m.definition)}">
    <span class="l">${esc(opts.label || m.label)}</span>
    <span class="v">${fmtMetric(id, cur)}${m.unit === 'sec' ? '<small>m:ss</small>' : ''}</span>
    <span class="meta">${dl ? `<span class="delta ${dl.cls}">${dl.txt}</span>` : ''}${target != null ? `<span class="pill ${ok ? 'good' : 'crit'}">${ok ? '✓' : '✕'} ${m.unit === 'pct' ? F.pct0(target) : fmtMetric(id, target)}</span>` : ''}${opts.note ? `<span>${esc(opts.note)}</span>` : ''}</span>
    ${spark ? `<span class="spark">${spark}</span>` : ''}
  </div>`;
}
function statusCell(id, v, t) {
  const ok = meetsTarget(id, v, t);
  return `<span class="${ok == null ? '' : ok ? 'st-good' : 'st-bad'}">${fmtMetric(id, v)}</span>`;
}
function sortableTable(el, cols, rows, opts = {}) {
  let key = opts.sortKey || null, dir = opts.sortDir || -1;
  const draw = () => {
    const data = key ? rows.slice().sort((a, b) => { const x = a[key], y = b[key]; return (x == null) - (y == null) || (x > y ? 1 : x < y ? -1 : 0) * dir; }) : rows;
    el.innerHTML = `<div class="tbl-wrap"><table class="tbl"><thead><tr>${cols.map(c => `<th class="${c.num ? 'r' : ''}">${c.sort === false ? esc(c.label) : `<button data-k="${c.key}">${esc(c.label)}${key === c.key ? (dir > 0 ? ' ↑' : ' ↓') : ''}</button>`}</th>`).join('')}</tr></thead>
      <tbody>${data.map(r => `<tr class="${opts.onRow ? 'click' : ''} ${opts.selected && opts.selected(r) ? 'sel' : ''}" data-id="${esc(r[opts.idKey || 'id'] ?? '')}">${cols.map(c => `<td class="${c.num ? 'num' : ''} ${c.wrap ? 'wrap' : ''}">${c.render ? c.render(r) : esc(r[c.key] ?? '—')}</td>`).join('')}</tr>`).join('') || `<tr><td colspan="${cols.length}" class="empty">No rows</td></tr>`}</tbody></table></div>`;
    $$('th button', el).forEach(b => b.onclick = () => { const k = b.dataset.k; if (key === k) dir *= -1; else { key = k; dir = -1; } draw(); });
    if (opts.onRow) $$('tbody tr', el).forEach(tr => tr.onclick = () => opts.onRow(rows.find(r => String(r[opts.idKey || 'id']) === tr.dataset.id)));
  };
  draw();
}
function loading(el, h = 260) { el.innerHTML = `<div class="skeleton" style="min-height:${h}px"></div>`; }
function errBox(el, e) { el.innerHTML = `<div class="empty">${esc(e.message || e)}</div>`; }
function copilotLink(question, queue) { return `<button class="btn btn-sm" data-ask="${esc(question)}" data-q="${esc(queue || '')}">${ICON.spark}Ask copilot</button>`; }
document.addEventListener('click', e => { const b = e.target.closest('[data-ask]'); if (!b) return; go('copilot', { q: b.dataset.ask, queue: b.dataset.q || '' }); });

/* ---------- router & shell ---------- */
const PAGES = {};
function page(id, def) { PAGES[id] = def; }
function go(id, params = {}) { const qs = new URLSearchParams(params).toString(); location.hash = `#/${id}${qs ? '?' + qs : ''}`; }
function parseHash() { const h = location.hash.replace(/^#\/?/, ''); const [p, q] = h.split('?'); return { id: p || 'overview', params: Object.fromEntries(new URLSearchParams(q || '')) }; }
let RENDER_TOKEN = 0;
async function route() {
  const { id, params } = parseHash(); const pg = PAGES[id] || PAGES.overview;
  STATE.route = PAGES[id] ? id : 'overview'; STATE.params = params;
  $$('.nav a').forEach(a => a.toggleAttribute('aria-current', a.dataset.page === STATE.route) || (a.dataset.page === STATE.route ? a.setAttribute('aria-current', 'page') : a.removeAttribute('aria-current')));
  $$('.nav a').forEach(a => a.dataset.page === STATE.route ? a.setAttribute('aria-current', 'page') : a.removeAttribute('aria-current'));
  $('#pgTitle').textContent = pg.title; $('#pgSub').textContent = pg.sub || '';
  renderFilters(pg);
  $('#app').classList.remove('nav-open');
  const token = ++RENDER_TOKEN; const v = $('#view'); v.innerHTML = '';
  try { await pg.render(v, params, () => token === RENDER_TOKEN); } catch (e) { console.error(e); errBox(v, e); }
  window.scrollTo({ top: 0 });
}
function rerender() { route(); }

function renderFilters(pg) {
  const host = $('#filters'); const f = STATE.filters; const show = pg.filters || [];
  if (!show.length) { host.innerHTML = ''; return; }
  const qs = STATE.meta.queues; const cls = STATE.meta.clients;
  host.innerHTML = `
    ${show.includes('date') ? `<div class="seg" id="fPreset">${[['7', '7 days'], ['30', '30 days'], ['all', 'Full period'], ['custom', 'Custom']].map(([v, l]) => `<button data-v="${v}" aria-pressed="${f.preset === v}">${l}</button>`).join('')}</div>
      <span id="fCustom" ${f.preset === 'custom' ? '' : 'hidden'} style="display:inline-flex;gap:4px;align-items:center"><input type="date" id="fStart" value="${f.start}" min="${STATE.meta.period.start}" max="${STATE.meta.period.end}"><span class="muted">→</span><input type="date" id="fEnd" value="${f.end}" min="${STATE.meta.period.start}" max="${STATE.meta.period.end}"></span>` : ''}
    ${show.includes('client') ? `<select id="fClient" aria-label="Client"><option value="all">All clients</option>${cls.map(c => `<option value="${c.client_id}" ${f.client === c.client_id ? 'selected' : ''}>${esc(c.client_name)}</option>`).join('')}</select>` : ''}
    ${show.includes('channel') ? `<select id="fChannel" aria-label="Channel"><option value="all">All channels</option>${['Voice', 'Chat', 'Email', 'Back office'].filter(c => qs.some(q => q.channel === c)).map(c => `<option ${f.channel === c ? 'selected' : ''}>${c}</option>`).join('')}</select>` : ''}
    ${show.includes('queues') ? `<button class="btn" data-dd id="fQueues">${f.queues ? `${f.queues.length} queue${f.queues.length > 1 ? 's' : ''}` : 'All queues'}<svg viewBox="0 0 10 6" width="10" height="6"><path d="M1 1l4 4 4-4" fill="none" stroke="currentColor" stroke-width="1.5"/></svg></button>` : ''}
    <span class="muted" style="font-size:12px;white-space:nowrap">${F.date(f.start)} – ${F.date(f.end)}</span>`;
  seg($('#fPreset'), v => { if (v === 'custom') { f.preset = 'custom'; $('#fCustom').hidden = false; saveFilters(); return; } applyPreset(v); rerender(); });
  $('#fStart')?.addEventListener('change', e => { f.start = e.target.value; if (f.start > f.end) f.end = f.start; saveFilters(); rerender(); });
  $('#fEnd')?.addEventListener('change', e => { f.end = e.target.value; if (f.end < f.start) f.start = f.end; saveFilters(); rerender(); });
  $('#fClient')?.addEventListener('change', e => { f.client = e.target.value; f.queues = null; saveFilters(); rerender(); });
  $('#fChannel')?.addEventListener('change', e => { f.channel = e.target.value; f.queues = null; saveFilters(); rerender(); });
  $('#fQueues')?.addEventListener('click', e => {
    e.stopPropagation();
    const avail = STATE.meta.queues.filter(q => (f.client === 'all' || q.client_id === f.client) && (f.channel === 'all' || q.channel === f.channel));
    const m = dropdown(e.currentTarget, `<button data-all><b>All queues</b></button><hr>${avail.map(q => `<label><input type="checkbox" value="${q.queue_id}" ${!f.queues || f.queues.includes(q.queue_id) ? 'checked' : ''}><span><b style="font-weight:550">${esc(q.code)}</b> <small>${esc(q.name)} · ${q.channel}</small></span></label>`).join('')}<hr><button data-apply class="btn btn-primary btn-sm" style="justify-content:center">Apply</button>`);
    m.querySelector('[data-all]').onclick = () => { f.queues = null; saveFilters(); closeMenus(); rerender(); };
    m.querySelector('[data-apply]').onclick = () => { const v = $$('input:checked', m).map(i => i.value); f.queues = v.length && v.length < avail.length ? v : null; saveFilters(); closeMenus(); rerender(); };
  });
}

function setTheme(t) { lsSet('oip_theme', t === 'system' ? null : t); if (t === 'system') delete document.documentElement.dataset.theme; else document.documentElement.dataset.theme = t; rerender(); }
function themeIsDark() { const t = document.documentElement.dataset.theme; return t ? t === 'dark' : matchMedia('(prefers-color-scheme: dark)').matches; }

async function loadData() {
  STATE.meta = await API.get('meta');
  M.list = STATE.meta.metrics; M.reg = Object.fromEntries(M.list.map(m => [m.id, m]));
  Cube.load(await API.get('cube'));
  STATE.cache = {};
  if (!STATE.filters) initFilters();
  STATE.filters.queues = STATE.filters.queues ? STATE.filters.queues.filter(q => queueById(q)) : null;
  if (STATE.filters.queues && !STATE.filters.queues.length) STATE.filters.queues = null;
  if (STATE.filters.client !== 'all' && !STATE.meta.clients.some(c => c.client_id === STATE.filters.client)) STATE.filters.client = 'all';
}
async function cached(key, fn) { if (!(key in STATE.cache)) STATE.cache[key] = fn(); return STATE.cache[key]; }

function renderShellMeta() {
  const u = STATE.meta.user; const llm = STATE.meta.llm || {};
  $('#userBtn').innerHTML = `<span class="avatar">${esc(u.name.split(' ').map(w => w[0]).join('').slice(0, 2))}</span><span style="text-align:left;line-height:1.2"><b style="font-size:12.5px;display:block">${esc(u.name)}</b><small class="muted" style="font-size:11px">${esc(u.role)}</small></span>`;
  $('#envDot').className = 'dot ' + (API.mode === 'live' ? 'on' : 'warn');
  $('#envT').textContent = API.mode === 'live' ? 'Live · local API' : 'Offline snapshot';
  $('#envS').textContent = API.mode === 'live' ? `Copilot: ${llm.provider === 'extractive' ? 'extractive (no LLM key)' : llm.provider + ' · ' + llm.model}` : 'Precomputed build; SQL lab needs the local server';
  $$('.nav a[data-role]').forEach(a => a.hidden = !a.dataset.role.split(',').includes(u.role));
}

async function boot() {
  const th = lsGet('oip_theme'); if (th) document.documentElement.dataset.theme = th;
  $('#menuBtn').onclick = () => $('#app').classList.toggle('nav-open');
  $('#scrim').onclick = () => $('#app').classList.remove('nav-open');
  $('#themeBtn').onclick = () => setTheme(themeIsDark() ? 'light' : 'dark');
  $('#userBtn').onclick = async e => {
    e.stopPropagation();
    const users = await API.get('users');
    const m = dropdown(e.currentTarget, `<div style="padding:6px 9px 4px" class="eyebrow">View the platform as</div>${users.map(u => `<button data-u="${u.id}"><span class="avatar">${esc(u.name.split(' ').map(w => w[0]).join('').slice(0, 2))}</span><span><b style="font-weight:550">${esc(u.name)}</b><small>${esc(u.role)} · ${esc(u.title)}${u.queues ? ' · rows limited to ' + u.queues.length + ' queue(s)' : ''}</small></span>${u.id === API.user ? '<span style="margin-left:auto">✓</span>' : ''}</button>`).join('')}`, 'left up');
    $$('[data-u]', m).forEach(b => b.onclick = async () => { API.user = b.dataset.u; lsSet('oip_user', API.user); closeMenus(); STATE.filters = null; lsSet('oip_filters', null); await loadData(); renderShellMeta(); toast(`Viewing as ${STATE.meta.user.name}`); rerender(); });
  };
  try { await API.init(); await loadData(); }
  catch (e) { $('#view').innerHTML = `<div class="empty" style="padding:80px 20px"><b style="font-size:16px;color:var(--ink)">The platform isn't running yet</b><p style="margin-top:8px">${esc(e.message)}</p><p class="mono" style="margin-top:12px">python -m oip build &amp;&amp; python -m oip serve</p></div>`; return; }
  renderShellMeta();
  const al = await API.get('alerts').catch(() => ({ incidents: [] }));
  const n = al.incidents.filter(i => i.severity === 'critical').length; $('#alertBadge').textContent = n || ''; $('#alertBadge').hidden = !n;
  window.addEventListener('hashchange', route);
  let rt; window.addEventListener('resize', () => { clearTimeout(rt); rt = setTimeout(() => $$('.chart[data-redraw]').forEach(c => c._redraw && c._redraw()), 150); });
  matchMedia('(prefers-color-scheme: dark)').addEventListener?.('change', rerender);
  route();
}
