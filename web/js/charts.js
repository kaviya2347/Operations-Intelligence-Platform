/* OIP charts: hand-built SVG/HTML, coloured only through CSS tokens. */
'use strict';

const cssVar = n => getComputedStyle(document.documentElement).getPropertyValue(n).trim();
const SERIES = ['--s1', '--s2', '--s3', '--s4', '--s5', '--s6', '--s7', '--s8'];
const sc = i => `var(${SERIES[i % SERIES.length]})`;

function niceTicks(min, max, n = 5) {
  if (!isFinite(min) || !isFinite(max)) return [0, 1];
  if (min === max) { max = min + 1; }
  const span = max - min, step0 = span / n, mag = 10 ** Math.floor(Math.log10(step0)), err = step0 / mag;
  const step = (err >= 7.5 ? 10 : err >= 3.5 ? 5 : err >= 1.5 ? 2 : 1) * mag;
  const lo = Math.floor(min / step) * step, hi = Math.ceil(max / step) * step; const t = [];
  for (let v = lo; v <= hi + step / 2; v += step) t.push(+v.toFixed(10));
  return t;
}
function hex2rgb(h) { h = h.replace('#', ''); if (h.length === 3) h = h.split('').map(c => c + c).join(''); const n = parseInt(h, 16); return [n >> 16 & 255, n >> 8 & 255, n & 255]; }
function mix(a, b, t) { const x = hex2rgb(a), y = hex2rgb(b); return `rgb(${x.map((c, i) => Math.round(c + (y[i] - c) * t)).join(',')})`; }
function ramp(stops, t) { t = clamp(t, 0, 1) * (stops.length - 1); const i = Math.min(stops.length - 2, Math.floor(t)); return mix(stops[i], stops[i + 1], t - i); }
const SEQ = () => themeIsDark() ? ['#141c28', '#16304f', '#184f95', '#2a78d6', '#6da7ec', '#b7d3f6'] : ['#f0f5fc', '#cde2fb', '#86b6ef', '#3987e5', '#1c5cab', '#0d366b'];
const DIV = () => themeIsDark() ? ['#e66767', '#8a3a3a', '#2c2f35', '#245a9c', '#6da7ec'] : ['#c42f2f', '#f1a9a6', '#f0efec', '#86b6ef', '#1c5cab'];
const scaleSeq = (lo, hi) => v => v == null || !isFinite(v) ? null : ramp(SEQ(), (v - lo) / ((hi - lo) || 1));
const scaleDiv = (center, span) => v => v == null || !isFinite(v) ? null : ramp(DIV(), 0.5 + (v - center) / (2 * span));
function inkOn(bg) { if (!bg) return 'var(--ink-3)'; const m = bg.match(/\d+/g); if (!m) return 'var(--ink)'; const [r, g, b] = m.map(Number); return (0.299 * r + 0.587 * g + 0.114 * b) > 150 ? '#0D1117' : '#FFFFFF'; }

function mountChart(el, draw) {
  el.classList.add('chart'); el.dataset.redraw = '1'; el._redraw = draw; draw();
  if (window.ResizeObserver && !el._ro) { let w = el.clientWidth; el._ro = new ResizeObserver(() => { if (Math.abs(el.clientWidth - w) > 6) { w = el.clientWidth; draw(); } }); el._ro.observe(el); }
}
function tipHTML(title, rows, extra) { return `<b>${esc(title)}</b>${rows.map(r => `<div><span><i style="background:${r.color}"></i>${esc(r.name)}</span><span class="mono">${esc(r.value)}</span></div>`).join('')}${extra ? `<em>${esc(extra)}</em>` : ''}`; }

