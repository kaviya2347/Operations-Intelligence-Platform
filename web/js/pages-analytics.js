/* Analytics pages: Root-cause workbench, Forecast & staffing plan, Alerts. */
'use strict';

const CAUSE_COLOR = { 'Staffing shortfall': 'var(--s2)', 'Volume spike': 'var(--s1)', 'Handle-time inflation': 'var(--s7)', 'Random variation': 'var(--ink-4)', 'Backlog (asynchronous queue)': 'var(--ink-4)' };

/* ---------------- Root cause ---------------- */
page('rca', {
  title: 'Root-cause analysis', sub: 'Why service level breaks, and what fixes it', filters: [],
  async render(v, params, alive) {
    const rt = STATE.meta.queues.filter(q => q.realtime);
    if (!rt.length) { v.innerHTML = '<div class="empty">No real-time queues available for your role.</div>'; return; }
    const qid = params.queue && rt.some(q => q.queue_id === params.queue) ? params.queue : rt[0].queue_id; const q = queueById(qid);
    const win = params.win || 'all'; const f = STATE.filters;
    v.innerHTML = `<div class="section-h"><div><span class="eyebrow">Root-cause workbench</span><h1>${esc(q.code)} · ${esc(q.name)}</h1><p>Breaches are intervals whose service level is below target by more than random variation at their volume. Causes are tested on breach vs normal intervals and attributed with a Shapley decomposition over an Erlang C model.</p></div>
      <div class="r"><select id="rq">${rt.map(x => `<option value="${x.queue_id}" ${x.queue_id === qid ? 'selected' : ''}>${x.code} · ${x.name}</option>`).join('')}</select>
      <div class="seg" id="rw"><button data-v="all" aria-pressed="${win === 'all'}">Full period</button><button data-v="filter" aria-pressed="${win === 'filter'}" ${API.mode === 'static' ? 'disabled title="Needs the local server"' : ''}>Current filter</button></div></div></div>
      <div id="rcab"><div class="skeleton" style="min-height:420px"></div></div>`;
    $('#rq').onchange = e => go('rca', { queue: e.target.value, win });
    seg($('#rw'), w => go('rca', { queue: qid, win: w }));
    const qs = win === 'filter' ? `&start=${f.start}&end=${f.end}` : '';
    let r; try { r = await API.get(`rca?queue=${qid}${qs}`); } catch (e) { errBox($('#rcab'), e); return; }
    if (!alive()) return;
    if (r.error) { $('#rcab').innerHTML = `<div class="empty">${esc(r.error)}</div>`; return; }
    const hs = new Set(r.hotspots || []); const lead = (r.hypotheses || []).slice().sort((a, b) => b.primary_share_vital - a.primary_share_vital)[0];
    $('#rcab').innerHTML = `
      <section class="kpis" style="margin-bottom:14px">
        <div class="kpi"><span class="l">Intervals analysed</span><span class="v">${F.int(r.totals.intervals)}</span><span class="meta">${F.date(r.range.start)} – ${F.date(r.range.end)}</span></div>
        <div class="kpi"><span class="l">Under target</span><span class="v">${F.int(r.totals.misses)}</span><span class="meta">${F.pct(r.totals.misses / r.totals.intervals)} of intervals</span></div>
        <div class="kpi"><span class="l">Material breaches</span><span class="v">${F.int(r.totals.breaches)}</span><span class="meta">beyond random variation</span></div>
        <div class="kpi"><span class="l">Recurring hotspots</span><span class="v">${hs.size}</span><span class="meta">${hs.size ? [...hs].sort().join(', ') : 'none: breaches are scattered'}</span></div>
        <div class="kpi"><span class="l">Lead cause</span><span class="v" style="font-size:17px;padding-top:5px">${esc(lead ? lead.hypothesis : '—')}</span><span class="meta">${lead ? F.pct0(lead.primary_share_vital) + ' of ' + (hs.size ? 'hotspot' : '') + ' breaches' : ''}</span></div>
        <div class="kpi"><span class="l">Abandoned in breaches</span><span class="v">${F.int(r.totals.abandoned_in_breach)}</span><span class="meta">callers lost</span></div>
      </section>
      <div class="grid">
        <section class="card c5"><div class="card-h"><h3>Findings</h3><div class="r">${copilotLink(`Root cause for ${q.code}: ${r.summary.slice(1, 4).join(' ')} What actions should operations and WFM take?`, qid)}</div></div><div class="card-b"><div class="narr">${r.summary.map(s => `<p>${esc(s)}</p>`).join('')}</div></div></section>
        <section class="card c7"><div class="card-h"><h3>Pareto of breaches by half-hour</h3><span class="sub">stacked by primary cause; line is cumulative share</span></div><div class="card-b"><div id="r1"></div><div class="legend" style="margin-top:6px">${['Staffing shortfall', 'Volume spike', 'Handle-time inflation', 'Random variation'].map(c => `<span><i style="background:${CAUSE_COLOR[c]}"></i>${c}</span>`).join('')}<span><i class="line" style="background:var(--ink)"></i>Cumulative</span><span>Bold labels are hotspots</span></div></div></section>
        <section class="card c7"><div class="card-h"><h3>When it started</h3><span class="sub">${hs.size ? 'hotspot intervals' : 'Pareto intervals'}, daily</span><div class="r legend"><span><i style="background:var(--crit);opacity:.5"></i>Breach rate</span><span><i class="line" style="background:var(--s3)"></i>Staffed / required</span></div></div><div class="card-b"><div id="r2"></div></div></section>
        <section class="card c5"><div class="card-h"><h3>Where the lost service level came from</h3><span class="sub">Shapley share of the shortfall, all breach intervals</span></div><div class="card-b" id="r3"></div></section>
        <section class="card c12"><div class="card-h"><h3>Hypotheses tested</h3><span class="sub">breach vs normal intervals · Mann–Whitney U · Shapley primary-cause share</span></div><div class="card-b"><div class="hyp" id="r4"></div></div></section>
        <section class="card c4"><div class="card-h"><h3>By weekday</h3><span class="sub">breach rate</span></div><div class="card-b" id="r5"></div></section>
        <section class="card c8"><div class="card-h"><h3>Staffing gap in ${hs.size ? 'hotspot' : 'breach'} intervals</h3><span class="sub">${r.change_point?.significant ? 'since ' + F.date(r.change_point.date) : 'whole window'}; averages on breach days</span></div><div class="card-b flush" id="r6"></div>${r.whatif ? `<div class="stat-row"><div><b>${F.pct(r.whatif.actual_sl)}</b><span>Queue service level, actual</span></div><div><b>${F.pct(r.whatif.projected_sl)}</b><span>With hotspots staffed to requirement</span></div><div><b>${F.pct(r.whatif.focus_actual_sl)}</b><span>Hotspot breaches, actual</span></div><div><b>${F.pct(r.whatif.focus_projected_sl)}</b><span>Hotspot breaches, at requirement</span></div></div>` : ''}</section>
      </div>
      <p class="muted" style="font-size:12px;margin-top:12px">${esc(r.attribution_method || '')}. Breach rule: interval SL below target by more than 1.645 binomial standard errors (one-sided 95%), minimum ${r.min_offered} contacts.</p>`;
    // Pareto
    const par = r.pareto.filter(p => p.breaches > 0); const pc = Object.fromEntries((r.pareto_causes || []).map(p => [p.label, p]));
    const causes = ['Staffing shortfall', 'Volume spike', 'Handle-time inflation', 'Random variation'];
    comboChart($('#r1'), { x: par.map(p => p.label), height: 330, stacked: true, xTickW: 40,
      series: [...causes.map(c => ({ name: c, values: par.map(p => pc[p.label]?.[c] || 0), kind: 'bar', color: CAUSE_COLOR[c] })),
               { name: 'Cumulative', values: par.map(p => p.cum_share), kind: 'line', axis: 'r', color: 'var(--ink)', width: 1.8, dots: true }],
      yl: { format: F.int }, yr: { format: F.pct0, min: 0, max: 1 }, targets: [{ value: 0.8, axis: 'r', label: '80%' }],
      tipTitle: l => `${l}${hs.has(l) ? ' · hotspot' : ''}`, tipExtra: i => `${par[i].breaches} breaches in ${par[i].intervals} intervals (${F.pct0(par[i].breach_rate)})` });
    $$('#r1 text.ax').forEach(t => { if (hs.has(t.textContent)) { t.style.fontWeight = '700'; t.style.fill = 'var(--ink)'; } });
    // change point
    const dv = r.daily_vital || [];
    const cpIdx = r.change_point?.significant ? dv.findIndex(d => d.date >= r.change_point.date) : -1;
    comboChart($('#r2'), { x: dv.map(d => d.date), xFormat: F.date, height: 240,
      series: [{ name: 'Breach rate', values: dv.map(d => d.breach_rate), kind: 'bar', color: 'var(--crit)', opacity: .5 }, { name: 'Staffed / required', values: dv.map(d => d.staff_ratio), kind: 'line', axis: 'r', color: 'var(--s3)', width: 2 }],
      yl: { format: F.pct0, min: 0, max: 1 }, yr: { format: F.ratio, min: 0.5, max: 1.4 }, targets: [{ value: 1, axis: 'r' }],
      markers: cpIdx >= 0 ? [{ index: cpIdx, label: `Change ${F.date(r.change_point.date)}: ${F.pct0(r.change_point.before)} → ${F.pct0(r.change_point.after)}` }] : [], tipTitle: F.dateLong });
    // shapley share
    const ss = r.shortfall_share || {};
    hbars($('#r3'), Object.entries(ss).map(([k, x]) => ({ label: k, value: x, color: CAUSE_COLOR[k] })), { format: F.pct0, max: 1, labelW: 150 });
    $('#r3').insertAdjacentHTML('beforeend', `<p class="muted" style="font-size:12px;margin-top:14px">For each breach interval the model recomputes service level with staffing, volume and handle time reset to plan in all eight combinations, and splits the gap fairly between them (Shapley values). Weighted by contacts.</p>`);
    // hypotheses
    $('#r4').innerHTML = r.hypotheses.map(h => `<div class="hcard ${h === lead ? 'win' : ''}"><div style="display:flex;gap:8px;align-items:center"><h4>${esc(h.hypothesis)}</h4><span class="pill ${h.verdict === 'Supported' ? 'good' : h.verdict === 'Partly supported' ? 'warn' : ''}" style="margin-left:auto">${esc(h.verdict)}</span></div>
      <p class="ink2" style="font-size:12.5px">${esc(h.description)}.</p>
      <div class="ev"><span>Median in breaches</span><span>${F.ratio(h.median_breach)}</span><span>Median otherwise</span><span>${F.ratio(h.median_ok)}</span><span>Breaches beyond threshold</span><span>${F.pct0(h.share_breach_beyond)}</span><span>Normal beyond threshold</span><span>${F.pct0(h.share_ok_beyond)}</span><span>Mann–Whitney p</span><span>${h.p_value < 1e-4 ? '< 0.0001' : h.p_value.toFixed(4)}</span><span>Primary cause (${hs.size ? 'hotspots' : 'all'})</span><span><b>${F.pct0(h.primary_share_vital)}</b></span></div></div>`).join('');
    hbars($('#r5'), r.by_weekday.map(w => ({ label: w.weekday, value: w.breach_rate, color: 'var(--crit)' })), { format: F.pct0, labelW: 44, max: Math.max(...r.by_weekday.map(w => w.breach_rate)) * 1.1 });
    sortableTable($('#r6'), [
      { key: 'label', label: 'Interval', render: x => `<b class="mono">${x.label}</b>${hs.has(x.label) ? ' <span class="pill crit">hotspot</span>' : ''}` },
      { key: 'breach_days', label: 'Breach days', num: true },
      { key: 'actual', label: 'Volume (fc)', num: true, render: x => `${F.num(x.actual, 0)} <span class="muted">(${F.num(x.forecast, 0)})</span>` },
      { key: 'required', label: 'Required', num: true, render: x => F.num(x.required) },
      { key: 'scheduled', label: 'Scheduled', num: true, render: x => F.num(x.scheduled) },
      { key: 'staffed', label: 'Staffed', num: true, render: x => `<span class="${x.staffed < x.required * 0.9 ? 'st-bad' : ''}">${F.num(x.staffed)}</span>` },
      { key: 'heads_to_add', label: 'Heads to add', num: true, render: x => x.heads_to_add > 0 ? `<b>+${x.heads_to_add}</b>` : '—' },
      { key: 'sl', label: 'SL', num: true, render: x => statusCell('sl', x.sl, q.sl_target) },
    ], (r.staffing_gap || []).filter(x => !hs.size || hs.has(x.label) || x.heads_to_add > 0), { sortKey: 'label', sortDir: 1, idKey: 'label' });
  },
});

