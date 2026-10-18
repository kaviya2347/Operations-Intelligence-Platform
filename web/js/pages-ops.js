/* Operations pages: Command center, Queue performance, Intraday, Agents. */
'use strict';

const KPI_SET = ['offered', 'sl', 'abandon_rate', 'asa', 'aht', 'fcr', 'csat', 'occupancy', 'shrinkage', 'staffing_ratio'];

function scope(over = {}) {
  const f = STATE.filters; const queues = selectedQueues(over);
  const rows = Cube.rows({ start: f.start, end: f.end, queues });
  const pr = prevRange(f.start, f.end); const prevOk = pr.start >= STATE.meta.period.start;
  const prev = prevOk ? Cube.rows({ start: pr.start, end: pr.end, queues }) : null;
  return { queues, rows, prev, pr: prevOk ? pr : null };
}
function daily(rows, ids) {
  const g = Cube.group(rows, i => Cube.dateStr[i], metricCols(ids));
  const days = [...g.keys()].sort();
  return { days, val: id => days.map(d => metricValue(id, g.get(d))) };
}
function scopeLabel() {
  const f = STATE.filters; const qs = selectedQueues();
  const cl = f.client === 'all' ? (STATE.meta.clients.length === 1 ? STATE.meta.clients[0].client_name : 'All clients') : STATE.meta.clients.find(c => c.client_id === f.client)?.client_name;
  return `${cl} · ${qs.length} queue${qs.length === 1 ? '' : 's'}${f.channel !== 'all' ? ' · ' + f.channel : ''}`;
}
function holidayMarkers(days) { return days.map((d, i) => ({ d, i, h: STATE.meta.dates.find(x => x.date === d) })).filter(x => x.h?.is_holiday).map(x => ({ index: x.i, label: x.h.holiday_name })); }

