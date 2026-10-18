/* Data pages: pipeline & quality, exploratory analysis, catalog & governance, SQL lab, settings, about. */
'use strict';

const SEV_PILL = { high: 'crit', medium: 'warn', low: '' };
const LOG_TAG = d => `<span class="tag" title="Daily activity log entry">log ${esc(d)}</span>`;

/* ---------------- Data pipeline & quality ---------------- */
page('quality', {
  title: 'Data pipeline & quality', sub: 'Profiling, cleaning rules, outliers and reconciliation to source', filters: [],
  async render(v, params, alive) {
    let d; try { d = await cached('quality', () => API.get('quality')); } catch (e) { errBox(v, e); return; }
    if (!alive()) return;
    const P = d.profile, C = d.cleaning, R = d.reconciliation; const cur = R.current, v1 = R.v1_rule;
    const step = id => C.steps.find(s => s.rule_id === id) || {};
    const wc = C.warehouse_counts || {};
    v.innerHTML = `<div class="section-h"><div><span class="eyebrow">Ingest → profile → clean → reconcile → load ${LOG_TAG('10–13 Jun')}</span><h1>Can we trust the numbers?</h1><p>Every source extract lands in staging with PII already masked, is profiled, passes through numbered cleaning rules that log the rows they touch, and is reconciled against the source system's own daily report before the warehouse is loaded.</p></div></div>
      <div class="card" style="margin-bottom:14px"><div class="card-b"><div class="flow">
        ${[['Source extracts', F.int(C.ingest?.rows), `${C.ingest?.tables || 15} files · batch ${esc(C.ingest?.batch_id || '')}`],
           ['Staging', `${P.tables.length} profiled`, 'PII hashed and masked on load'],
           ['Cleaning', `${C.steps.length} rules`, `${F.int(step('R02').rows_affected)} duplicates removed`],
           ['Reconciliation', `${cur.matched}/${cur.rows}`, 'queue-days match the source report'],
           ['Warehouse', F.int(wc.fact_interaction), 'contacts in fact_interaction'],
           ['Reporting cube', F.int(wc.rpt_interval_cube), 'queue × day × half-hour rows']].map(([t, b, s], i) => `${i ? `<span class="flow-arrow">${ICON.arrow}</span>` : ''}<div class="flow-step"><small>${t}</small><b>${b}</b><span>${s}</span></div>`).join('')}
      </div></div></div>
      <section class="kpis" style="margin-bottom:14px">
        <div class="kpi"><span class="l">Duplicates removed</span><span class="v">${F.int(step('R02').rows_affected)}</span><span class="meta">composite business key</span></div>
        <div class="kpi"><span class="l">Label variants mapped</span><span class="v">${F.int(step('R03').rows_affected)}</span><span class="meta">${esc((step('R03').decision || '').split(';')[0])}</span></div>
        <div class="kpi"><span class="l">Timestamps re-parsed</span><span class="v">${F.int(step('R01').rows_affected)}</span><span class="meta">day-first format</span></div>
        <div class="kpi"><span class="l">Outliers capped</span><span class="v">${F.int(C.outliers?.capped)}</span><span class="meta">${F.int(C.outliers?.kept_long)} long calls kept</span></div>
        <div class="kpi"><span class="l">Reconciliation variance</span><span class="v">${F.int(cur.total_answered_clean - cur.total_answered_source)}</span><span class="meta"><span class="pill good">✓ ${cur.matched}/${cur.rows} queue-days</span></span></div>
        <div class="kpi"><span class="l">Bug caught</span><span class="v">${F.int(v1.answered_variance_total)}</span><span class="meta">answered contacts lost by the v1 rule</span></div>
      </section>
      <div class="grid">
        <section class="card c12"><div class="card-h"><h3>Profiling findings</h3><span class="sub">what the raw extracts looked like before any rule ran</span><div class="r">${LOG_TAG('10 Jun')}</div></div><div class="card-b flush" id="q1"></div></section>
        <section class="card c12"><div class="card-h"><h3>Cleaning rules</h3><span class="sub">each rule is a function that logs rows before, after and affected</span><div class="r">${LOG_TAG('11–13 Jun')}</div></div><div class="card-b flush" id="q2"></div></section>
        <section class="card c7"><div class="card-h"><h3>Handle-time tail before and after treatment</h3><span class="sub">voice, answered, 12 minutes and over; bins below 12 minutes are unchanged</span><div class="r">${LOG_TAG('12 Jun')}</div></div><div class="card-b"><div id="q3"></div><div class="legend" style="margin-top:6px"><span><i style="background:var(--s2);opacity:.55"></i>Before (raw)</span><span><i style="background:var(--s1)"></i>After capping</span><span>${F.int(C.outliers?.capped)} unclosed sessions leave the 60m+ bin and land at their queue's P99</span></div></div></section>
        <section class="card c5"><div class="card-h"><h3>Why only some were capped</h3></div><div class="card-b"><div class="narr">
          <p>The interquartile-range rule flagged ${F.int((C.outliers?.capped || 0) + (C.outliers?.kept_long || 0))} handle times as extreme, up to ${F.int(C.outliers?.max_before)} seconds.</p>
          <p>Matching them to agent session logs showed ${F.int(C.outliers?.capped)} had no logout event: the agent never closed the session, so the clock kept running. Those were capped at the queue's 99th percentile (SOP-DATA-05).</p>
          <p>The other ${F.int(C.outliers?.kept_long)} had normal session closes. They are genuinely long, complex contacts and were kept: removing them would understate AHT.</p>
          <p>Treatment ran only after the rule was approved; before that, outliers were flagged, not changed.</p></div></div></section>
        <section class="card c7"><div class="card-h"><h3>Reconciliation to the source daily report</h3><span class="sub">answered contacts, three sample dates</span><div class="r">${LOG_TAG('13 Jun')}</div></div><div class="card-b flush" id="q4"></div></section>
        <section class="card c5"><div class="card-h"><h3>The variance that found a bug</h3></div><div class="card-b"><div class="narr">
          <p>The first version of the cleaning script dropped answered contacts that had a blank agent login (${F.int(-v1.answered_variance_total)} contacts over the period).</p>
          <p>Reconciling three sample dates against the dialler's own daily report showed answered counts a few short each day. Tracing the gap led to that rule.</p>
          <p>The fix (R06) keeps the rows and flags them <span class="mono">agent_missing</span>: they count for the queue, but not for any agent. After the fix all ${cur.rows} queue-days reconcile exactly.</p></div>
          <div class="stat-row" style="margin-top:12px"><div><b>${F.int(cur.total_offered_source)}</b><span>offered, source</span></div><div><b>${F.int(cur.total_offered_clean)}</b><span>offered, warehouse</span></div><div><b>${F.int(cur.total_answered_clean)}</b><span>answered, warehouse</span></div></div></div></section>
      </div>`;
    sortableTable($('#q1'), [
      { key: 'severity', label: 'Severity', render: f => `<span class="pill ${SEV_PILL[f.severity]}">${f.severity}</span>` },
      { key: 'table', label: 'Table', render: f => `<span class="mono" style="font-size:12px">${esc(f.table)}</span>` },
      { key: 'column', label: 'Column', render: f => `<span class="mono" style="font-size:12px">${esc(f.column)}</span>` },
      { key: 'finding', label: 'Finding', wrap: true },
      { key: 'rule', label: 'Handled by', sort: false, render: f => { const r = { duplicate: 'R02', label: 'R03', format: 'R01', negative: 'R04', missing: f.column === 'hold_sec' ? 'R05' : 'R10', extreme: 'R08', spellings: 'R10', outside: 'R12' }; const k = Object.keys(r).find(k => f.finding.includes(k)); return k ? `<span class="tag">${r[k]}</span>` : ''; } },
    ], P.findings.map((f, i) => ({ ...f, id: i, severity: f.severity })), { sortKey: 'severity', sortDir: 1, onRow: f => profileDrawer(P, f.table) });
    sortableTable($('#q2'), [
      { key: 'rule_id', label: 'Rule', render: s => `<b class="mono">${s.rule_id}</b>` },
      { key: 'name', label: 'Step', render: s => `<b style="font-weight:550">${esc(s.name)}</b><div class="muted" style="font-size:12px;white-space:normal">${esc(s.description)}</div>`, wrap: true },
      { key: 'rows_before', label: 'Before', num: true, render: s => F.int(s.rows_before) },
      { key: 'rows_after', label: 'After', num: true, render: s => F.int(s.rows_after) },
      { key: 'rows_affected', label: 'Affected', num: true, render: s => `<b>${F.int(s.rows_affected)}</b>` },
      { key: 'decision', label: 'Decision and history', sort: false, wrap: true, render: s => `<span style="font-size:12.5px">${esc(s.decision)}</span>${s.history ? `<div class="muted" style="font-size:12px;margin-top:3px">${esc(s.history)}</div>` : ''}` },
    ], C.steps.map(s => ({ ...s, id: s.rule_id })), { sortKey: 'rule_id', sortDir: 1 });
    const o = C.outliers; if (o) {
      const from = o.bins.findIndex(b => b >= 720); const lab = o.bins.slice(from).map(b => b >= 3600 ? '60m+' : `${b / 60}m`);
      comboChart($('#q3'), { x: lab, height: 240, xTickW: 34, series: [
        { name: 'Before', values: o.before.slice(from), kind: 'bar', color: 'var(--s2)', opacity: .55 },
        { name: 'After', values: o.after.slice(from), kind: 'bar', color: 'var(--s1)' }], yl: { format: F.compact }, tipTitle: l => `Handle time ${l}`,
        tipExtra: i => { const d = o.after[from + i] - o.before[from + i]; return d ? `${d > 0 ? '+' : ''}${F.int(d)} contacts after treatment` : 'unchanged'; } });
    }
    const rows = R.sample_dates.map(dt => { const c = cur.by_sample_date.find(x => x.date === dt), b = v1.by_sample_date.find(x => x.date === dt); return { id: dt, date: dt, src: c.answered_source, cur: c.answered_clean, v1: b.answered_clean, v1var: b.answered_variance, curvar: c.answered_variance }; });
    sortableTable($('#q4'), [
      { key: 'date', label: 'Date', render: r => F.dateLong(r.date) },
      { key: 'src', label: 'Source report', num: true, render: r => F.int(r.src) },
      { key: 'v1', label: 'v1 pipeline', num: true, render: r => F.int(r.v1) },
      { key: 'v1var', label: 'v1 variance', num: true, render: r => `<span class="st-bad">${r.v1var}</span>` },
      { key: 'cur', label: 'Fixed pipeline', num: true, render: r => F.int(r.cur) },
      { key: 'curvar', label: 'Variance', num: true, render: r => `<span class="st-good">${r.curvar}</span>` },
    ], rows, { sortKey: 'date', sortDir: 1 });
  },
});
function profileDrawer(P, table) {
  const t = P.tables.find(x => x.table === table); if (!t) return;
  drawer(table, `<p class="muted" style="font-size:12.5px">${F.int(t.rows)} rows · ${t.columns.length} columns</p><div class="tbl-wrap"><table class="tbl"><thead><tr><th>Column</th><th>Type</th><th class="r">Null %</th><th class="r">Distinct</th><th>Notes</th></tr></thead><tbody>${t.columns.map(c => `<tr><td class="mono" style="font-size:12px">${esc(c.column)}</td><td>${esc(c.type)}</td><td class="num ${c.null_pct > 2 ? 'st-bad' : ''}">${F.num(c.null_pct, 2)}</td><td class="num">${F.int(c.distinct)}</td><td class="wrap" style="font-size:12px">${c.top ? 'Top: ' + Object.entries(c.top).slice(0, 6).map(([k, n]) => `<span class="tag">${esc(k)}</span> ${F.int(n)}`).join(' ') : ''}${c.alt_format_rows ? `${F.int(c.alt_format_rows)} rows in another format` : ''}${c.min != null && !c.top ? ` ${esc(c.min)} → ${esc(c.max)}` : ''}${c.negative ? ` · ${F.int(c.negative)} negative` : ''}</td></tr>`).join('')}</tbody></table></div>`, { sub: 'Staging profile' });
}

