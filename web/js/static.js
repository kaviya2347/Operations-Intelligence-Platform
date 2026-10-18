/* Offline snapshot mode: answers the same API paths from window.OIP_SNAPSHOT, applying the same
   row-level security as the server, and runs the copilot's retrieval (BM25 + MMR) in the browser.
   On a hosted page that grants the `sample` capability, Claude writes the answer from the passages. */
'use strict';

const STATIC_LLM = { sample: null };
(function initSample() {
  if (window.claude?.use) window.claude.use('sample').then(s => { STATIC_LLM.sample = s || null; }).catch(() => { });
})();

const StaticAPI = {
  _u() { return this.snap().users.find(u => u.id === API.user) || this.snap().users[0]; },
  snap() { return API.snap; },
  allowed() { const u = this._u(); return u.queues ? new Set(u.queues) : new Set(this.snap().meta[u.id].queues.map(q => q.queue_id)); },
  _filterColumnar(c, keep) {
    const idx = []; for (let i = 0; i < c.n; i++) if (keep(i)) idx.push(i);
    const data = {}; for (const k of c.columns) { const a = c.data[k]; data[k] = idx.map(i => a[i]); }
    return { n: idx.length, columns: c.columns, data };
  },
  _cache: {},
  async get(path) {
    const S = this.snap(); const [p, qs] = path.split('?'); const q = Object.fromEntries(new URLSearchParams(qs || ''));
    const u = this._u(); const aq = this.allowed(); const role = u.role;
    const deny = msg => { const e = new Error(msg); e.status = 403; throw e; };
    switch (p) {
      case 'health': return { ok: true, static: true };
      case 'users': return S.users;
      case 'meta': return S.meta[u.id];
      case 'cube': { const k = 'cube|' + u.id; if (!this._cache[k]) this._cache[k] = this._filterColumnar(S.cube, i => aq.has(S.cube.data.queue_id[i])); return this._cache[k]; }
      case 'agents': {
        const k = 'agents|' + u.id; if (this._cache[k]) return this._cache[k];
        const ad = this._filterColumnar(S.agents.agent_day, i => aq.has(S.agents.agent_day.data.queue_id[i]));
        const dim = S.agents.agents.filter(a => aq.has(a.queue_id)).map(a => u.can_see_agent_names ? a : { ...a, full_name: 'Agent ' + a.agent_id, team_leader_name: 'Team ' + (a.team_leader_id || '') });
        return (this._cache[k] = { agent_day: ad, agents: dim });
      }
      case 'rca': { const id = q.queue || 'Q01'; if (!aq.has(id)) deny('You do not have access to this queue.'); return S.rca[id] || { error: 'No root-cause analysis for this queue.' }; }
      case 'forecast': {
        const f = S.forecast; const codes = new Set(S.meta[u.id].queues.filter(x => aq.has(x.queue_id)).map(x => x.code)); const inQ = r => aq.has(r.queue_id);
        return { ...f, results: f.results.filter(inQ), predictions: f.predictions.filter(inQ), forecast: f.forecast.filter(inQ),
          staffing_plan: { intervals: f.staffing_plan.intervals.filter(inQ), summary: f.staffing_plan.summary.filter(inQ), worst_gaps: f.staffing_plan.worst_gaps.filter(inQ) },
          importance: Object.fromEntries(Object.entries(f.importance).filter(([k]) => codes.has(k))) };
      }
      case 'alerts': return { method: S.alerts.method, incidents: S.alerts.incidents.filter(i => aq.has(i.queue_id)), alerts: S.alerts.alerts.filter(i => aq.has(i.queue_id)) };
      case 'quality': if (!['Admin', 'Analyst'].includes(role)) deny('Data quality is visible to Admin and Analyst roles.'); return S.quality;
      case 'eda': return S.eda;
      case 'catalog': { const c = S.catalog; return ['Admin', 'Analyst'].includes(role) ? c : { ...c, tables: c.tables.filter(t => !/^(stg_|gov_)/.test(t.name)) }; }
      case 'copilot/docs': return S.copilot.docs;
      case 'copilot/chunks': return S.copilot.chunks;
      case 'copilot/eval': return S.copilot.eval;
      case 'sql/saved': return S.sql.saved;
      case 'settings/llm': return S.meta[u.id].llm;
    }
    throw new Error(`Not available offline: ${p}`);
  },
  async post(path, body = {}, opts = {}) {
    const S = this.snap(); const u = this._u();
    if (path === 'copilot/ask') return Copilot.ask(body.question, { k: body.k || 5, docTypes: body.doc_types, live: body.queue_id && this.allowed().has(body.queue_id) ? liveContext(body.queue_id) : null, onText: opts.onText });
    const m = path.match(/^alerts\/(.+)\/recommend$/);
    if (m) {
      const inc = S.alerts.incidents.find(i => i.incident_id === decodeURIComponent(m[1]) && this.allowed().has(i.queue_id)); if (!inc) throw new Error('Incident not found.');
      const kpi = inc.kpi_label || inc.kpi;
      const q = `${inc.queue_code} ${kpi} problem from ${inc.start} to ${inc.end}. Likely driver: ${inc.likely_driver || 'unknown'}. What should operations and workforce management do, and which past RCA or SOP applies?`;
      const live = `Queue ${inc.queue_code}; ${kpi}; period ${inc.start} to ${inc.end}; severity ${inc.severity}; peak value ${inc.peak_value}; baseline or target ${inc.baseline}; likely driver ${inc.likely_driver}.\n${inc.note || ''}`;
      return Copilot.ask(q, { k: 5, live, onText: opts.onText });
    }
    if (path === 'sql') {
      if (!u.can_sql) throw new Error('The SQL lab is available to Admin and Analyst roles.');
      const norm = s => s.replace(/\s+/g, ' ').trim().replace(/;$/, '');
      const hit = S.sql.saved.find(s => norm(s.sql) === norm(body.sql || ''));
      if (hit && S.sql.results[hit.id]) return { ...S.sql.results[hit.id], cached: true };
      return { error: 'Custom queries need the local server (python -m oip serve). Saved queries return the results captured when this snapshot was built; use Reset to restore one.' };
    }
    throw new Error(`Not available offline: ${path}`);
  },
};