/* Combined bars + lines, two y axes, targets, markers, bands, hover. */
function comboChart(el, cfg) {
  mountChart(el, () => {
    const W = Math.max(280, el.clientWidth || 600), H = cfg.height || 260;
    const n = cfg.x.length; const hasR = cfg.series.some(s => s.axis === 'r');
    const lfmt = cfg.yl?.format || (v => F.compact(v)), rfmt = cfg.yr?.format || (v => F.compact(v));
    const vals = ax => cfg.series.filter(s => (s.axis || 'l') === ax).flatMap(s => {
      if (s.kind === 'bar' && cfg.stacked) return [];
      return s.values.filter(v => v != null && isFinite(v));
    });
    let stackMax = 0;
    if (cfg.stacked) for (let i = 0; i < n; i++) stackMax = Math.max(stackMax, sum(cfg.series.filter(s => s.kind === 'bar' && (s.axis || 'l') === 'l').map(s => s.values[i] || 0)));
    const lv = vals('l').concat(cfg.stacked ? [stackMax] : []).concat((cfg.targets || []).filter(t => (t.axis || 'l') === 'l').map(t => t.value));
    const rv = vals('r').concat((cfg.targets || []).filter(t => t.axis === 'r').map(t => t.value));
    const lt = niceTicks(cfg.yl?.min ?? Math.min(0, ...lv), cfg.yl?.max ?? Math.max(...lv, 0) * 1.04, cfg.ticks || 4);
    const rt = hasR ? niceTicks(cfg.yr?.min ?? Math.min(...rv), cfg.yr?.max ?? Math.max(...rv), cfg.ticks || 4) : null;
    const padL = 12 + Math.max(...lt.map(t => lfmt(t).length)) * 6.4, padR = hasR ? 12 + Math.max(...rt.map(t => rfmt(t).length)) * 6.4 : 12;
    const pt = 10, pb = 26, pw = W - padL - padR, ph = H - pt - pb;
    const bw = pw / n; const X = i => padL + bw * (i + 0.5);
    const Yl = v => pt + ph - (v - lt[0]) / (lt[lt.length - 1] - lt[0]) * ph;
    const Yr = rt ? (v => pt + ph - (v - rt[0]) / (rt[rt.length - 1] - rt[0]) * ph) : Yl;
    let g = '';
    lt.forEach(t => g += `<line class="grid-l" x1="${padL}" x2="${W - padR}" y1="${Yl(t)}" y2="${Yl(t)}"/><text class="ax" x="${padL - 6}" y="${Yl(t) + 3.5}" text-anchor="end">${lfmt(t)}</text>`);
    if (rt) rt.forEach(t => g += `<text class="ax" x="${W - padR + 6}" y="${Yr(t) + 3.5}">${rfmt(t)}</text>`);
    (cfg.bands || []).forEach(b => g += `<rect x="${padL + bw * b.from}" y="${pt}" width="${bw * (b.to - b.from + 1)}" height="${ph}" fill="${b.color || 'var(--band)'}"/>${b.label ? `<text class="axl" x="${padL + bw * b.from + 6}" y="${pt + 13}">${esc(b.label)}</text>` : ''}`);
    const every = Math.max(1, Math.ceil(n / Math.max(2, Math.floor(pw / (cfg.xTickW || 62)))));
    for (let i = 0; i < n; i += every) g += `<text class="ax" x="${X(i)}" y="${H - 8}" text-anchor="middle">${esc(cfg.xFormat ? cfg.xFormat(cfg.x[i], i) : cfg.x[i])}</text>`;
    const bars = cfg.series.filter(s => s.kind === 'bar'); const stackBase = new Array(n).fill(0);
    bars.forEach((s, si) => {
      const Y = (s.axis === 'r') ? Yr : Yl; const gw = cfg.stacked ? bw * 0.7 : bw * 0.72 / bars.length;
      s.values.forEach((v, i) => {
        if (v == null || !isFinite(v)) return;
        const x0 = cfg.stacked ? X(i) - gw / 2 : X(i) - bw * 0.36 + gw * si;
        const amin = s.axis === 'r' ? rt[0] : lt[0]; const y0 = cfg.stacked ? stackBase[i] : Math.max(0, amin); const y1 = cfg.stacked ? y0 + v : (amin > 0 ? Math.max(v, amin) : v);
        const top = Y(Math.max(y0, y1)), bot = Y(Math.min(y0, y1));
        const col = s.colorAt ? s.colorAt(i, v) : s.color;
        g += `<rect x="${x0.toFixed(1)}" y="${top.toFixed(1)}" width="${Math.max(1, gw - (cfg.stacked ? 0 : 1)).toFixed(1)}" height="${Math.max(0.5, bot - top).toFixed(1)}" fill="${col}" opacity="${s.opacity ?? 1}" rx="${cfg.stacked ? 0 : Math.min(2, gw / 4)}"/>`;
        if (cfg.stacked) stackBase[i] = y1;
      });
    });
    (cfg.targets || []).forEach(t => { const Y = t.axis === 'r' ? Yr : Yl; g += `<line class="target-l" x1="${padL}" x2="${W - padR}" y1="${Y(t.value)}" y2="${Y(t.value)}"/>${t.label ? `<text class="axl" x="${W - padR - 4}" y="${Y(t.value) - 5}" text-anchor="end">${esc(t.label)}</text>` : ''}`; });
    cfg.series.filter(s => s.kind !== 'bar').forEach(s => {
      const Y = s.axis === 'r' ? Yr : Yl; let d = '', pen = false;
      s.values.forEach((v, i) => {
        if (v == null || !isFinite(v)) { pen = false; return; }
        if (s.kind === 'step') { d += pen ? ` H${(X(i) - bw / 2).toFixed(1)} V${Y(v).toFixed(1)} H${(X(i) + bw / 2).toFixed(1)}` : ` M${(X(i) - bw / 2).toFixed(1)},${Y(v).toFixed(1)} H${(X(i) + bw / 2).toFixed(1)}`; }
        else d += `${pen ? ' L' : ' M'}${X(i).toFixed(1)},${Y(v).toFixed(1)}`;
        pen = true;
      });
      if (s.kind === 'area') { const first = s.values.findIndex(v => v != null), last = s.values.length - 1 - [...s.values].reverse().findIndex(v => v != null); g += `<path d="${d} L${X(last)},${Y(Math.max(lt[0], 0))} L${X(first)},${Y(Math.max(lt[0], 0))} Z" fill="${s.color}" opacity=".12"/>`; }
      g += `<path d="${d}" fill="none" stroke="${s.color}" stroke-width="${s.width || 2}" ${s.dash ? `stroke-dasharray="${s.dash}"` : ''} stroke-linejoin="round" stroke-linecap="round"/>`;
      if (s.dots) s.values.forEach((v, i) => { if (v != null) g += `<circle cx="${X(i)}" cy="${Y(v)}" r="2.6" fill="${s.color}"/>`; });
    });
    (cfg.markers || []).forEach(m => g += `<line x1="${X(m.index) - bw / 2}" x2="${X(m.index) - bw / 2}" y1="${pt - 2}" y2="${pt + ph}" stroke="var(--ink)" stroke-width="1.2" stroke-dasharray="2 3"/><text class="lbl" x="${X(m.index) - bw / 2 + 5}" y="${pt + 11}">${esc(m.label)}</text>`);
    g += `<line class="base-l" x1="${padL}" x2="${W - padR}" y1="${Yl(Math.max(lt[0], 0))}" y2="${Yl(Math.max(lt[0], 0))}"/>`;
    el.innerHTML = `<svg viewBox="0 0 ${W} ${H}" width="${W}" height="${H}" role="img" aria-label="${esc(cfg.aria || 'Chart')}">${g}<line class="hover-l" id="hl" x1="0" x2="0" y1="${pt}" y2="${pt + ph}" visibility="hidden"/><rect class="hit" x="${padL}" y="${pt}" width="${pw}" height="${ph + pb}"/></svg><div class="tip" hidden></div>`;
    const svg = el.querySelector('svg'), tip = el.querySelector('.tip'), hl = svg.querySelector('#hl'), hit = svg.querySelector('.hit');
    const idxAt = ev => { const r = svg.getBoundingClientRect(); return clamp(Math.floor(((ev.clientX - r.left) * W / r.width - padL) / bw), 0, n - 1); };
    hit.addEventListener('pointermove', ev => {
      const i = idxAt(ev); const r = svg.getBoundingClientRect(); const k = r.width / W;
      hl.setAttribute('x1', X(i)); hl.setAttribute('x2', X(i)); hl.setAttribute('visibility', 'visible');
      tip.hidden = false; tip.style.left = clamp(X(i) * k, 100, r.width - 100) + 'px'; tip.style.top = (pt + 8) * k + 'px';
      tip.innerHTML = tipHTML(cfg.tipTitle ? cfg.tipTitle(cfg.x[i], i) : cfg.x[i], cfg.series.filter(s => !s.noTip).map(s => ({ name: s.name, color: s.color, value: s.values[i] == null ? '—' : (s.axis === 'r' ? rfmt : lfmt)(s.values[i]) })), cfg.tipExtra ? cfg.tipExtra(i) : null);
      tip.style.transform = 'translate(-50%, 0)';
    });
    hit.addEventListener('pointerleave', () => { tip.hidden = true; hl.setAttribute('visibility', 'hidden'); });
    if (cfg.onClick) { hit.style.cursor = 'pointer'; hit.addEventListener('click', ev => cfg.onClick(idxAt(ev))); }
  });
}