/* ---------------- Exploratory analysis ---------------- */
page('eda', {
  title: 'Exploratory analysis', sub: 'Distributions, drivers of handle time, load patterns and correlations', filters: [],
  async render(v, params, alive) {
    const e = await cached('eda', () => API.get('eda')); if (!alive()) return;
    const D = e.distributions;
    v.innerHTML = `<div class="section-h"><div><span class="eyebrow">Full period, all clients ${LOG_TAG('15 Jun')}</span><h1>Exploratory analysis</h1><p>Before building any metric or model: what the data looks like, where handle time varies, when the load arrives and which KPIs move together.</p></div></div>
      <div class="card" style="margin-bottom:14px"><div class="card-h"><h3>What stood out</h3></div><div class="card-b"><div class="narr">${e.observations.map(o => `<p>${esc(o)}</p>`).join('')}</div></div></div>
      <div class="grid">
        <section class="card c6"><div class="card-h"><h3>Handle time</h3><span class="sub">answered contacts, 1-minute bins</span></div><div class="card-b" id="e1"></div></section>
        <section class="card c6"><div class="card-h"><h3>Wait time before answer</h3><span class="sub">real-time channels, 10-second bins</span></div><div class="card-b" id="e2"></div></section>
        <section class="card c8"><div class="card-h"><h3>Handle time by queue</h3><span class="sub">P5–P95 whiskers, interquartile box, median line, mean dot</span></div><div class="card-b" id="e3"></div></section>
        <section class="card c4"><div class="card-h"><h3>CSAT responses</h3><span class="sub">score 1–5</span></div><div class="card-b" id="e4"></div></section>
        <section class="card c6"><div class="card-h"><h3>Median handle time by tenure</h3><span class="sub">seconds; tenure at contact date</span></div><div class="card-b" id="e5"></div></section>
        <section class="card c6"><div class="card-h"><h3>Median handle time by shift</h3><span class="sub">seconds</span></div><div class="card-b" id="e6"></div></section>
        <section class="card c7"><div class="card-h"><h3>When the load arrives</h3><span class="sub">${esc(e.load_heatmap.note)}</span><div class="r" id="e7l"></div></div><div class="card-b" id="e7"></div></section>
        <section class="card c5"><div class="card-h"><h3>Which KPIs move together</h3><span class="sub">Pearson r, daily, within queue</span></div><div class="card-b" id="e8"></div></section>
      </div>`;
    const hist = (el, d, unit, step) => { const lab = d.edges.slice(0, -1).map(x => unit === 'min' ? `${Math.round(x / 60)}m` : `${x}s`); comboChart(el, { x: lab, height: 220, xTickW: 36, series: [{ name: 'Contacts', values: d.counts, kind: 'bar', color: 'var(--s1)' }], yl: { format: F.compact }, tipTitle: (l, i) => `${l} – ${unit === 'min' ? Math.round(d.edges[i + 1] / 60) + 'm' : d.edges[i + 1] + 's'}` }); };
    hist($('#e1'), D.handle_sec, 'min'); hist($('#e2'), D.wait_sec_answered, 'sec');
    boxPlot($('#e3'), Object.entries(e.aht_box_by_queue).map(([k, b]) => ({ label: k, ...b })).sort((a, b) => b.median - a.median));
    const cs = D.csat; const tot = sum(cs.map(c => c.n));
    hbars($('#e4'), cs.slice().reverse().map(c => ({ label: `${c.score} ${'★'.repeat(c.score)}`, value: c.n / tot, color: c.score >= 4 ? 'var(--good)' : c.score === 3 ? 'var(--ink-4)' : 'var(--crit)' })), { format: F.pct0, labelW: 90 });
    $('#e4').insertAdjacentHTML('beforeend', `<p class="muted" style="font-size:12px;margin-top:12px">${F.int(tot)} valid responses. CSAT counts 4 and 5 as satisfied: ${F.pct(sum(cs.filter(c => c.score >= 4).map(c => c.n)) / tot)}.</p>`);
    const mat = (el, rows, cols) => { const vals = rows.map(r => cols.map(c => r[c])); const flat = vals.flat().filter(x => x != null); const fn = scaleSeq(Math.min(...flat), Math.max(...flat));
      heatmap(el, { rows: rows.map(r => r.queue_code), cols, values: vals, color: fn, text: x => Math.round(x), title: (i, j, x) => `${rows[i].queue_code}, ${cols[j]}: median ${Math.round(x)}s` }); };
    mat($('#e5'), e.aht_by_tenure, ['0-3m', '3-6m', '6-12m', '12m+']); mat($('#e6'), e.aht_by_shift, ['Morning', 'General', 'Evening', 'Night']);
    const L = e.load_heatmap; const lf = L.values.flat(); const fl = scaleSeq(0, Math.max(...lf));
    heatmap($('#e7'), { rows: L.rows, cols: L.cols.map(h => `${h}:00`), colEvery: 2, values: L.values, color: fl, text: () => '', title: (i, j, x) => `${L.rows[i]} ${L.cols[j]}:00 — ${F.int(x)} contacts/hour` });
    $('#e7l').innerHTML = heatLegend(fl, 0, Math.max(...lf), F.int);
    const Cm = e.correlation; const fd = scaleDiv(0, 1);
    heatmap($('#e8'), { rows: Cm.labels, cols: Cm.labels.map(l => l.split(/[ /]/)[0].slice(0, 6)), values: Cm.matrix, color: fd, text: x => x.toFixed(2).replace('0.', '.'), title: (i, j, x) => `${Cm.labels[i]} vs ${Cm.labels[j]}: r = ${x.toFixed(2)}` });
  },
});
function boxPlot(el, items) {
  mountChart(el, () => {
    const W = Math.max(300, el.clientWidth || 600), rowH = 30, pl = 84, pr = 16, pt = 6, H = pt + items.length * rowH + 26;
    const hi = Math.max(...items.map(i => i.p95)); const t = niceTicks(0, hi, 5); const X = x => pl + x / t.at(-1) * (W - pl - pr);
    let g = t.map(x => `<line class="grid-l" x1="${X(x)}" x2="${X(x)}" y1="${pt}" y2="${H - 22}"/><text class="ax" x="${X(x)}" y="${H - 8}" text-anchor="middle">${F.sec(x)}</text>`).join('');
    items.forEach((b, i) => { const y = pt + i * rowH + rowH / 2;
      g += `<text class="ax" x="${pl - 8}" y="${y + 4}" text-anchor="end" style="font-weight:600;fill:var(--ink-2)">${esc(b.label)}</text>
        <line x1="${X(b.p5)}" x2="${X(b.p95)}" y1="${y}" y2="${y}" stroke="var(--ink-4)" stroke-width="1.4"/>
        <line x1="${X(b.p5)}" x2="${X(b.p5)}" y1="${y - 5}" y2="${y + 5}" stroke="var(--ink-4)"/><line x1="${X(b.p95)}" x2="${X(b.p95)}" y1="${y - 5}" y2="${y + 5}" stroke="var(--ink-4)"/>
        <rect x="${X(b.q1)}" y="${y - 9}" width="${X(b.q3) - X(b.q1)}" height="18" rx="3" fill="color-mix(in srgb, var(--s1) 22%, transparent)" stroke="var(--s1)"/>
        <line x1="${X(b.median)}" x2="${X(b.median)}" y1="${y - 9}" y2="${y + 9}" stroke="var(--s1)" stroke-width="2.4"/>
        <circle cx="${X(b.mean)}" cy="${y}" r="3" fill="var(--surface)" stroke="var(--ink)" stroke-width="1.4"><title>${esc(b.label)}: median ${F.sec(b.median)}, mean ${F.sec(b.mean)}, IQR ${F.sec(b.q1)}–${F.sec(b.q3)}, n=${F.int(b.n)}</title></circle>`; });
    el.innerHTML = `<svg viewBox="0 0 ${W} ${H}" width="${W}" height="${H}" role="img" aria-label="Box plot of handle time by queue">${g}</svg>`;
  });
}