/* ---------------- Command center ---------------- */
page('overview', {
  title: 'Command center', sub: 'Service, efficiency and quality across every client', filters: ['date', 'client', 'channel', 'queues'],
  async render(v, params, alive) {
    const S = scope(); const f = STATE.filters;
    if (!S.rows.length) { v.innerHTML = '<div class="empty">No data for these filters.</div>'; return; }
    const cur = compute(KPI_SET, S.rows), prev = S.prev ? compute(KPI_SET, S.prev) : {};
    const dly = daily(S.rows, KPI_SET);
    const alerts = await cached('alerts', () => API.get('alerts'));
    if (!alive()) return;
    const inRange = alerts.incidents.filter(i => S.queues.includes(i.queue_id) && i.end >= f.start && i.start <= f.end && i.severity !== 'info');
    v.innerHTML = `
      ${API.mode === 'static' ? `<div class="banner info">${ICON.spark}<span><b>Offline snapshot.</b> All dashboards are live on precomputed data; the SQL lab and custom-range root-cause runs need the local server (<span class="mono">python -m oip serve</span>).</span></div>` : ''}
      <div class="section-h"><div><span class="eyebrow">${esc(scopeLabel())}</span><h1>Operations at a glance</h1><p>${F.dateLong(f.start)} to ${F.dateLong(f.end)}${S.pr ? `, compared with the previous ${daysBetween(f.start, f.end) + 1} days` : ''}.</p></div>
        <div class="r"><button class="btn" onclick="go('alerts')">${ICON.bell}${inRange.length} open incidents</button><button class="btn btn-primary" onclick="go('copilot')">${ICON.spark}Ask the copilot</button></div></div>
      <section class="kpis" style="margin-bottom:14px" id="kpis"></section>
      <div class="grid">
        <section class="card c8"><div class="card-h"><h3>Volume and service level</h3><span class="sub">daily · bars offered, line service level</span><div class="r legend"><span><i style="background:var(--s1);opacity:.35"></i>Offered</span><span><i class="line" style="background:var(--s2)"></i>Service level</span><span><i class="dash"></i>Target</span></div></div><div class="card-b"><div id="volChart"></div></div></section>
        <section class="card c4"><div class="card-h"><h3>Needs attention</h3><span class="sub">${inRange.length} incidents in range</span><div class="r"><button class="btn btn-sm btn-ghost" onclick="go('alerts')">All ${ICON.arrow}</button></div></div><div class="card-b" style="display:flex;flex-direction:column;gap:10px" id="attn"></div></section>
        <section class="card c12"><div class="card-h"><h3>Client scorecard</h3><span class="sub">queue results against contract targets</span></div><div class="card-b flush" id="score"></div></section>
        <section class="card c6"><div class="card-h"><h3>Service level by week</h3><span class="sub">points above or below each queue's target</span></div><div class="card-b"><div id="weekHeat"></div><div id="weekLeg" style="margin-top:10px"></div></div></section>
        <section class="card c6"><div class="card-h"><h3>Capacity</h3><span class="sub">staffed vs required, by client</span></div><div class="card-b" id="cap"></div></section>
        <section class="card c6"><div class="card-h"><h3>Work by channel</h3></div><div class="card-b" id="chan"></div></section>
        <section class="card c6"><div class="card-h"><h3>Quality</h3><span class="sub">FCR and CSAT by client</span></div><div class="card-b" id="qual"></div></section>
      </div>`;
    const tgt = id => targetFor(id, S.rows);
    $('#kpis').innerHTML = KPI_SET.map(id => kpiTile(id, cur[id], prev[id], tgt(id), sparkline(dly.val(id), { color: 'var(--s1)', target: tgt(id) }))).join('');
    const days = dly.days; const slT = tgt('sl');
    comboChart($('#volChart'), {
      x: days, xFormat: d => F.date(d), height: 300, aria: 'Daily offered contacts and service level',
      series: [{ name: 'Offered', values: dly.val('offered'), kind: 'bar', color: 'var(--s1)', opacity: .35 },
               { name: 'Service level', values: dly.val('sl'), kind: 'line', axis: 'r', color: 'var(--s2)', width: 2.2 }],
      yr: { format: F.pct0, min: Math.min(0.5, ...dly.val('sl').filter(x => x != null)), max: 1 }, yl: { format: F.compact },
      targets: slT ? [{ value: slT, axis: 'r', label: `Target ${F.pct0(slT)}` }] : [], markers: holidayMarkers(days),
      tipTitle: d => F.dateLong(d),
    });
    const sevRank = { critical: 0, high: 1, medium: 2 };
    const top = inRange.slice().sort((a, b) => (a.kpi === 'sl_hotspot' ? -1 : 0) - (b.kpi === 'sl_hotspot' ? -1 : 0) || sevRank[a.severity] - sevRank[b.severity] || (b.days || 0) - (a.days || 0)).slice(0, 3);
    $('#attn').innerHTML = top.map(i => `<div class="insight ${i.severity === 'critical' ? 'crit' : 'warn'}"><div><b>${esc(i.queue_code)} · ${esc(i.kpi_label)}</b><p>${i.start === i.end ? F.date(i.start) : `${F.date(i.start)} – ${F.date(i.end)}`}${i.likely_driver ? ' · likely driver: ' + esc(i.likely_driver.toLowerCase()) : ''}</p>
      <div class="acts">${i.kpi === 'sl_hotspot' ? `<button class="btn btn-sm" onclick="go('rca',{queue:'${i.queue_id}'})">Root cause ${ICON.arrow}</button>` : `<button class="btn btn-sm" onclick="go('alerts',{id:'${i.incident_id}'})">Investigate ${ICON.arrow}</button>`}${copilotLink(`${i.queue_code} ${i.kpi_label} ${i.start} to ${i.end}: what should we do?`, i.queue_id)}</div></div></div>`).join('') || '<div class="empty">No incidents in this range.</div>';

    // scorecard
    const g = Cube.group(S.rows, i => Cube.d.queue_id[i], metricCols(['offered', 'sl', 'abandon_rate', 'aht', 'fcr', 'csat']));
    const dq = Cube.group(S.rows, i => Cube.d.queue_id[i] + '|' + Cube.dateStr[i], metricCols(['sl']));
    const rowsT = [...g.entries()].map(([qid, s]) => { const q = queueById(qid); const cl = STATE.meta.clients.find(c => c.client_id === q.client_id);
      const tr = [...dq.entries()].filter(([k]) => k.startsWith(qid + '|')).sort().map(([, s2]) => metricValue('sl', s2));
      return { id: qid, client: cl.client_name, code: q.code, name: q.name, channel: q.channel, offered: metricValue('offered', s), sl: metricValue('sl', s), slT: q.sl_target, abd: q.realtime ? metricValue('abandon_rate', s) : null, abdT: q.abandon_target, aht: metricValue('aht', s), ahtT: q.aht_target_sec, fcr: metricValue('fcr', s), csat: metricValue('csat', s), trend: tr }; })
      .sort((a, b) => a.client.localeCompare(b.client) || a.code.localeCompare(b.code));
    sortableTable($('#score'), [
      { key: 'code', label: 'Queue', render: r => `<div class="qname"><b>${esc(r.code)}</b><small>${esc(r.client)} · ${esc(r.channel)}</small></div>` },
      { key: 'offered', label: 'Offered', num: true, render: r => F.int(r.offered) },
      { key: 'sl', label: 'Service level', num: true, render: r => `${statusCell('sl', r.sl, r.slT)} <span class="muted mono" style="font-size:11px">/${F.pct0(r.slT)}</span>` },
      { key: 'trend', label: 'Trend', sort: false, render: r => sparkline(r.trend, { w: 70, h: 20, target: r.slT, color: r.sl >= r.slT ? 'var(--s1)' : 'var(--crit)' }) },
      { key: 'abd', label: 'Abandon', num: true, render: r => r.abd == null ? '<span class="muted">n/a</span>' : statusCell('abandon_rate', r.abd, r.abdT) },
      { key: 'aht', label: 'AHT', num: true, render: r => statusCell('aht', r.aht, r.ahtT) },
      { key: 'fcr', label: 'FCR', num: true, render: r => F.pct(r.fcr) },
      { key: 'csat', label: 'CSAT', num: true, render: r => F.pct(r.csat) },
    ], rowsT, { onRow: r => go('queues', { q: r.id }) });

    // weekly heat
    const wk = Cube.group(S.rows, i => Cube.d.queue_id[i] + '|' + STATE.meta.dates.find(d => d.date_key === Cube.d.date_key[i]).iso_week, ['sl_num', 'sl_den']);
    const weeks = [...new Set([...wk.keys()].map(k => +k.split('|')[1]))].sort((a, b) => a - b);
    const qids = rowsT.map(r => r.id);
    const wkStart = w => STATE.meta.dates.find(d => d.iso_week === w)?.date;
    const vals = qids.map(q => weeks.map(w => { const s = wk.get(q + '|' + w); return s && s.sl_den ? s.sl_num / s.sl_den - queueById(q).sl_target : null; }));
    const div = scaleDiv(0, 0.15);
    heatmap($('#weekHeat'), { rows: qids.map(q => queueById(q).code), cols: weeks.map(w => F.date(wkStart(w))), values: vals, color: div, text: x => (x * 100 >= 0 ? '+' : '') + Math.round(x * 100), title: (r, c, x) => `${queueById(qids[r]).code}, week of ${F.date(wkStart(weeks[c]))}: ${(x * 100).toFixed(1)} pts vs target`, colEvery: Math.ceil(weeks.length / 7), onClick: (r) => go('queues', { q: qids[r] }) });
    $('#weekLeg').innerHTML = heatLegend(div, -0.15, 0.15, x => (x >= 0 ? '+' : '') + Math.round(x * 100) + ' pts', 'vs target');

    // channel / capacity / quality
    const ch = Cube.group(S.rows, i => queueById(Cube.d.queue_id[i]).channel, ['offered', 'handle_sec']);
    hbars($('#chan'), [...ch.entries()].sort((a, b) => b[1].offered - a[1].offered).map(([k, s], i) => ({ label: k, value: s.offered, color: sc(i) })), { format: F.compact, labelW: 90 });
    $('#chan').insertAdjacentHTML('beforeend', `<p class="muted" style="font-size:12px;margin-top:12px">Agent hours worked: <b class="mono" style="color:var(--ink)">${F.int(sum([...ch.values()].map(s => s.handle_sec)) / 3600)}</b></p>`);
    const byClient = Cube.group(S.rows, i => queueById(Cube.d.queue_id[i]).client_id, metricCols(['staffing_ratio', 'occupancy', 'fcr', 'csat']));
    const cname = id => STATE.meta.clients.find(c => c.client_id === id)?.client_name;
    hbars($('#cap'), [...byClient.entries()].map(([k, s]) => ({ label: cname(k), value: metricValue('staffing_ratio', s), color: metricValue('staffing_ratio', s) >= 1 ? 'var(--s1)' : 'var(--crit)' })), { format: F.pct0, max: 1.3, target: 1, labelW: 120 });
    $('#cap').insertAdjacentHTML('beforeend', `<div class="stat-row" style="margin:14px -16px -14px"><div><b>${F.pct(cur.occupancy)}</b><span>Occupancy</span></div><div><b>${F.pct(cur.shrinkage)}</b><span>Shrinkage (plan 30%)</span></div></div>`);
    $('#qual').innerHTML = [...byClient.entries()].map(([k, s]) => `<div style="display:grid;grid-template-columns:120px 1fr 1fr;gap:10px;align-items:center;font-size:12.5px;padding:5px 0"><span class="ink2">${esc(cname(k))}</span>${cellbar(metricValue('fcr', s), metricValue('fcr', s), 'var(--s3)', F.pct0)}${cellbar(metricValue('csat', s), metricValue('csat', s), 'var(--s7)', F.pct0)}</div>`).join('') + `<div class="legend" style="margin-top:8px"><span><i style="background:var(--s3)"></i>FCR (target 80%)</span><span><i style="background:var(--s7)"></i>CSAT (target 85%)</span></div>`;
  },
});