/* ---------------- Forecast ---------------- */
page('forecast', {
  title: 'Forecast & staffing', sub: 'Daily volume models, accuracy and the next 14 days of staffing', filters: [],
  async render(v, params, alive) {
    const fc = await cached('forecast', () => API.get('forecast')); if (!alive()) return;
    const res = fc.results; if (!res.length) { v.innerHTML = '<div class="empty">No forecast for your queues.</div>'; return; }
    const qid = params.q && res.some(r => r.queue_id === params.q) ? params.q : res[0].queue_id; const q = queueById(qid); const rr = res.find(r => r.queue_id === qid);
    const models = Object.keys(rr.models); const best = rr.best_model; const met = params.m || 'mape';
    const fmtE = x => met === 'mape' ? x.toFixed(1) + '%' : (met === 'bias' && x > 0 ? '+' : '') + F.num(x, 0);
    v.innerHTML = `<div class="section-h"><div><span class="eyebrow">Train before ${F.date(fc.test_start)} · test ${F.date(fc.test_start)} – 31 May · no shuffling</span><h1>Forecast & staffing plan</h1><p>Each model must beat a 7-day moving-average baseline on a hold-out period that comes after training. The winner forecasts the next 14 days, which Erlang C turns into required heads per interval.</p></div>
      <div class="r"><select id="fq">${res.map(r => `<option value="${r.queue_id}" ${r.queue_id === qid ? 'selected' : ''}>${r.queue_code}</option>`).join('')}</select></div></div>
      <div class="grid">
        <section class="card c12"><div class="card-h"><h3>Model comparison</h3><span class="sub">error on the hold-out period, lower is better</span><div class="r"><div class="seg" id="fm">${[['mape', 'MAPE'], ['mae', 'MAE'], ['rmse', 'RMSE'], ['bias', 'Bias']].map(([k, l]) => `<button data-v="${k}" aria-pressed="${met === k}">${l}</button>`).join('')}</div></div></div><div class="card-b flush" id="f1"></div></section>
        <section class="card c8"><div class="card-h"><h3>${esc(q.code)}: actual vs predicted</h3><span class="sub">hold-out period</span><div class="r legend"><span><i class="line" style="background:var(--ink)"></i>Actual</span><span><i class="line" style="background:var(--s1)"></i>${esc(best)}</span><span><i class="dash"></i>Moving average</span></div></div><div class="card-b"><div id="f2"></div><div id="f2b" style="margin-top:6px"></div></div></section>
        <section class="card c4"><div class="card-h"><h3>What drives the forecast</h3><span class="sub">random forest importance</span></div><div class="card-b" id="f3"></div></section>
        <section class="card c5"><div class="card-h"><h3>Next 14 days</h3><span class="sub">${esc(fc.forecast.find(x => x.queue_id === qid)?.model || '')}, recursive</span></div><div class="card-b"><div id="f4"></div></div>${(() => { const sm = fc.staffing_plan.summary.find(x => x.queue_id === qid); return sm ? `<div class="stat-row"><div><b>${F.int(sm.forecast)}</b><span>contacts forecast</span></div><div><b>${F.int(sm.short_intervals)}</b><span>intervals short</span></div><div><b>${F.pct0(sm.coverage)}</b><span>roster coverage</span></div></div>` : ''; })()}</section>
        <section class="card c7"><div class="card-h"><h3>Staffing plan vs current roster</h3><span class="sub">heads needed minus heads rostered (same weekday, last 2 weeks)</span><div class="r" id="f5l"></div></div><div class="card-b"><div id="f5" style="max-height:420px;overflow:auto"></div></div></section>
      </div>
      <div class="card" style="margin-top:14px"><div class="card-b"><div class="narr">${fc.notes.map(n => `<p>${esc(n)}</p>`).join('')}</div></div></div>`;
    $('#fq').onchange = e => go('forecast', { q: e.target.value, m: met });
    seg($('#fm'), m => go('forecast', { q: qid, m }));
    const cols = Object.keys(res[0].models);
    sortableTable($('#f1'), [
      { key: 'queue_code', label: 'Queue', render: r => `<b>${esc(r.queue_code)}</b>` },
      ...cols.map(m => ({ key: m, label: m, num: true, render: r => { const x = r.models[m][met]; return `<span class="mono ${m === r.best_model ? 'st-good' : ''}" style="${m === r.best_model ? 'font-weight:700' : ''}">${fmtE(x)}</span>`; } })),
      { key: 'best_model', label: 'Best' },
      { key: 'improvement_vs_baseline', label: 'vs baseline', num: true, render: r => `<span class="delta ${r.improvement_vs_baseline > 0 ? 'up' : 'down'}">${r.improvement_vs_baseline > 0 ? '−' : '+'}${Math.abs(r.improvement_vs_baseline * 100).toFixed(0)}% error</span>` },
    ], res.map(r => ({ ...r, id: r.queue_id, ...Object.fromEntries(cols.map(m => [m, met === 'bias' ? Math.abs(r.models[m].bias) : r.models[m][met]])) })), { onRow: r => go('forecast', { q: r.queue_id, m: met }), selected: r => r.queue_id === qid, sortKey: 'queue_code', sortDir: 1 });
    const pred = fc.predictions.filter(p => p.queue_id === qid);
    comboChart($('#f2'), { x: pred.map(p => p.date), xFormat: F.date, height: 240, series: [
      { name: 'Actual', values: pred.map(p => p.actual), kind: 'line', color: 'var(--ink)', width: 2.2 },
      { name: best, values: pred.map(p => p[best]), kind: 'line', color: 'var(--s1)', width: 2 },
      { name: 'Moving average', values: pred.map(p => p['Moving average (7-day)']), kind: 'line', color: 'var(--ink-3)', dash: '4 3', width: 1.4 }],
      yl: { format: F.int }, tipTitle: F.dateLong });
    const resid = pred.map(p => p.actual - p[best]);
    comboChart($('#f2b'), { x: pred.map(p => p.date), xFormat: F.date, height: 110, series: [{ name: 'Residual (actual − forecast)', values: resid, kind: 'bar', color: 'var(--s1)', colorAt: (i, x) => x > 0 ? 'var(--s2)' : 'var(--s1)' }], yl: { format: F.int }, ticks: 2, tipTitle: F.dateLong });
    const imp = fc.importance[q.code] || {};
    const WD = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday'];
    const FL = { lag_1: 'Volume 1 day before', lag_7: 'Volume 7 days before', lag_14: 'Volume 14 days before', roll_mean_7: '7-day mean', roll_mean_28: '28-day mean', roll_std_7: '7-day volatility', dow: 'Day of week', month: 'Month', is_holiday: 'Holiday', pre_holiday: 'Day before holiday', staffing_ratio_lag1: 'Staffing ratio, prior day', aht_lag1: 'AHT, prior day', day_of_month: 'Day of month', trend: 'Trend' };
    const flab = k => FL[k] || (/^dow_(\d)$/.test(k) ? WD[+k.slice(4)] + ' (flag)' : k.replaceAll('_', ' '));
    hbars($('#f3'), Object.entries(imp).map(([k, x]) => ({ label: flab(k), value: x, color: 'var(--s1)' })), { format: x => (x * 100).toFixed(1) + '%', labelW: 160 });
    $('#f3').insertAdjacentHTML('beforeend', `<p class="muted" style="font-size:12px;margin-top:12px">Features: ${fc.features.map(flab).join(', ')}. Lags and rolling windows use only data available on the morning of the forecast day.</p>`);
    const fut = fc.forecast.filter(x => x.queue_id === qid);
    const hist = (() => { const rows = Cube.rows({ start: addDays(STATE.meta.period.end, -20), end: STATE.meta.period.end, queues: [qid] }); const g = Cube.group(rows, i => Cube.dateStr[i], ['offered']); return [...g.entries()].sort().map(([d, s]) => ({ d, v: s.offered })); })();
    comboChart($('#f4'), { x: [...hist.map(h => h.d), ...fut.map(x => x.date)], xFormat: F.date, height: 300, series: [
      { name: 'Actual', values: [...hist.map(h => h.v), ...fut.map(() => null)], kind: 'line', color: 'var(--ink)', width: 2 },
      { name: 'Forecast', values: [...hist.map(() => null), ...fut.map(x => x.forecast)], kind: 'line', color: 'var(--s1)', width: 2, dash: '5 3', dots: true }],
      yl: { format: F.int }, markers: [{ index: hist.length, label: 'Forecast' }], tipTitle: F.dateLong });
    const iv = fc.staffing_plan.intervals.filter(x => x.queue_id === qid);
    const dates = [...new Set(iv.map(x => x.date))].sort(); const ivs = [...new Set(iv.map(x => x.interval_idx))].sort((a, b) => a - b);
    const m = new Map(iv.map(x => [x.date + '|' + x.interval_idx, x]));
    const fn = scaleDiv(0, 4);
    heatmap($('#f5'), { rows: dates.map(d => `${F.date(d)} ${new Date(d + 'T00:00:00').toLocaleDateString('en-GB', { weekday: 'short' })}`), cols: ivs.map(i => STATE.meta.intervals[i].slice(0, 2)), colEvery: 2, minWidth: 640,
      values: dates.map(d => ivs.map(i => { const x = m.get(d + '|' + i); return x ? -x.gap : null; })), color: fn, text: x => Math.round(x) === 0 ? '' : (x > 0 ? '+' : '') + Math.round(x),
      title: (r, c) => { const x = m.get(dates[r] + '|' + ivs[c]); return `${dates[r]} ${STATE.meta.intervals[ivs[c]]}: forecast ${F.num(x.forecast)}; need ${x.heads_needed} heads, rostered ${F.num(x.current_roster)} (${x.gap > 0 ? 'short ' + F.num(x.gap) : 'surplus ' + F.num(-x.gap)})`; } });
    $('#f5l').innerHTML = heatLegend(fn, -4, 4, x => (x > 0 ? '+' : '') + Math.round(x), 'red = short');
  },
});