/* ---------------- Catalog & governance ---------------- */
function daxFor(m) {
  const ex = t => t.map(([c, s], i) => `${i ? (s > 0 ? ' + ' : ' - ') : s > 0 ? '' : '-'}SUM(rpt_interval_cube[${c}])`).join('');
  return `[${m.label}] =\n    ${m.den ? `DIVIDE(\n        ${ex(m.num)},\n        ${ex(m.den)}\n    )` : ex(m.num)}`;
}
page('catalog', {
  title: 'Catalog & governance', sub: 'Metric definitions, tables, the star schema, PII and access', filters: [],
  async render(v, params, alive) {
    const tab = params.tab || 'metrics';
    const c = await cached('catalog', () => API.get('catalog')); if (!alive()) return;
    v.innerHTML = `<div class="section-h"><div><span class="eyebrow">One definition per metric, one owner per table ${LOG_TAG('2–4 Jun, 16–19 Jun')}</span><h1>Catalog & governance</h1><p>The same registry drives the SQL views, the dashboard's in-browser engine and the generated Power BI measures, so a KPI cannot mean two different things in two places.</p></div>
      <div class="r"><div class="seg" id="kt">${[['metrics', 'Metrics'], ['tables', 'Tables'], ['schema', 'Star schema'], ['gov', 'PII & access']].map(([k, l]) => `<button data-v="${k}" aria-pressed="${tab === k}">${l}</button>`).join('')}</div></div></div><div id="kb"></div>`;
    seg($('#kt'), t => go('catalog', { tab: t }));
    const host = $('#kb');
    if (tab === 'metrics') {
      const groups = [...new Set(c.metrics.map(m => m.group))];
      host.innerHTML = groups.map(g => `<h3 style="font-size:13px;margin:6px 0 10px;color:var(--ink-2)">${esc(g)}</h3><div class="grid" style="margin-bottom:18px">${c.metrics.filter(m => m.group === g).map(m => {
        const tgt = m.target_key && c.targets[m.target_key] != null ? (m.unit === 'pct' ? F.pct0(c.targets[m.target_key]) : fmtMetric(m.id, c.targets[m.target_key])) : ['sl', 'aht', 'abandon_rate'].includes(m.id) ? 'per queue contract' : null;
        return `<section class="card c6 metric-card"><div class="card-h"><h3>${esc(m.label)}</h3><span class="tag">${esc(m.id)}</span><div class="r">${tgt ? `<span class="pill info">target ${esc(tgt)}</span>` : ''}<span class="pill out">${m.direction === 'up' ? 'higher is better' : m.direction === 'down' ? 'lower is better' : 'context'}</span></div></div>
          <div class="card-b" style="display:flex;flex-direction:column;gap:10px"><p style="font-size:13px">${esc(m.definition)}</p>
          <dl class="kv"><dt>Business question</dt><dd>${esc(m.business_question)}</dd><dt>Numerator</dt><dd>${esc(m.numerator)}</dd><dt>Denominator</dt><dd>${esc(m.denominator)}</dd><dt>Exclusions</dt><dd>${esc(m.exclusions)}</dd></dl>
          <details><summary class="muted" style="font-size:12px;cursor:pointer">SQL and DAX</summary><pre class="code">${esc(m.sql)}</pre><pre class="code">${esc(daxFor(m))}</pre></details></div></section>`; }).join('')}</div>`).join('');
    } else if (tab === 'tables') {
      const layers = ['All', 'Fact', 'Dimension', 'Reporting', 'Governance', 'Staging']; const L = params.layer || 'All';
      host.innerHTML = `<div style="margin-bottom:12px" class="seg" id="kl">${layers.filter(l => l === 'All' || c.tables.some(t => t.layer === l)).map(l => `<button data-v="${l}" aria-pressed="${L === l}">${l}</button>`).join('')}</div><div class="card"><div class="card-b flush" id="kt2"></div></div>`;
      seg($('#kl'), l => go('catalog', { tab: 'tables', layer: l }));
      sortableTable($('#kt2'), [
        { key: 'name', label: 'Table', render: t => `<b class="mono" style="font-size:12.5px">${esc(t.name)}</b>${t.type === 'view' ? ' <span class="tag">view</span>' : ''}` },
        { key: 'layer', label: 'Layer', render: t => `<span class="pill ${t.layer === 'Fact' ? 'info' : t.layer === 'Staging' ? 'warn' : 'out'}">${esc(t.layer)}</span>` },
        { key: 'rows', label: 'Rows', num: true, render: t => F.int(t.rows) },
        { key: 'ncols', label: 'Columns', num: true },
        { key: 'pii', label: 'Sensitive', num: true, render: t => t.pii ? `<span class="st-bad">${t.pii}</span>` : '—' },
        { key: 'description', label: 'Description', wrap: true },
      ], c.tables.filter(t => L === 'All' || t.layer === L).map(t => ({ ...t, id: t.name, ncols: t.columns.length, pii: t.columns.filter(x => x.sensitivity).length })), { sortKey: 'layer', sortDir: 1, onRow: t => drawer(t.name, `<p style="font-size:13px">${esc(t.description)}</p><div class="tbl-wrap"><table class="tbl"><thead><tr><th>Column</th><th>Type</th><th>Key</th><th>Sensitivity</th></tr></thead><tbody>${t.columns.map(x => `<tr><td class="mono" style="font-size:12px">${esc(x.name)}</td><td>${esc(x.type)}</td><td>${x.pk ? '<span class="tag">PK</span>' : c.relationships.some(r => r.from_table === t.name && r.from_column === x.name) ? '<span class="tag">FK</span>' : ''}</td><td>${x.sensitivity ? `<span class="pill warn">${esc(x.sensitivity)}</span>` : ''}</td></tr>`).join('')}</tbody></table></div>`, { sub: `${t.layer} · ${F.int(t.rows)} rows` }) });
    } else if (tab === 'schema') {
      host.innerHTML = `<div class="grid"><section class="card c9"><div class="card-h"><h3>Star schema</h3><span class="sub">fact_interaction at the centre; one row per offered contact</span></div><div class="card-b schema" id="ks"></div></section>
        <section class="card c3"><div class="card-h"><h3>Relationships</h3></div><div class="card-b" style="display:flex;flex-direction:column;gap:8px;font-size:12.5px">${c.relationships.map(r => `<div><span class="mono" style="font-size:11.5px">${esc(r.from_table)}.${esc(r.from_column)}</span><br><span class="muted">→ ${esc(r.to_table)} · ${esc(r.cardinality)}</span></div>`).join('')}
        <div class="insight" style="margin-top:6px"><div><b>The join trap</b><p>fact_case_status has several rows per interaction. Joining it directly multiplies contacts; keep the latest status per case with ROW_NUMBER() first (SQL lab, ${'"Latest status per case"'}).</p></div></div></div></section></div>`;
      schemaDiagram($('#ks'), c);
    } else {
      const users = await API.get('users'); if (!alive()) return;
      host.innerHTML = `<div class="grid"><section class="card c7"><div class="card-h"><h3>PII register</h3><span class="sub">every sensitive source column and what happens to it</span><div class="r">${LOG_TAG('4 Jun')}</div></div><div class="card-b flush" id="kg1"></div></section>
        <section class="card c5"><div class="card-h"><h3>Principles</h3></div><div class="card-b"><div class="narr">
          <p>Customer identifiers are hashed with a salted SHA-256 on the way into staging. The hash keeps customers joinable (repeat contacts, FCR) without the clear value ever reaching the warehouse.</p>
          <p>Masked display forms (for example ••••••4821) exist for case look-ups; clear names, phones and emails are dropped.</p>
          <p>The API and SQL lab use a read-only connection. Staging tables are blocked in the SQL lab.</p>
          <p>Row-level security limits each role to its queues; client viewers also get agent names replaced by IDs.</p>
          <p>Each load writes a batch id, file and row count to gov_load_log, and each cleaning rule writes to gov_cleaning_log.</p></div></div></section>
        <section class="card c12"><div class="card-h"><h3>Roles and row-level security</h3><span class="sub">switch identity from the top-right menu to see the effect</span></div><div class="card-b flush" id="kg2"></div></section></div>`;
      sortableTable($('#kg1'), [
        { key: 'source_table', label: 'Source', render: p => `<span class="mono" style="font-size:12px">${esc(p.source_table)}.${esc(p.column_name)}</span>` },
        { key: 'classification', label: 'Classification', render: p => `<span class="pill ${/PII/.test(p.classification) ? 'crit' : 'warn'}">${esc(p.classification)}</span>` },
        { key: 'treatment', label: 'Treatment', wrap: true },
      ], c.pii_register.map((p, i) => ({ ...p, id: i })), {});
      sortableTable($('#kg2'), [
        { key: 'name', label: 'User', render: u => `<b style="font-weight:550">${esc(u.name)}</b><div class="muted" style="font-size:12px">${esc(u.title)}</div>` },
        { key: 'role', label: 'Role' },
        { key: 'queues', label: 'Rows visible', render: u => u.queues ? u.queues.map(q => `<span class="tag">${esc(q)}</span>`).join(' ') : 'All queues' },
        { key: 'can_see_agent_names', label: 'Agent names', render: u => u.can_see_agent_names ? 'Visible' : '<span class="st-bad">Replaced by ID</span>' },
        { key: 'can_sql', label: 'SQL lab and data quality', render: u => u.can_sql ? '<span class="st-good">Yes</span>' : 'No' },
        { key: 'cur', label: '', sort: false, render: u => u.id === API.user ? '<span class="pill info">current</span>' : '' },
      ], users, {});
    }
  },
});
function schemaDiagram(el, cat) {
  const rows = Object.fromEntries(cat.tables.map(t => [t.name, t.rows]));
  const B = {
    fact_interaction: [380, 190, 200, ['interaction_id PK', 'date_key FK', 'interval_idx FK', 'queue_id FK', 'agent_id FK', 'customer_key FK', '+ 38 measures and flags'], 'fact'],
    dim_date: [30, 30, 170, ['date_key PK', 'weekday, iso_week', 'is_holiday'], 'dim'],
    dim_interval: [30, 170, 170, ['interval_idx PK', 'label, shift window'], 'dim'],
    dim_customer: [30, 290, 170, ['customer_key PK', 'masked fields only'], 'dim'],
    dim_queue: [770, 30, 180, ['queue_id PK', 'client_id FK', 'targets, hours'], 'dim'],
    dim_client: [770, 170, 180, ['client_id PK', 'client_name'], 'dim'],
    dim_agent: [770, 290, 180, ['agent_id PK', 'team_leader_id FK', 'tenure, shift'], 'dim'],
    dim_team_leader: [770, 420, 180, ['team_leader_id PK'], 'dim'],
    fact_case_status: [180, 450, 180, ['interaction_id FK (many)', 'status, status_at'], 'fact'],
    fact_csat: [390, 470, 140, ['interaction_id FK', 'score'], 'fact'],
    fact_qa: [560, 450, 160, ['interaction_id FK', 'audit scores'], 'fact'],
    rpt_interval_cube: [290, 20, 190, ['queue × date × interval', '28 additive columns'], 'rpt'],
    fact_wfm_interval: [520, 20, 190, ['forecast, required', 'scheduled, staffed'], 'fact'],
  };
  const W = 980, H = 560; const hgt = n => 30 + n * 16;
  const box = n => { const [x, y, w, cols] = B[n]; return { x, y, w, h: hgt(cols.length), cx: x + w / 2, cy: y + hgt(cols.length) / 2 }; };
  const clip = (a, b) => { const dx = b.cx - a.cx, dy = b.cy - a.cy; const s = Math.min(Math.abs((a.w / 2) / (dx || 1e-9)), Math.abs((a.h / 2) / (dy || 1e-9))); return [a.cx + dx * s, a.cy + dy * s]; };
  let g = '';
  cat.relationships.forEach(r => { if (!B[r.from_table] || !B[r.to_table]) return; const a = box(r.from_table), b = box(r.to_table); const [x1, y1] = clip(a, b), [x2, y2] = clip(b, a);
    g += `<path class="ln" d="M${x1},${y1} L${x2},${y2}"/><circle cx="${x2}" cy="${y2}" r="3" fill="var(--axis)"/><text x="${x1 + (x2 - x1) * 0.12}" y="${y1 + (y2 - y1) * 0.12 - 4}" style="font-size:10px;fill:var(--ink-3)">${/one-to-one|zero-or-one/.test(r.cardinality) ? '1' : '∞'}</text><text x="${x2 - (x2 - x1) * 0.1}" y="${y2 - (y2 - y1) * 0.1 - 4}" style="font-size:10px;fill:var(--ink-3)">1</text>`; });
  Object.entries(B).forEach(([n, [x, y, w, cols, kind]]) => { const h = hgt(cols.length);
    g += `<g class="${kind === 'fact' ? 'fact' : ''}" style="cursor:pointer" data-t="${n}"><rect class="tb" x="${x}" y="${y}" width="${w}" height="${h}" rx="8"/><path class="th" d="M${x},${y + 8} a8,8 0 0 1 8,-8 h${w - 16} a8,8 0 0 1 8,8 v16 h-${w} z"/>
      <text x="${x + 10}" y="${y + 17}" style="font-weight:650;fill:var(--ink)">${n}</text><text x="${x + w - 8}" y="${y + 17}" text-anchor="end" style="fill:var(--ink-3);font-size:10px">${F.compact(rows[n])}</text>
      ${cols.map((c, i) => `<text x="${x + 10}" y="${y + 40 + i * 16}" style="fill:${/PK/.test(c) ? 'var(--ink)' : /FK/.test(c) ? 'var(--s1)' : 'var(--ink-3)'}">${esc(c)}</text>`).join('')}</g>`; });
  el.innerHTML = `<div style="overflow-x:auto"><svg viewBox="0 0 ${W} ${H}" style="width:100%;min-width:760px;height:auto" role="img" aria-label="Star schema diagram">${g}</svg></div><div class="legend" style="margin-top:8px"><span><i style="background:color-mix(in srgb,var(--s1) 30%,var(--surface))"></i>Fact</span><span><i style="background:var(--surface-3)"></i>Dimension / reporting</span><span style="color:var(--s1)">FK</span><span>∞ — 1 cardinality</span><span>click a table for its columns</span></div>`;
  $$('g[data-t]', el).forEach(gg => gg.onclick = () => { const t = cat.tables.find(x => x.name === gg.dataset.t); if (t) drawer(t.name, `<p style="font-size:13px">${esc(t.description)}</p><div class="tbl-wrap"><table class="tbl"><thead><tr><th>Column</th><th>Type</th><th>Sensitivity</th></tr></thead><tbody>${t.columns.map(x => `<tr><td class="mono" style="font-size:12px">${esc(x.name)}${x.pk ? ' <span class="tag">PK</span>' : ''}</td><td>${esc(x.type)}</td><td>${x.sensitivity ? `<span class="pill warn">${esc(x.sensitivity)}</span>` : ''}</td></tr>`).join('')}</tbody></table></div>`, { sub: `${t.layer} · ${F.int(t.rows)} rows` }); });
}