/* ---------------- Queue performance ---------------- */
page('queues', {
  title: 'Queue performance', sub: 'Every queue against its contract, with drill-down', filters: ['date', 'client', 'channel', 'queues'],
  async render(v, params) {
    const S = scope(); if (!S.rows.length) { v.innerHTML = '<div class="empty">No data for these filters.</div>'; return; }
    const ids = ['offered', 'sl', 'abandon_rate', 'asa', 'aht', 'fcr', 'csat', 'occupancy', 'staffing_ratio', 'transfer_rate'];
    const g = Cube.group(S.rows, i => Cube.d.queue_id[i], metricCols(ids));
    const rows = [...g.entries()].map(([qid, s]) => ({ id: qid, q: queueById(qid), ...Object.fromEntries(ids.map(id => [id, metricValue(id, s)])) }));
    const sel = params.q && g.has(params.q) ? params.q : rows.slice().sort((a, b) => (a.sl - a.q.sl_target) - (b.sl - b.q.sl_target))[0].id;
    v.innerHTML = `<div class="section-h"><div><span class="eyebrow">${esc(scopeLabel())}</span><h1>Queue performance</h1><p>Click a queue to drill in. Colours compare each value with that queue's own contract target.</p></div></div>
      <section class="card" style="margin-bottom:14px"><div class="card-b flush" id="qtable"></div></section>
      <div id="qdetail"></div>`;
    sortableTable($('#qtable'), [
      { key: 'id', label: 'Queue', render: r => `<div class="qname"><b>${esc(r.q.code)} · ${esc(r.q.name)}</b><small>${esc(STATE.meta.clients.find(c => c.client_id === r.q.client_id).client_name)} · ${r.q.channel}</small></div>` },
      { key: 'offered', label: 'Offered', num: true, render: r => F.int(r.offered) },
      { key: 'sl', label: 'Service level', num: true, render: r => cellbar(r.sl, r.sl, r.sl >= r.q.sl_target ? 'var(--good)' : 'var(--crit)', F.pct) },
      { key: 'abandon_rate', label: 'Abandon', num: true, render: r => r.q.realtime ? statusCell('abandon_rate', r.abandon_rate, r.q.abandon_target) : '<span class="muted">n/a</span>' },
      { key: 'asa', label: 'ASA', num: true, render: r => r.q.realtime ? F.secs(r.asa) : '<span class="muted">n/a</span>' },
      { key: 'aht', label: 'AHT', num: true, render: r => statusCell('aht', r.aht, r.q.aht_target_sec) },
      { key: 'fcr', label: 'FCR', num: true, render: r => statusCell('fcr', r.fcr, STATE.meta.targets.fcr_target) },
      { key: 'csat', label: 'CSAT', num: true, render: r => statusCell('csat', r.csat, STATE.meta.targets.csat_target) },
      { key: 'occupancy', label: 'Occupancy', num: true, render: r => F.pct(r.occupancy) },
      { key: 'staffing_ratio', label: 'Staffed/req.', num: true, render: r => `<span class="${r.staffing_ratio < 0.97 ? 'st-bad' : ''}">${F.pct0(r.staffing_ratio)}</span>` },
    ], rows, { onRow: r => go('queues', { q: r.id }), selected: r => r.id === sel });
    renderQueueDetail($('#qdetail'), sel, S);
  },
});
function renderQueueDetail(host, qid, S) {
  const q = queueById(qid); const f = STATE.filters;
  const rows = Cube.rows({ start: f.start, end: f.end, queues: [qid] });
  const prev = S.pr ? Cube.rows({ start: S.pr.start, end: S.pr.end, queues: [qid] }) : null;
  const ids = q.realtime ? ['offered', 'sl', 'abandon_rate', 'asa', 'aht', 'fcr', 'csat', 'staffing_ratio'] : ['offered', 'sl', 'aht', 'fcr', 'csat', 'occupancy', 'staffing_ratio'];
  const cur = compute(ids, rows), pv = prev ? compute(ids, prev) : {}; const dly = daily(rows, ids);
  const tgt = { sl: q.sl_target, aht: q.aht_target_sec, abandon_rate: q.abandon_target, fcr: STATE.meta.targets.fcr_target, csat: STATE.meta.targets.csat_target };
  host.innerHTML = `<div class="section-h"><div><span class="eyebrow">${esc(STATE.meta.clients.find(c => c.client_id === q.client_id).client_name)} · ${q.channel} · ${q.open_hour}:00–${q.close_hour}:00</span><h1>${esc(q.code)} · ${esc(q.name)}</h1>
      <p>Target ${F.pct0(q.sl_target)} ${q.channel === 'Email' || q.channel === 'Back office' ? `first response within ${q.sl_threshold_sec / 3600} business hours` : `answered within ${q.sl_threshold_sec}s`}; AHT target ${F.sec(q.aht_target_sec)}.</p></div>
      <div class="r"><button class="btn" onclick="go('intraday',{q:'${qid}'})">Intraday view</button>${q.realtime ? `<button class="btn btn-primary" onclick="go('rca',{queue:'${qid}'})">Root-cause analysis ${ICON.arrow}</button>` : ''}</div></div>
    <section class="kpis" style="margin-bottom:14px">${ids.map(id => kpiTile(id, cur[id], pv[id], tgt[id] ?? null, sparkline(dly.val(id), { target: tgt[id] }))).join('')}</section>
    <div class="grid">
      <section class="card c7"><div class="card-h"><h3>Daily service level</h3><div class="r legend"><span><i style="background:var(--s1);opacity:.35"></i>Offered</span><span><i class="line" style="background:var(--s2)"></i>Service level</span><span><i class="line" style="background:var(--s3)"></i>Staffed / required</span></div></div><div class="card-b"><div id="qd1"></div></div></section>
      <section class="card c5"><div class="card-h"><h3>Handle time by week</h3><span class="sub">talk, hold and after-call work</span></div><div class="card-b"><div id="qd2"></div><div class="legend" style="margin-top:8px"><span><i style="background:var(--s1)"></i>Talk</span><span><i style="background:var(--s4)"></i>Hold</span><span><i style="background:var(--s7)"></i>ACW</span><span><i class="dash"></i>Target</span></div></div></section>
      <section class="card c12"><div class="card-h"><h3>When service level slips</h3><span class="sub">weekday × half-hour, points vs ${F.pct0(q.sl_target)} target, selected period</span><div class="r" id="qd3l"></div></div><div class="card-b"><div id="qd3"></div></div></section>
    </div>`;
  comboChart($('#qd1'), { x: dly.days, xFormat: F.date, height: 250, series: [
    { name: 'Offered', values: dly.val('offered'), kind: 'bar', color: 'var(--s1)', opacity: .32 },
    { name: 'Service level', values: dly.val('sl'), kind: 'line', axis: 'r', color: 'var(--s2)', width: 2.2 },
    { name: 'Staffed / required', values: dly.val('staffing_ratio'), kind: 'line', axis: 'r', color: 'var(--s3)', width: 1.6, dash: '4 3' }],
    yr: { format: F.pct0, min: 0.4, max: 1.3 }, yl: { format: F.compact }, targets: [{ value: q.sl_target, axis: 'r' }], markers: holidayMarkers(dly.days), tipTitle: F.dateLong });
  const wk = Cube.group(rows, i => STATE.meta.dates.find(d => d.date_key === Cube.d.date_key[i]).iso_week, ['talk_sec', 'hold_sec', 'acw_sec', 'handled']);
  const weeks = [...wk.keys()].sort((a, b) => a - b); const wl = weeks.map(w => STATE.meta.dates.find(d => d.iso_week === w).date);
  comboChart($('#qd2'), { x: wl, xFormat: F.date, height: 250, stacked: true, series: [
    { name: 'Talk', values: weeks.map(w => wk.get(w).talk_sec / wk.get(w).handled), kind: 'bar', color: 'var(--s1)' },
    { name: 'Hold', values: weeks.map(w => wk.get(w).hold_sec / wk.get(w).handled), kind: 'bar', color: 'var(--s4)' },
    { name: 'ACW', values: weeks.map(w => wk.get(w).acw_sec / wk.get(w).handled), kind: 'bar', color: 'var(--s7)' }],
    yl: { format: F.secs }, targets: [{ value: q.aht_target_sec }], tipTitle: d => 'Week of ' + F.date(d) });
  const wd = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun'];
  const ivs = []; for (let i = q.realtime ? q.open_hour * 2 : 0; i < (q.realtime ? q.close_hour * 2 : 48); i++) ivs.push(i);
  const hg = Cube.group(rows, i => Cube.weekday[i] + '|' + Cube.d.interval_idx[i], ['sl_num', 'sl_den', 'offered']);
  const vals = wd.map(d => ivs.map(i => { const s = hg.get(d + '|' + i); return s && s.sl_den >= 10 ? s.sl_num / s.sl_den - q.sl_target : null; }));
  const div = scaleDiv(0, 0.2);
  heatmap($('#qd3'), { rows: wd, cols: ivs.map(i => STATE.meta.intervals[i]), values: vals, color: div, text: x => Math.round(x * 100), colEvery: 2, minWidth: 720,
    title: (r, c, x) => `${wd[r]} ${STATE.meta.intervals[ivs[c]]}: ${F.pct(x + q.sl_target)} service level (${(x * 100).toFixed(1)} pts vs target)` });
  $('#qd3l').innerHTML = heatLegend(div, -0.2, 0.2, x => (x >= 0 ? '+' : '') + Math.round(x * 100), 'pts');
}