/* Horizontal bars (rankings, importances, segments). */
function hbars(el, items, opts = {}) {
  const max = opts.max ?? Math.max(...items.map(i => Math.abs(i.value || 0)), 1e-9);
  el.innerHTML = `<div style="display:flex;flex-direction:column;gap:7px">${items.map(it => `<div style="display:grid;grid-template-columns:${opts.labelW || 130}px minmax(0,1fr) ${opts.valW || 64}px;gap:10px;align-items:center;font-size:12.5px" title="${esc(it.title || '')}">
    <span style="white-space:nowrap;overflow:hidden;text-overflow:ellipsis" class="ink2">${esc(it.label)}</span>
    <span style="height:${opts.h || 12}px;background:var(--surface-3);border-radius:4px;overflow:hidden;position:relative"><i style="display:block;height:100%;width:${clamp(Math.abs(it.value || 0) / max * 100, 0, 100)}%;background:${it.color || 'var(--s1)'};border-radius:4px"></i>${opts.target != null ? `<b style="position:absolute;top:-2px;bottom:-2px;left:${clamp(opts.target / max * 100, 0, 100)}%;width:2px;background:var(--ink)"></b>` : ''}</span>
    <span class="mono" style="text-align:right">${esc(opts.format ? opts.format(it.value) : it.value)}</span></div>`).join('')}</div>`;
}