/* Live KPI context for a queue: same text the server builds (last seven days + RCA findings). */
function liveContext(qid) {
  const q = queueById(qid); if (!q) return null;
  const last = STATE.meta.period.end; const rows = Cube.rows({ start: addDays(last, -6), end: last, queues: [qid] });
  const s = Cube.sums(rows, ['sl_num', 'sl_den', 'handle_sec', 'handled', 'staffed_agents', 'required_agents']);
  if (!s.sl_den) return `${q.code}: no recent data.`;
  const lines = [`${q.code} (${q.name}) last 7 days: service level ${(s.sl_num / s.sl_den * 100).toFixed(1)}% vs target ${Math.round(q.sl_target * 100)}%; AHT ${Math.round(s.handle_sec / s.handled)}s vs target ${q.aht_target_sec}s; staffed/required ${(s.staffed_agents / s.required_agents).toFixed(2)}.`];
  const r = API.snap?.rca?.[qid]; if (r?.summary) lines.push(...r.summary.slice(1, 4));
  return lines.join('\n');
}

/* ---------- in-browser retrieval and answer ---------- */
const Copilot = {
  idx: null,
  tok(t) { const st = this.stop; return (t.toLowerCase().match(/[a-z0-9]+(?:-[a-z0-9]+)*/g) || []).filter(w => !st.has(w) && w.length > 1); },
  expand(t) { const A = this.abbr; const extra = (t.toLowerCase().match(/[a-z]+/g) || []).filter(w => A[w]).map(w => A[w]); return extra.length ? t + ' ' + extra.join(' ') : t; },
  build() {
    const C = API.snap.copilot; this.abbr = C.abbreviations; this.stop = new Set(C.stopwords);
    const toks = C.chunks.map(c => this.tok(this.expand(c.text))); const df = new Map();
    toks.forEach(t => new Set(t).forEach(w => df.set(w, (df.get(w) || 0) + 1)));
    const n = toks.length; const idf = new Map([...df].map(([w, f]) => [w, Math.log(1 + (n - f + 0.5) / (f + 0.5))]));
    const tf = toks.map(t => { const m = new Map(); t.forEach(w => m.set(w, (m.get(w) || 0) + 1)); return m; });
    const len = toks.map(t => t.length); const avg = len.reduce((a, b) => a + b, 0) / n;
    this.idx = { chunks: C.chunks, vectors: C.vectors, idf, tf, len, avg };
  },
  bm25(q) {
    const { tf, idf, len, avg } = this.idx; const qt = this.tok(this.expand(q)); const k1 = 1.5, b = 0.75;
    return tf.map((m, i) => qt.reduce((s, t) => { const f = m.get(t); return f ? s + (idf.get(t) || 0) * f * (k1 + 1) / (f + k1 * (1 - b + b * len[i] / avg)) : s; }, 0));
  },
  retrieve(q, k = 5, docTypes = null) {
    if (!this.idx) this.build();
    const { chunks, vectors } = this.idx; const sc = this.bm25(q);
    let ids = chunks.map((c, i) => i).filter(i => !docTypes || docTypes.includes(chunks[i].doc_type));
    if (/defin|measur|calculat|formula|denominator|numerator|what is the .* rate/i.test(q)) ids.forEach(i => { if (chunks[i].doc_id === 'MET-01') sc[i] += 0.5; });
    const cand = ids.sort((a, b) => sc[b] - sc[a]).slice(0, 20).filter(i => sc[i] > 0);
    const lo = Math.min(...cand.map(i => sc[i])), hi = Math.max(...cand.map(i => sc[i]));
    const rel = i => (sc[i] - lo) / ((hi - lo) || 1); const dot = (a, b) => { let s = 0; for (let j = 0; j < a.length; j++) s += a[j] * b[j]; return s; };
    const chosen = [];
    while (chosen.length < Math.min(k, cand.length)) {
      let best = null, bs = -1e9;
      for (const i of cand) { if (chosen.includes(i)) continue; const div = chosen.length ? Math.max(...chosen.map(c => dot(vectors[i], vectors[c]))) : 0; const s = 0.7 * rel(i) - 0.3 * div; if (s > bs) { bs = s; best = i; } }
      chosen.push(best);
    }
    return chosen.map((i, r) => ({ rank: r + 1, chunk_id: chunks[i].chunk_id, doc_id: chunks[i].doc_id, title: chunks[i].title, doc_type: chunks[i].doc_type, section: chunks[i].section, text: chunks[i].text, score: +(1 / (60 + r)).toFixed(5), dense: null, bm25: +sc[i].toFixed(3) }));
  },
  prompt(q, passages, live) {
    const src = passages.map(p => `[${p.rank}] ${p.doc_id} · ${p.title} > ${p.section}\n${p.text}`).join('\n\n');
    return `${API.snap.copilot.system}\n\nSOURCES:\n${src}${live ? `\n\nLIVE DATA [L] (from the platform, current filters):\n${live}` : ''}\n\nQUESTION: ${q}`;
  },
  extractive(q, passages, live) {
    const C = API.snap.copilot; const qt = new Set(this.tok(this.expand(q))); const wants = new RegExp(C.action_q, 'i').test(q);
    const imp = new RegExp(`^(\\d\\.\\s*)?(${C.imperatives.join('|')})`);
    const split = t => t.replace(/^.*?>\s.*?\.\s/, '').split(/(?<=[.!?])\s+(?=[A-Z0-9])|\s(?=\d\.\s)|\s(?=-\s)|\s\|\s/).map(s => s.trim().replace(/^[-|\s]+|[-|\s]+$/g, '')).filter(s => s.split(/\s+/).length >= 5);
    const F1 = [], A1 = [];
    passages.forEach(p => { const isAct = C.action_sections.some(a => p.section.toLowerCase().includes(a));
      split(p.text).forEach(s => { const st = new Set(this.tok(this.expand(s))); if (!st.size) return; let ov = 0; st.forEach(w => qt.has(w) && ov++);
        const score = ov / (Math.sqrt(qt.size) + 1e-9) + 0.35 / p.rank; const im = imp.test(s);
        if (wants && (isAct || im)) A1.push([score + (im ? 0.3 : 0), p.rank, s.replace(/^\d\.\s*/, '')]); else F1.push([score, p.rank, s]); }); });
    F1.sort((a, b) => b[0] - a[0]); A1.sort((a, b) => b[0] - a[0]);
    const uniq = (items, n) => { const out = [], seen = new Set(); for (const [, r, s] of items) { if (seen.has(s.slice(0, 50))) continue; seen.add(s.slice(0, 50)); out.push([r, s.replace(/\.$/, '') + '.']); if (out.length >= n) break; } return out; };
    const lines = []; if (live) lines.push(`Live data [L]: ${live.split('\n')[0]}`);
    const top = uniq(F1, wants ? 2 : 4); if (top.length) { lines.push(top.slice(0, 2).map(([r, s]) => `${s} [${r}]`).join(' ')); top.slice(2).forEach(([r, s]) => lines.push(`- ${s} [${r}]`)); }
    const acts = uniq(A1, 5); if (acts.length) { lines.push('Recommended actions from the knowledge base:'); acts.forEach(([r, s], i) => lines.push(`${i + 1}. ${s} [${r}]`)); }
    if (!top.length && !acts.length) lines.push('The knowledge base does not cover this question.');
    lines.push('(Extractive mode: quoted from the sources. Open the hosted page in Claude, or run the local server with a model, for a written recommendation.)');
    return lines.join('\n');
  },
  async ask(q, { k = 5, docTypes = null, live = null, onText } = {}) {
    const t0 = performance.now(); const passages = this.retrieve(q, k, docTypes && docTypes.length ? docTypes : null);
    let text = null, provider = 'extractive', error = null;
    if (STATIC_LLM.sample && passages.length) {
      try { const r = await STATIC_LLM.sample(this.prompt(q, passages, live), { onText: onText ? ({ text }) => onText(text) : undefined }); text = r.text; provider = 'claude'; }
      catch (e) { if (['not_granted', 'sampling_disabled', 'not_declared', 'capability_disabled', 'capability_removed'].includes(e?.code)) STATIC_LLM.sample = null; if (e?.code !== 'cancelled') error = `Claude unavailable (${e?.code || 'error'}); showing the extractive answer`; }
    }
    if (!text) text = this.extractive(q, passages, live);
    const cited = new Set([...text.matchAll(/\[(\d+)\]/g)].map(m => +m[1]));
    return { question: q, answer: text, passages, provider, model: provider === 'claude' ? 'via claude.ai' : null, error,
      citations: passages.map(p => ({ n: p.rank, doc_id: p.doc_id, title: p.title, section: p.section, score: p.score, cited: cited.has(p.rank) })), latency_ms: Math.round(performance.now() - t0) };
  },
};