/* ---------------- Intraday ---------------- */
page('intraday', {
  title: 'Intraday', sub: 'Forecast vs actual, staffing vs requirement, interval by interval', filters: ['date'],
  async render(v, params) {
    const rt = STATE.meta.queues.filter(q => q.realtime); const qid = params.q && queueById(params.q) ? params.q : (rt[0] || STATE.meta.queues[0]).queue_id;
    const q = queueById(qid); const f = STATE.filters; const metric = params.m || 'sl';
    const rows = Cube.rows({ start: f.start, end: f.end, queues: [qid] });
    const dates = [...new Set(rows.map(i => Cube.dateStr[i]))].sort();
    const day = params.d && dates.includes(params.d) ? params.d : dates[dates.length - 1];
    v.innerHTML = `<div class="section-h"><div><span class="eyebrow">${esc(q.code)} · ${q.channel}</span><h1>Intraday: ${esc(q.name)}</h1><p>Each row is a day, each column a half-hour. Click a cell to open that day.</p></div>
      <div class="r"><select id="iq">${STATE.meta.queues.map(x => `<option value="${x.queue_id}" ${x.queue_id === qid ? 'selected' : ''}>${x.code} · ${x.name}</option>`).join('')}</select>
      <div class="seg" id="im">${[['sl', 'Service level'], ['staffing_ratio', 'Staffed vs required'], ['offered', 'Volume'], ['abandon_rate', 'Abandon']].filter(([k]) => q.realtime || k !== 'abandon_rate').map(([k, l]) => `<button data-v="${k}" aria-pressed="${metric === k}">${l}</button>`).join('')}</div></div></div>
      <div class="grid"><section class="card c12"><div class="card-h"><h3>${metric === 'sl' ? 'Service level vs target' : metric === 'staffing_ratio' ? 'Staffed agents as a share of required' : metric === 'offered' ? 'Offered contacts' : 'Abandon rate'}</h3><span class="sub">${dates.length} days × ${q.close_hour - q.open_hour} hours</span><div class="r" id="ileg"></div></div><div class="card-b"><div id="iheat" style="max-height:520px;overflow:auto"></div></div></section>
      <section class="card c6"><div class="card-h"><h3>${F.dateLong(day)}: volume vs forecast</h3></div><div class="card-b"><div id="id1"></div><div class="legend" style="margin-top:6px"><span><i style="background:var(--s1);opacity:.4"></i>Offered</span><span><i class="line" style="background:var(--ink-2)"></i>WFM forecast</span></div></div></section>
      <section class="card c6"><div class="card-h"><h3>Staffing vs requirement</h3><span class="sub">agents on the queue</span></div><div class="card-b"><div id="id2"></div><div class="legend" style="margin-top:6px"><span><i class="line" style="background:var(--s3)"></i>Staffed</span><span><i class="line" style="background:var(--crit)"></i>Required (Erlang C)</span><span><i class="line" style="background:var(--ink-4)"></i>Scheduled heads</span></div></div></section>
      <section class="card c12"><div class="card-h"><h3>Service level by interval</h3><span class="sub">${F.dateLong(day)}</span>${q.realtime ? `<div class="r">${copilotLink(`On ${day} ${q.code} missed service level in some intervals. What should the RTA do intraday?`, qid)}</div>` : ''}</div><div class="card-b"><div id="id3"></div></div></section></div>`;
    $('#iq').onchange = e => go('intraday', { q: e.target.value, m: metric });
    seg($('#im'), m => go('intraday', { q: qid, m, d: day }));
    const ivs = []; for (let i = q.realtime ? q.open_hour * 2 : 0; i < (q.realtime ? q.close_hour * 2 : 48); i++) ivs.push(i);
    const cell = new Map(); for (const i of rows) cell.set(Cube.dateStr[i] + '|' + Cube.d.interval_idx[i], i);
    const val = (d, iv) => { const i = cell.get(d + '|' + iv); if (i == null) return null; const s = {}; metricCols([metric]).forEach(c => s[c] = Cube.d[c][i]);
      if (metric === 'sl') return s.sl_den >= 3 ? s.sl_num / s.sl_den - q.sl_target : null;
      return metricValue(metric, s); };
    const fn = metric === 'sl' ? scaleDiv(0, 0.3) : metric === 'staffing_ratio' ? scaleDiv(1, 0.35) : metric === 'abandon_rate' ? scaleSeq(0, 0.25) : scaleSeq(0, Math.max(...rows.map(i => Cube.d.offered[i])));
    heatmap($('#iheat'), { rows: dates.map(d => `${F.date(d)} ${STATE.meta.dates.find(x => x.date === d).weekday}`), cols: ivs.map(i => STATE.meta.intervals[i]), colEvery: 2, minWidth: 760,
      values: dates.map(d => ivs.map(iv => val(d, iv))), color: fn, title: (r, c, x) => `${dates[r]} ${STATE.meta.intervals[ivs[c]]}: ${metric === 'sl' ? F.pct(x + q.sl_target) : metric === 'offered' ? F.int(x) : F.pct(x)}`,
      onClick: (r) => go('intraday', { q: qid, m: metric, d: dates[r] }) });
    $('#iheat').querySelectorAll('td.k').forEach(td => td.style.width = '96px');
    $('#ileg').innerHTML = metric === 'sl' ? heatLegend(fn, -0.3, 0.3, x => (x >= 0 ? '+' : '') + Math.round(x * 100), 'pts vs target') : metric === 'staffing_ratio' ? heatLegend(fn, 0.65, 1.35, F.pct0, '') : heatLegend(fn, 0, metric === 'abandon_rate' ? 0.25 : 1, metric === 'abandon_rate' ? F.pct0 : (x => ''), '');
    const dv = ivs.map(iv => cell.get(day + '|' + iv)); const pick = c => dv.map(i => i == null ? null : Cube.d[c][i]);
    const labels = ivs.map(i => STATE.meta.intervals[i]);
    comboChart($('#id1'), { x: labels, height: 220, xTickW: 46, series: [{ name: 'Offered', values: pick('offered'), kind: 'bar', color: 'var(--s1)', opacity: .4 }, { name: 'Forecast', values: pick('forecast_volume'), kind: 'line', color: 'var(--ink-2)', width: 1.6 }], yl: { format: F.int } });
    comboChart($('#id2'), { x: labels, height: 220, xTickW: 46, series: [{ name: 'Scheduled', values: pick('scheduled_agents'), kind: 'step', color: 'var(--ink-4)', width: 1.4 }, { name: 'Required', values: pick('required_agents'), kind: 'step', color: 'var(--crit)', width: 1.8, dash: '4 3' }, { name: 'Staffed', values: pick('staffed_agents'), kind: 'step', color: 'var(--s3)', width: 2.2 }], yl: { format: F.int, min: 0 } });
    const slv = dv.map(i => i == null || !Cube.d.sl_den[i] ? null : Cube.d.sl_num[i] / Cube.d.sl_den[i]);
    comboChart($('#id3'), { x: labels, height: 200, xTickW: 46, series: [{ name: 'Service level', values: slv, kind: 'bar', color: 'var(--s1)', colorAt: (i, x) => x < q.sl_target ? 'var(--crit)' : 'var(--s1)' }], yl: { format: F.pct0, min: 0, max: 1 }, targets: [{ value: q.sl_target, label: `Target ${F.pct0(q.sl_target)}` }] });
  },
});