/* Heatmap as a table. */
function heatmap(el, cfg) {
  const every = cfg.colEvery || 1;
  el.innerHTML = `<div class="tbl-wrap"><table class="heat" style="min-width:${cfg.minWidth || 0}px"><thead><tr><th class="k">${esc(cfg.corner || '')}</th>${cfg.cols.map((c, j) => `<th>${j % every === 0 ? esc(c) : ''}</th>`).join('')}${cfg.extra ? `<th style="width:${cfg.extraW || 60}px">${esc(cfg.extra.label)}</th>` : ''}</tr></thead>
    <tbody>${cfg.rows.map((r, i) => `<tr><td class="k" title="${esc(r)}">${esc(r)}</td>${cfg.values[i].map((v, j) => { const bg = cfg.color(v); return v == null ? `<td class="c e"></td>` : `<td class="c" data-r="${i}" data-c="${j}" style="background:${bg};color:${inkOn(bg)}" title="${esc(cfg.title ? cfg.title(i, j, v) : v)}">${cfg.text ? esc(cfg.text(v)) : ''}</td>`; }).join('')}${cfg.extra ? `<td class="mono" style="text-align:right;font-size:11.5px;color:var(--ink-2)">${esc(cfg.extra.value(i))}</td>` : ''}</tr>`).join('')}</tbody></table></div>`;
  if (cfg.onClick) $$('td.c[data-r]', el).forEach(td => { td.style.cursor = 'pointer'; td.onclick = () => cfg.onClick(+td.dataset.r, +td.dataset.c); });
}
function heatLegend(fn, lo, hi, fmt, label) {
  const stops = [0, .25, .5, .75, 1].map(t => fn(lo + (hi - lo) * t)).join(',');
  return `<div class="heat-leg"><span>${fmt(lo)}</span><i style="background:linear-gradient(90deg,${stops})"></i><span>${fmt(hi)}</span>${label ? `<span>${esc(label)}</span>` : ''}</div>`;
}