/* ---------------- SQL lab ---------------- */
const SQLSTATE = { sql: null, id: null, result: null };
page('sql', {
  title: 'SQL lab', sub: 'Read-only queries on the warehouse, with execution plans', filters: [],
  async render(v, params, alive) {
    if (!STATE.meta.user.can_sql) { v.innerHTML = '<div class="empty">The SQL lab is available to Admin and Analyst roles.</div>'; return; }
    const saved = await cached('sqlsaved', () => API.get('sql/saved')); if (!alive()) return;
    const cur = saved.find(s => s.id === (params.id || SQLSTATE.id)) || saved[0];
    if (SQLSTATE.id !== cur.id || SQLSTATE.sql == null) { SQLSTATE.id = cur.id; SQLSTATE.sql = cur.sql; SQLSTATE.result = null; }
    v.innerHTML = `<div class="section-h"><div><span class="eyebrow">Read-only connection · one SELECT or WITH · warehouse tables only · 6 s timeout · 1,000 rows ${LOG_TAG('5–9 Jun, 16 Jun, 23–24 Jun')}</span><h1>SQL lab</h1><p>The saved queries are the SQL exercises from the internship log, rewritten against this warehouse. Each shows its execution plan, so the effect of an index is visible.</p></div></div>
      ${API.mode === 'static' ? '<div class="banner info" style="margin-bottom:14px"><b>Offline snapshot.</b> Saved queries show the results captured when the snapshot was built. Run <span class="mono">python -m oip serve</span> to write your own.</div>' : ''}
      <div class="sqlwrap"><section class="card"><div class="card-h"><h3>Saved queries</h3></div><div class="list saved">${saved.map(s => `<div class="li ${s.id === cur.id ? 'sel' : ''}" data-id="${s.id}"><div class="t"><b>${esc(s.title)}</b><small>log ${esc(s.log)}</small></div></div>`).join('')}</div></section>
      <div style="display:flex;flex-direction:column;gap:14px;min-width:0"><section class="card"><div class="card-h"><h3>${esc(cur.title)}</h3>${LOG_TAG(cur.log)}<div class="r"><button class="btn btn-ghost btn-sm" id="sreset" title="Restore the saved text">Reset</button><button class="btn btn-primary btn-sm" id="srun">${ICON.play}Run <span class="kbd" style="margin-left:4px">⌘↵</span></button></div></div>
        <div class="card-b" style="display:flex;flex-direction:column;gap:10px"><p class="ink2" style="font-size:13px">${esc(cur.note)}</p><textarea class="editor" id="sed" spellcheck="false" aria-label="SQL">${esc(SQLSTATE.sql)}</textarea></div></section>
        <section class="card" id="sres"></section></div></div>`;
    $$('.saved .li').forEach(li => li.onclick = () => { SQLSTATE.id = null; go('sql', { id: li.dataset.id }); });
    const ed = $('#sed'); ed.style.height = Math.min(420, Math.max(200, ed.scrollHeight + 6)) + 'px';
    ed.oninput = () => SQLSTATE.sql = ed.value;
    ed.onkeydown = e => { if ((e.metaKey || e.ctrlKey) && e.key === 'Enter') { e.preventDefault(); run(); } if (e.key === 'Tab') { e.preventDefault(); const s = ed.selectionStart; ed.setRangeText('  ', s, ed.selectionEnd, 'end'); SQLSTATE.sql = ed.value; } };
    $('#sreset').onclick = () => { ed.value = SQLSTATE.sql = cur.sql; };
    const show = r => {
      const box = $('#sres'); if (!box) return;
      if (!r) { box.innerHTML = '<div class="card-b muted" style="font-size:13px">Run the query to see results and its plan.</div>'; return; }
      if (r.error) { box.innerHTML = `<div class="card-b"><div class="banner warn"><b>Query not run.</b> ${esc(r.error)}</div></div>`; return; }
      const scans = r.plan.filter(p => /^SCAN/.test(p)).length;
      box.innerHTML = `<div class="card-h"><h3>Result</h3><span class="sub">${F.int(r.row_count)} row${r.row_count === 1 ? '' : 's'}${r.truncated ? ' (first 1,000)' : ''} · ${F.num(r.elapsed_ms, 1)} ms${r.cached ? ' · captured at build' : ''}</span>${API.mode === 'live' ? `<div class="r"><button class="btn btn-sm btn-ghost" id="scsv">${ICON.down}CSV</button></div>` : ''}</div>
        ${r.plan.length ? `<div class="card-b" style="border-bottom:1px solid var(--border)"><div class="eyebrow" style="margin-bottom:6px">Query plan ${scans ? `<span class="pill warn">${scans} full scan${scans > 1 ? 's' : ''}</span>` : '<span class="pill good">index searches only</span>'}</div><div class="plan">${r.plan.map(p => `<span class="${/^SCAN/.test(p) ? 'scan' : /^SEARCH/.test(p) ? 'search' : ''}">${esc(p)}</span>`).join('')}</div></div>` : ''}
        <div class="card-b flush"><div class="tbl-wrap" style="max-height:460px;overflow:auto"><table class="tbl"><thead><tr>${r.columns.map(c => `<th>${esc(c)}</th>`).join('')}</tr></thead><tbody>${r.rows.slice(0, 300).map(row => `<tr>${row.map(x => `<td class="${typeof x === 'number' ? 'num' : ''}">${x == null ? '<span class="muted">null</span>' : esc(typeof x === 'number' && !Number.isInteger(x) ? +x.toFixed(4) : x)}</td>`).join('')}</tr>`).join('')}</tbody></table></div>${r.rows.length > 300 ? `<p class="muted" style="padding:10px 14px;font-size:12px">Showing 300 of ${F.int(r.rows.length)} rows; the CSV has all of them.</p>` : ''}</div>`;
      if ($('#scsv')) $('#scsv').onclick = () => { const q = x => x == null ? '' : /[",\n]/.test(String(x)) ? `"${String(x).replaceAll('"', '""')}"` : x; const csv = [r.columns, ...r.rows].map(rr => rr.map(q).join(',')).join('\n'); const a = document.createElement('a'); a.href = URL.createObjectURL(new Blob([csv], { type: 'text/csv' })); a.download = `${cur.id}.csv`; a.click(); };
    };
    const run = async () => { const b = $('#srun'); b.disabled = true; $('#sres').innerHTML = '<div class="card-b"><div class="skeleton" style="min-height:140px"></div></div>';
      try { SQLSTATE.result = await API.post('sql', { sql: ed.value }); } catch (e) { SQLSTATE.result = { error: e.message }; }
      show(SQLSTATE.result); b.disabled = false; };
    $('#srun').onclick = run;
    if (SQLSTATE.result) show(SQLSTATE.result); else run();
  },
});

/* ---------------- Settings ---------------- */
page('settings', {
  title: 'Settings', sub: 'Copilot model, appearance, identity and build', filters: [],
  async render(v) {
    const llm = STATE.meta.llm || {}; const b = STATE.meta.build || {}; const th = lsGet('oip_theme') || 'system';
    const users = await API.get('users');
    v.innerHTML = `<div class="grid">
      <section class="card c6"><div class="card-h"><h3>Copilot model</h3></div><div class="card-b" style="display:flex;flex-direction:column;gap:12px">
        <dl class="kv"><dt>Mode</dt><dd>${API.mode === 'static' ? (STATIC_LLM.sample ? 'Claude, through claude.ai (keyword retrieval in the browser)' : 'Extractive (offline snapshot)') : `${esc(PROVIDER_LABEL[llm.provider] || llm.provider)}`}</dd><dt>Model</dt><dd class="mono">${esc(API.mode === 'static' ? (STATIC_LLM.sample ? 'viewer’s Claude' : 'none') : llm.model)}</dd><dt>Configured</dt><dd class="mono">OIP_LLM_PROVIDER=${esc(llm.configured || 'auto')}</dd></dl>
        <p class="ink2" style="font-size:13px">With <span class="mono">auto</span> the copilot uses Claude when an API key is set, then a local Ollama model if one is running, and otherwise quotes the retrieved passages. Retrieval and citations are the same in every mode.</p>
        <pre class="code">cp .env.example .env
# then set one of:
ANTHROPIC_API_KEY=sk-ant-...        # Claude writes the answer
OIP_ANTHROPIC_MODEL=claude-sonnet-5-5
OLLAMA_BASE_URL=http://127.0.0.1:11434   # or a local model
OIP_OLLAMA_MODEL=llama3.1</pre></div></section>
      <section class="card c6"><div class="card-h"><h3>Appearance</h3></div><div class="card-b" style="display:flex;flex-direction:column;gap:12px"><div class="seg" id="sth">${[['system', 'System'], ['light', 'Light'], ['dark', 'Dark']].map(([k, l]) => `<button data-v="${k}" aria-pressed="${th === k}">${l}</button>`).join('')}</div>
        <p class="muted" style="font-size:12.5px">Charts use one blue for actuals, a categorical palette checked for colour-blind contrast, and red only for status. Every chart has a table or tooltip with the exact values.</p></div>
        <div class="card-h" style="border-top:1px solid var(--border)"><h3>Build</h3></div><div class="card-b"><dl class="kv"><dt>Data</dt><dd>${F.dateLong(STATE.meta.period.start)} to ${F.dateLong(STATE.meta.period.end)} (synthetic)</dd><dt>Built</dt><dd>${esc(b.built_at || '—')}${b.seconds ? ` in ${b.seconds}s` : ''}</dd><dt>Seed</dt><dd class="mono">${esc(b.seed ?? '20260601')}</dd><dt>Serving</dt><dd>${API.mode === 'live' ? 'Local API · <a href="api/docs" target="_blank" rel="noopener">OpenAPI docs ' + ICON.ext + '</a>' : 'Offline snapshot (no server)'}</dd></dl></div></section>
      <section class="card c12"><div class="card-h"><h3>View the platform as</h3><span class="sub">demo identities; production would use single sign-on</span></div><div class="card-b flush" id="su"></div></section>
      <section class="card c12"><div class="card-h"><h3>Commands</h3></div><div class="card-b"><pre class="code">python -m oip build           # generate data → ingest → profile → clean → reconcile → warehouse → analytics → copilot index
python -m oip serve           # dashboard and API on http://127.0.0.1:8050
python -m oip ask "How do we handle an SLA breach in the morning peak?"
python -m oip export-powerbi  # star-schema CSVs + measures.dax + model notes for Power BI Desktop
python -m oip export-static   # offline snapshot for the hosted preview
python -m pytest              # metric parity, cleaning rules, reconciliation, Erlang C, SQL guard rails, RAG quality</pre></div></section></div>`;
    seg($('#sth'), t => setTheme(t));
    sortableTable($('#su'), [
      { key: 'name', label: 'User', render: u => `<b style="font-weight:550">${esc(u.name)}</b>` }, { key: 'role', label: 'Role' }, { key: 'title', label: 'Scope', render: u => esc(u.title) },
      { key: 'id', label: '', sort: false, render: u => u.id === API.user ? '<span class="pill info">current</span>' : `<button class="btn btn-sm" data-sw="${u.id}">Switch</button>` },
    ], users, {});
    $$('[data-sw]').forEach(b => b.onclick = async () => { API.user = b.dataset.sw; lsSet('oip_user', API.user); STATE.filters = null; lsSet('oip_filters', null); await loadData(); renderShellMeta(); toast(`Viewing as ${STATE.meta.user.name}`); go('overview'); });
  },
});

/* ---------------- About this build ---------------- */
const LOGMAP = [
  ['15–30 May', 'Floor-plan module (separate project)', 'Image pre-processing, OCR of dimension text, unit parsing and schema validation for the 2D-to-3D floor-plan pipeline.', null],
  ['1 Jun', 'Platform layers', 'Source systems → ingestion and staging → warehouse → analytics → reporting.', ['about', {}]],
  ['2 Jun', 'Operational metrics', 'AHT, ACW, FCR, CSAT, SLA, abandonment, occupancy, shrinkage, each mapped to a business question.', ['catalog', { tab: 'metrics' }]],
  ['3 Jun', 'Data dictionary and ERD', 'Facts vs dimensions, keys, grain and row counts.', ['catalog', { tab: 'schema' }]],
  ['4 Jun', 'Governance', 'PII masking, read-only access, role-based access.', ['catalog', { tab: 'gov' }]],
  ['5–9 Jun', 'SQL', 'Aggregation, four-table joins and the one-to-many trap, CTEs, ROW_NUMBER, RANK, AVG OVER, execution plans and indexing.', ['sql', {}]],
  ['10 Jun', 'Extract and profile', 'SQLAlchemy load into pandas; nulls, types, distinct values and label drift.', ['quality', {}]],
  ['11–12 Jun', 'Cleaning and outliers', 'Imputation, mapping dictionaries, datetime parsing, de-duplication, IQR outliers and approved capping of unclosed sessions.', ['quality', {}]],
  ['13 Jun', 'Reconciliation', 'Three sample dates against the source report; a variance traced to a cleaning rule and fixed.', ['quality', {}]],
  ['15 Jun', 'Exploratory analysis', 'Distributions, handle time by queue, shift and tenure, load patterns, correlations.', ['eda', {}]],
  ['16–17 Jun', 'Metric SQL and reporting views', 'Numerators, denominators and exclusions written out; the short-abandon mismatch; the reporting cube.', ['catalog', { tab: 'metrics' }]],
  ['18–19 Jun', 'Power BI model and DAX', 'Star schema, date table and measures validated against SQL (exported by export-powerbi).', ['catalog', { tab: 'metrics' }]],
  ['20–22 Jun', 'Queue performance page and testing', 'KPI cards, trend and queue matrix with slicers; figures reconciled to SQL; row-level security.', ['queues', {}]],
  ['23–24 Jun', 'SLA root-cause analysis', 'Pareto of breaches by half-hour, candidate causes tested, staffing gap quantified.', ['rca', {}]],
  ['25–26 Jun', 'Volume forecasting', 'Lag, rolling and calendar features, chronological split, moving-average baseline, linear regression and random forest, MAE/RMSE/MAPE.', ['forecast', {}]],
  ['27–29 Jun', 'RAG recommendation module', 'Knowledge-base preparation, chunking, embeddings, vector store, chunk-size test and citation test queries.', ['copilot', { tab: 'eval' }]],
];
page('about', {
  title: 'About this build', sub: 'What this is, how it maps to the internship log, and its limits', filters: [],
  render(v) {
    v.innerHTML = `<div class="banner warn" style="margin-bottom:16px"><b>Reconstruction on synthetic data.</b> The Operations Intelligence Platform at BPO Integra runs on confidential client data, and access ended with the internship on 30 June 2026. This build re-implements the methods worked on during the internship, under mentor supervision, on generated data for four fictional clients. It contains no company code and no client data.</div>
      <div class="grid">
        <section class="card c12"><div class="card-h"><h3>Architecture</h3></div><div class="card-b"><div class="arch">
          ${[['Sources', ['Dialler / ACD calls', 'Chat and email platforms', 'Back-office workflow', 'CRM cases and customers', 'WFM plan and staffed intervals', 'HR roster, QA audits, CSAT']],
             ['Staging', ['15 extracts, batch-logged', 'PII hashed and masked on load', 'Profiling of every column']],
             ['Cleaning', ['13 numbered rules with a log', 'Mapping dictionaries', 'IQR outliers, approved capping', 'Reconciliation to source']],
             ['Warehouse', ['SQLite star schema', '7 dimensions, 6 facts', 'Reporting cube, indexed', 'Metric registry as code']],
             ['Analytics', ['EDA', 'Root cause: Pareto, tests, Shapley', 'Forecast + Erlang C staffing', 'Anomaly detection']],
             ['Serving', ['FastAPI, role-based access', 'This dashboard (no build step)', 'RAG copilot with citations', 'Power BI export']]].map(([h, items], i) => `${i ? `<span class="flow-arrow">${ICON.arrow}</span>` : ''}<div class="arch-col"><b>${h}</b>${items.map(x => `<span>${x}</span>`).join('')}</div>`).join('')}
        </div></div></section>
        <section class="card c8"><div class="card-h"><h3>How the platform maps to the daily activity log</h3><span class="sub">click a row to open the module</span></div><div class="card-b flush"><div class="list">${LOGMAP.map(([d, t, s, link]) => `<div class="li" ${link ? `data-go='${esc(JSON.stringify(link))}'` : ''} style="${link ? '' : 'opacity:.75;cursor:default'}"><span class="tag" style="min-width:74px;text-align:center">${d}</span><div class="t"><b>${esc(t)}</b><small style="white-space:normal">${esc(s)}</small></div>${link ? `<span class="muted">${ICON.arrow}</span>` : '<span class="pill out">separate</span>'}</div>`).join('')}</div></div></section>
        <section class="card c4"><div class="card-h"><h3>Beyond the log</h3></div><div class="card-b"><div class="narr">
          <p>Some modules go past what the log records the intern doing, to make the platform complete. They are listed so the review can tell the two apart.</p>
          <p>Intraday view, agent drawer and alerts with anomaly detection.</p>
          <p>Shapley attribution of breaches over an Erlang C model, and the what-if projection.</p>
          <p>The 14-day staffing plan from the forecast (Erlang C with 30% shrinkage).</p>
          <p>Answer generation in the copilot (the log covers knowledge-base preparation, embeddings and retrieval testing).</p></div></div>
          <div class="card-h" style="border-top:1px solid var(--border)"><h3>Limitations</h3></div><div class="card-b"><div class="narr">
          <p>Synthetic data: patterns are realistic but designed, so findings are demonstrations of method, not results.</p>
          <p>Three months of history cannot show annual seasonality.</p>
          <p>SQLite suits a single-node demo; production would use a server warehouse, scheduled orchestration and SSO.</p>
          <p>The offline copilot quotes sentences; only a connected model writes reasoned answers, and those must still be checked against the citations.</p></div></div></section>
      </div>`;
    $$('[data-go]').forEach(li => li.onclick = () => { const [p, q] = JSON.parse(li.dataset.go); if (p !== 'about') go(p, q); });
  },
});