/* ---------------- Agents ---------------- */
page('agents', {
  title: 'Agents', sub: 'Productivity, quality and coaching priorities', filters: ['date', 'client', 'channel', 'queues'],
  async render(v, params) {
    const data = await cached('agents', () => API.get('agents'));
    const f = STATE.filters; const qs = new Set(selectedQueues()); const s = s2dk(f.start), e = s2dk(f.end);
    const ad = data.agent_day.data; const n = data.agent_day.n; const agg = new Map();
    for (let i = 0; i < n; i++) {
      if (ad.date_key[i] < s || ad.date_key[i] > e || !qs.has(ad.queue_id[i])) continue;
      let o = agg.get(ad.agent_id[i]); if (!o) { o = { handled: 0, handle_sec: 0, transferred: 0, fcr_num: 0, fcr_den: 0, csat_resp: 0, csat_top2: 0, qa_audits: 0, qa_sum: 0, qa_fatal: 0, days: 0, queue_id: ad.queue_id[i] }; agg.set(ad.agent_id[i], o); }
      for (const c of ['handled', 'handle_sec', 'transferred', 'fcr_num', 'fcr_den', 'csat_resp', 'csat_top2', 'qa_audits', 'qa_sum', 'qa_fatal']) o[c] += ad[c][i] || 0; o.days++;
    }
    const dim = Object.fromEntries(data.agents.map(a => [a.agent_id, a]));
    let rows = [...agg.entries()].filter(([id]) => dim[id]).map(([id, o]) => { const a = dim[id]; const q = queueById(o.queue_id);
      return { id, name: a.full_name, tl: a.team_leader_name, site: a.site, band: a.tenure_band, queue: q.code, queue_id: q.queue_id, days: o.days, handled: o.handled, aht: o.handled ? o.handle_sec / o.handled : null, ahtT: q.aht_target_sec,
        fcr: o.fcr_den ? o.fcr_num / o.fcr_den : null, csat: o.csat_resp >= 5 ? o.csat_top2 / o.csat_resp : null, qa: o.qa_audits ? o.qa_sum / o.qa_audits : null, audits: o.qa_audits, fatal: o.qa_fatal, transfer: o.handled ? o.transferred / o.handled : null }; });
    const byQ = {}; rows.forEach(r => (byQ[r.queue_id] = byQ[r.queue_id] || []).push(r));
    Object.values(byQ).forEach(list => { list.filter(r => r.handled >= 50).sort((a, b) => a.aht - b.aht).forEach((r, i, arr) => { r.rank = i + 1; r.of = arr.length; }); });
    rows.forEach(r => { r.flags = []; if (r.qa != null && r.qa < 80) r.flags.push('Low QA'); if (r.fatal >= 2) r.flags.push('Repeated fatal errors'); if (r.aht > r.ahtT * 1.15) r.flags.push('High AHT'); if (r.fcr != null && r.fcr < 0.82) r.flags.push('Repeat contacts'); });
    const band = params.band || 'all'; const shown = rows.filter(r => band === 'all' || r.band === band);
    const bands = ['0-3m', '3-6m', '6-12m', '12m+'];
    v.innerHTML = `<div class="section-h"><div><span class="eyebrow">${esc(scopeLabel())}</span><h1>Agent performance</h1><p>Ranks use RANK() within each queue on AHT (agents with 50+ contacts). Flags suggest coaching priorities; they are prompts for a conversation, not verdicts.</p></div>
      <div class="r"><div class="seg" id="ab">${[['all', 'All tenure'], ...bands.map(b => [b, b])].map(([k, l]) => `<button data-v="${k}" aria-pressed="${band === k}">${l}</button>`).join('')}</div></div></div>
      <div class="grid">
        <section class="card c4"><div class="card-h"><h3>Handle time by tenure</h3><span class="sub">relative to queue target</span></div><div class="card-b" id="ag1"></div></section>
        <section class="card c8"><div class="card-h"><h3>Quality vs speed</h3><span class="sub">each dot an agent; size = contacts handled</span><div class="r legend">${bands.map((b, i) => `<span><i style="background:${sc(i)}"></i>${b}</span>`).join('')}</div></div><div class="card-b"><div id="ag2"></div></div></section>
        <section class="card c12"><div class="card-h"><h3>Leaderboard</h3><span class="sub">${shown.length} agents · click a row for detail</span><div class="r"><input type="search" id="aq" placeholder="Search agent or team leader" style="width:220px"></div></div><div class="card-b flush" id="ag3"></div></section>
      </div>`;
    seg($('#ab'), b => go('agents', { band: b }));
    const bandAgg = bands.map(b => { const rs = rows.filter(r => r.band === b && r.handled); const h = sum(rs.map(r => r.handled)); return { label: b, value: h ? sum(rs.map(r => r.aht / r.ahtT * r.handled)) / h : null, n: rs.length }; });
    hbars($('#ag1'), bandAgg.map((x, i) => ({ label: `${x.label} (${x.n})`, value: x.value, color: sc(i) })), { format: x => F.pct0(x), max: 1.4, target: 1, labelW: 90 });
    $('#ag1').insertAdjacentHTML('beforeend', '<p class="muted" style="font-size:12px;margin-top:12px">100% = on the queue\'s AHT target. New joiners typically run 15–25% over target in their first three months.</p>');
    const pts = rows.filter(r => r.qa != null && r.aht).map(r => ({ x: r.aht / r.ahtT, y: r.qa, r: 3 + Math.sqrt(r.handled) / 6, color: sc(bands.indexOf(r.band)), id: r.id, tip: `<b>${esc(r.name)}</b><div><span>Queue</span><span>${esc(r.queue)}</span></div><div><span>AHT vs target</span><span>${F.pct0(r.aht / r.ahtT)}</span></div><div><span>QA</span><span>${F.num(r.qa)}</span></div><div><span>Handled</span><span>${F.int(r.handled)}</span></div>` }));
    scatter($('#ag2'), { points: pts, height: 300, xFormat: F.pct0, yFormat: x => x, xLabel: 'AHT vs queue target', yLabel: 'QA score', refX: 1, refY: 85, onClick: p => agentDrawer(rows.find(r => r.id === p.id), data) });
    const draw = qtxt => sortableTable($('#ag3'), [
      { key: 'name', label: 'Agent', render: r => `<div class="qname"><b>${esc(r.name)}</b><small>${esc(r.tl || '')} · ${esc(r.site || '')}</small></div>` },
      { key: 'queue', label: 'Queue' }, { key: 'band', label: 'Tenure' },
      { key: 'handled', label: 'Handled', num: true, render: r => F.int(r.handled) },
      { key: 'aht', label: 'AHT', num: true, render: r => statusCell('aht', r.aht, r.ahtT) },
      { key: 'rank', label: 'Rank in queue', num: true, render: r => r.rank ? `<span class="mono">${r.rank}<span class="muted">/${r.of}</span></span>` : '—' },
      { key: 'fcr', label: 'FCR', num: true, render: r => F.pct(r.fcr) },
      { key: 'csat', label: 'CSAT', num: true, render: r => F.pct(r.csat) },
      { key: 'qa', label: 'QA', num: true, render: r => r.qa == null ? '—' : `<span class="${r.qa < 80 ? 'st-bad' : ''}">${F.num(r.qa)}</span>` },
      { key: 'transfer', label: 'Transfers', num: true, render: r => F.pct(r.transfer) },
      { key: 'flags', label: 'Coaching flags', sort: false, render: r => r.flags.map(x => `<span class="pill ${x === 'Repeated fatal errors' ? 'crit' : 'warn'}">${x}</span>`).join(' ') || '<span class="muted">—</span>' },
    ], shown.filter(r => !qtxt || (r.name + ' ' + r.tl).toLowerCase().includes(qtxt)), { sortKey: 'handled', onRow: r => agentDrawer(r, data) });
    draw(''); $('#aq').oninput = e => draw(e.target.value.toLowerCase());
    $('#ag3').classList.add('scroll-y');
  },
});
function agentDrawer(r, data) {
  const ad = data.agent_day.data; const days = [];
  for (let i = 0; i < data.agent_day.n; i++) if (ad.agent_id[i] === r.id) days.push({ d: dk2s(ad.date_key[i]), h: ad.handled[i], aht: ad.handle_sec[i] / ad.handled[i] });
  days.sort((a, b) => a.d < b.d ? -1 : 1);
  const { el } = drawer(r.name, `<dl class="kv"><dt>Queue</dt><dd>${esc(r.queue)}</dd><dt>Team leader</dt><dd>${esc(r.tl || '—')}</dd><dt>Site</dt><dd>${esc(r.site || '—')}</dd><dt>Tenure band</dt><dd>${esc(r.band)}</dd><dt>Days worked</dt><dd>${r.days}</dd><dt>Handled</dt><dd>${F.int(r.handled)}</dd><dt>AHT</dt><dd>${F.sec(r.aht)} (target ${F.sec(r.ahtT)})</dd><dt>FCR / CSAT</dt><dd>${F.pct(r.fcr)} / ${F.pct(r.csat)}</dd><dt>QA</dt><dd>${r.qa == null ? '—' : F.num(r.qa)} from ${r.audits} audits${r.fatal ? `, <b class="st-bad">${r.fatal} fatal</b>` : ''}</dd></dl>
    <div><div class="eyebrow" style="margin-bottom:6px">Daily handle time</div><div id="adc"></div></div>
    ${r.flags.length ? `<div class="insight warn"><div><b>Coaching prompts</b><p>${r.flags.join(', ')}. See QA-01 for coaching rules; schedule sessions outside the morning peak.</p><div class="acts">${copilotLink(`How should a team leader coach an agent with ${r.flags.join(' and ').toLowerCase()}?`)}</div></div></div>` : ''}`, { sub: `${r.queue} · ${r.band}` });
  comboChart(el.querySelector('#adc'), { x: days.map(d => d.d), xFormat: F.date, height: 200, series: [{ name: 'Handled', values: days.map(d => d.h), kind: 'bar', color: 'var(--s1)', opacity: .35 }, { name: 'AHT', values: days.map(d => d.aht), kind: 'line', axis: 'r', color: 'var(--s2)' }], yr: { format: F.secs }, targets: [{ value: r.ahtT, axis: 'r' }] });
}