/* Scatter with optional reference lines. */
function scatter(el, cfg) {
  mountChart(el, () => {
    const W = Math.max(280, el.clientWidth || 500), H = cfg.height || 300, pts = cfg.points;
    const xt = niceTicks(cfg.xMin ?? Math.min(...pts.map(p => p.x)), cfg.xMax ?? Math.max(...pts.map(p => p.x)), 5);
    const yt = niceTicks(cfg.yMin ?? Math.min(...pts.map(p => p.y)), cfg.yMax ?? Math.max(...pts.map(p => p.y)), 4);
    const pl = 46, pr = 14, pt = 10, pb = 36, pw = W - pl - pr, ph = H - pt - pb;
    const X = v => pl + (v - xt[0]) / (xt[xt.length - 1] - xt[0]) * pw, Y = v => pt + ph - (v - yt[0]) / (yt[yt.length - 1] - yt[0]) * ph;
    let g = '';
    xt.forEach(t => g += `<line class="grid-l" x1="${X(t)}" x2="${X(t)}" y1="${pt}" y2="${pt + ph}"/><text class="ax" x="${X(t)}" y="${H - 20}" text-anchor="middle">${cfg.xFormat ? cfg.xFormat(t) : t}</text>`);
    yt.forEach(t => g += `<line class="grid-l" x1="${pl}" x2="${W - pr}" y1="${Y(t)}" y2="${Y(t)}"/><text class="ax" x="${pl - 6}" y="${Y(t) + 3.5}" text-anchor="end">${cfg.yFormat ? cfg.yFormat(t) : t}</text>`);
    if (cfg.refX != null) g += `<line class="target-l" x1="${X(cfg.refX)}" x2="${X(cfg.refX)}" y1="${pt}" y2="${pt + ph}"/>`;
    if (cfg.refY != null) g += `<line class="target-l" x1="${pl}" x2="${W - pr}" y1="${Y(cfg.refY)}" y2="${Y(cfg.refY)}"/>`;
    if (cfg.diag) g += `<line class="target-l" x1="${X(Math.max(xt[0], yt[0]))}" y1="${Y(Math.max(xt[0], yt[0]))}" x2="${X(Math.min(xt.at(-1), yt.at(-1)))}" y2="${Y(Math.min(xt.at(-1), yt.at(-1)))}"/>`;
    pts.forEach((p, i) => g += `<circle cx="${X(p.x).toFixed(1)}" cy="${Y(p.y).toFixed(1)}" r="${p.r || 4}" fill="${p.color || 'var(--s1)'}" fill-opacity="${p.opacity ?? .75}" stroke="var(--surface)" stroke-width="1" data-i="${i}" style="cursor:${cfg.onClick ? 'pointer' : 'default'}"/>`);
    if (cfg.xLabel) g += `<text class="axl" x="${pl + pw / 2}" y="${H - 3}" text-anchor="middle">${esc(cfg.xLabel)}</text>`;
    if (cfg.yLabel) g += `<text class="axl" x="${pl}" y="${pt + 10}" dx="6">${esc(cfg.yLabel)}</text>`;
    el.innerHTML = `<svg viewBox="0 0 ${W} ${H}" width="${W}" height="${H}" role="img" aria-label="${esc(cfg.aria || 'Scatter plot')}">${g}</svg><div class="tip" hidden></div>`;
    const tip = el.querySelector('.tip'), svg = el.querySelector('svg');
    $$('circle[data-i]', svg).forEach(c => {
      c.addEventListener('pointerenter', () => { const p = pts[+c.dataset.i]; const r = svg.getBoundingClientRect(), k = r.width / W; tip.hidden = false; tip.style.left = X(p.x) * k + 'px'; tip.style.top = Y(p.y) * k + 'px'; tip.innerHTML = p.tip || esc(p.label); });
      c.addEventListener('pointerleave', () => tip.hidden = true);
      if (cfg.onClick) c.addEventListener('click', () => cfg.onClick(pts[+c.dataset.i]));
    });
  });
}

function sparkline(values, opts = {}) {
  const v = values.filter(x => x != null && isFinite(x)); if (v.length < 2) return '';
  const w = opts.w || 64, h = opts.h || 22; const lo = Math.min(...v, opts.target ?? Infinity), hi = Math.max(...v, opts.target ?? -Infinity);
  const X = i => 1 + i / (values.length - 1) * (w - 2), Y = x => 2 + (1 - (x - lo) / ((hi - lo) || 1)) * (h - 4);
  let d = ''; values.forEach((x, i) => { if (x == null) return; d += `${d ? ' L' : 'M'}${X(i).toFixed(1)},${Y(x).toFixed(1)}`; });
  const last = values.length - 1 - [...values].reverse().findIndex(x => x != null);
  return `<svg width="${w}" height="${h}" viewBox="0 0 ${w} ${h}" aria-hidden="true">${opts.target != null ? `<line x1="0" x2="${w}" y1="${Y(opts.target)}" y2="${Y(opts.target)}" stroke="var(--ink-4)" stroke-dasharray="2 2"/>` : ''}<path d="${d}" fill="none" stroke="${opts.color || 'var(--s1)'}" stroke-width="1.5" stroke-linejoin="round"/><circle cx="${X(last)}" cy="${Y(values[last])}" r="2" fill="${opts.color || 'var(--s1)'}"/></svg>`;
}
function cellbar(value, frac, color, fmt) { return `<span class="cellbar"><span class="mono">${fmt ? fmt(value) : value}</span><span class="b"><i style="width:${clamp(frac * 100, 0, 100)}%;background:${color || 'var(--s1)'}"></i></span></span>`; }