/* ---------------- Alerts ---------------- */
page('alerts', {
  title: 'Alerts', sub: 'Anomalies, sustained shifts and recurring hotspots', filters: ['client', 'channel', 'queues'],
  async render(v, params, alive) {
    const a = await cached('alerts', () => API.get('alerts')); if (!alive()) return;
    const qs = new Set(selectedQueues()); const sev = params.sev || 'all';
    const SR = { critical: 0, high: 1, medium: 2, info: 3 };
    const list = a.incidents.filter(i => qs.has(i.queue_id) && (sev === 'all' || i.severity === sev))
      .sort((x, y) => SR[x.severity] - SR[y.severity] || (y.kpi === 'sl_hotspot') - (x.kpi === 'sl_hotspot') || (y.days || 1) - (x.days || 1) || (y.end > x.end ? 1 : y.end < x.end ? -1 : 0));
    const sel = list.find(i => i.incident_id === params.id) || list[0];
    const count = s => a.incidents.filter(i => qs.has(i.queue_id) && i.severity === s).length;
    v.innerHTML = `<div class="section-h"><div><span class="eyebrow">${esc(a.method || '')}</span><h1>Alerts</h1><p>Daily KPIs are compared with a robust rolling baseline; seven-day shifts and recurring interval hotspots from root-cause analysis are added. Each incident can be turned into recommended actions by the copilot.</p></div>
      <div class="r"><div class="seg" id="as">${[['all', 'All'], ['critical', `Critical ${count('critical')}`], ['high', `High ${count('high')}`], ['medium', `Medium ${count('medium')}`], ['info', 'Info']].map(([k, l]) => `<button data-v="${k}" aria-pressed="${sev === k}">${l}</button>`).join('')}</div></div></div>
      <div class="grid"><section class="card c5"><div class="card-h"><h3>Incidents</h3><span class="sub">${list.length}</span></div><div class="card-b flush"><div class="list" style="max-height:72vh;overflow:auto">${list.map(i => `<div class="li ${sel && i.incident_id === sel.incident_id ? 'sel' : ''}" data-id="${i.incident_id}"><span class="sev ${i.severity}"></span><div class="t"><b>${esc(i.queue_code)} · ${esc(i.kpi_label)}</b><small>${i.start === i.end ? F.dateLong(i.start) : `${F.date(i.start)} – ${F.date(i.end)}`}${i.days ? ` · ${i.days} day${i.days > 1 ? 's' : ''}` : ''}${i.likely_driver ? ' · ' + esc(i.likely_driver) : ''}</small></div><span class="pill ${i.severity === 'critical' ? 'crit' : i.severity === 'high' ? 'serious' : i.severity === 'info' ? 'info' : 'warn'}">${i.severity}</span></div>`).join('') || '<div class="empty">No incidents for these filters.</div>'}</div></div></section>
      <section class="card c7" id="ad"></section></div>`;
    seg($('#as'), s => go('alerts', { sev: s }));
    $$('.li[data-id]').forEach(li => li.onclick = () => go('alerts', { sev, id: li.dataset.id }));
    if (sel) renderIncident($('#ad'), sel);
  },
});
function renderIncident(host, i) {
  const q = queueById(i.queue_id); const kmap = { sl: 'sl', sl_shift: 'sl', sl_hotspot: 'sl', abandon_rate: 'abandon_rate', abandon_rate_shift: 'abandon_rate', aht: 'aht', offered: 'offered', csat: 'csat' };
  const mid = kmap[i.kpi] || 'sl'; const start = addDays(i.start, -21) < STATE.meta.period.start ? STATE.meta.period.start : addDays(i.start, -21); const end = addDays(i.end, 10) > STATE.meta.period.end ? STATE.meta.period.end : addDays(i.end, 10);
  const rows = Cube.rows({ start, end, queues: [i.queue_id] }); const dly = daily(rows, [mid, 'staffing_ratio', 'offered', 'forecast_volume']);
  const a = dly.days.findIndex(d => d >= i.start), b = dly.days.findIndex(d => d > i.end);
  host.innerHTML = `<div class="card-h"><span class="sev ${i.severity}" style="margin:0"></span><h3>${esc(i.queue_code)} · ${esc(i.kpi_label)}</h3><div class="r">${i.kpi.startsWith('sl') && q.realtime ? `<button class="btn btn-sm" onclick="go('rca',{queue:'${i.queue_id}'})">Root cause ${ICON.arrow}</button>` : ''}<button class="btn btn-sm" onclick="go('intraday',{q:'${i.queue_id}',d:'${i.start}'})">Intraday</button></div></div>
    <div class="card-b" style="display:flex;flex-direction:column;gap:14px">
      <dl class="kv"><dt>Period</dt><dd>${F.dateLong(i.start)}${i.end !== i.start ? ' to ' + F.dateLong(i.end) : ''}</dd>
      ${i.peak_value != null ? `<dt>Worst value</dt><dd><b>${fmtMetric(mid, i.peak_value)}</b> against a baseline of ${fmtMetric(mid, i.baseline)}${i.peak_z != null ? ` (z = ${F.num(i.peak_z, 1)})` : ''}</dd>` : `<dt>Target</dt><dd>${F.pct0(i.baseline)}</dd>`}
      <dt>Likely driver</dt><dd>${esc(i.likely_driver || 'Not determined from daily data')}</dd>${i.note ? `<dt>Note</dt><dd>${esc(i.note)}</dd>` : ''}</dl>
      <div id="ic"></div>
      <div class="insight info"><div><b>Recommended actions</b><p>The copilot retrieves the relevant SOPs and past RCAs and drafts actions with citations.</p><div class="acts"><button class="btn btn-sm btn-primary" id="recBtn">${ICON.spark}Get recommendation</button></div><div id="recOut" style="margin-top:10px"></div></div></div>
    </div>`;
  comboChart($('#ic'), { x: dly.days, xFormat: F.date, height: 230, bands: a >= 0 ? [{ from: a, to: (b < 0 ? dly.days.length : b) - 1, color: 'color-mix(in srgb, var(--crit) 10%, transparent)', label: 'Incident' }] : [],
    series: [{ name: M.reg[mid].label, values: dly.val(mid), kind: mid === 'offered' ? 'bar' : 'line', color: 'var(--s1)', width: 2.2, opacity: .5 }, ...(mid === 'offered' ? [{ name: 'Forecast', values: dly.val('forecast_volume'), kind: 'line', color: 'var(--ink-2)', dash: '4 3' }] : [{ name: 'Staffed / required', values: dly.val('staffing_ratio'), kind: 'line', axis: 'r', color: 'var(--s3)', dash: '4 3', width: 1.5 }])],
    yl: { format: M.reg[mid].unit === 'pct' ? F.pct0 : M.reg[mid].unit === 'sec' ? F.secs : F.int, ...(M.reg[mid].unit === 'pct' ? { max: 1 } : {}) }, yr: { format: F.ratio }, tipTitle: F.dateLong,
    targets: mid === 'sl' ? [{ value: q.sl_target, label: 'Target' }] : mid === 'aht' ? [{ value: q.aht_target_sec, label: 'Target' }] : [] });
  $('#recBtn').onclick = async () => {
    const out = $('#recOut'); out.innerHTML = '<div class="skeleton" style="min-height:90px"></div>'; $('#recBtn').disabled = true;
    try { const r = await API.post(`alerts/${encodeURIComponent(i.incident_id)}/recommend`); out.innerHTML = answerHTML(r); bindCites(out, r); }
    catch (e) { out.innerHTML = `<p class="st-bad">${esc(e.message)}</p>`; }
    $('#recBtn').disabled = false;
  };
}
