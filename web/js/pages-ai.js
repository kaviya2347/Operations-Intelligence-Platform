/* AI pages: Operations copilot (RAG with citations), knowledge base, retrieval evaluation. */
'use strict';

const CHAT = { msgs: [], lastAuto: null, docTypes: [], queue: '' };
const DOC_TYPES = ['SOP', 'RCA', 'Playbook', 'Quality', 'Reference', 'Contract', 'Governance'];
const SUGGEST = [
  'What should the RTA do when service level is more than 10 points below target for two intervals?',
  'What did the Billing RCA recommend to fix the morning peak?',
  'How is service level calculated and which abandons are excluded?',
  'How should we prepare for the Kestrel sale weekend?',
  'How do we correct handle time when an agent session was not closed?',
  'Who can see customer phone numbers, and how are they masked?',
];
const PROVIDER_LABEL = { anthropic: 'Claude', ollama: 'Local model', extractive: 'Extractive', claude: 'Claude' };

function citeText(t, r) {
  const titles = Object.fromEntries((r.citations || []).map(c => [c.n, `${c.doc_id} · ${c.title} § ${c.section}`]));
  return esc(t).replace(/\[(\d+)\]/g, (m, n) => titles[n] ? `<span class="cite" data-n="${n}" role="button" tabindex="0" title="${esc(titles[n])}">${n}</span>` : m)
    .replace(/\[L\]/g, '<span class="cite live" title="Live queue data from the warehouse">L</span>');
}
function answerHTML(r) {
  const cited = (r.citations || []).filter(c => c.cited);
  return `<div class="msg bot"><div class="bubble">${citeText(r.answer || '', r)}</div>
    <div class="meta"><span class="pill ${r.provider === 'extractive' ? '' : 'info'}">${esc(PROVIDER_LABEL[r.provider] || r.provider)}${r.model ? ' · ' + esc(r.model) : ''}</span>
    ${r.latency_ms != null ? `<span>${F.int(r.latency_ms)} ms</span>` : ''}
    ${cited.length ? `<span>· cites</span>${cited.map(c => `<button class="chip" data-n="${c.n}" style="height:22px;font-size:11.5px">[${c.n}] ${esc(c.doc_id)}</button>`).join('')}` : ''}
    ${r.error ? `<span class="st-bad">${esc(r.error)}</span>` : ''}</div></div>`;
}
function passageHTML(p, cited) {
  const max = 0.035;
  return `<div class="passage" data-rank="${p.rank}"><div class="h"><span class="cite" style="display:inline-grid;place-items:center;min-width:20px;height:18px;border-radius:5px;background:color-mix(in srgb,var(--s1) 14%,transparent);color:var(--s1);font:600 10.5px var(--f-mono)">${p.rank}</span>
    <b style="font-size:12.5px">${esc(p.doc_id)}</b><span class="tag">${esc(p.doc_type)}</span>${cited ? '<span class="pill good">cited</span>' : ''}</div>
    <small class="ink2" style="font-size:12px">${esc(p.title)} § ${esc(p.section)}</small>
    <p>${esc(p.text.replace(/^.*?>\s.*?\.\s/, ''))}</p>
    <div class="scorebar"><span title="Reciprocal-rank fusion score">fused ${p.score.toFixed(4)}</span><span title="Cosine similarity of embeddings">dense ${p.dense != null ? p.dense.toFixed(3) : '—'}</span><span title="BM25 keyword score">bm25 ${p.bm25 != null ? p.bm25.toFixed(2) : '—'}</span></div>
    <span style="height:4px;border-radius:3px;background:var(--surface-3);overflow:hidden"><i style="display:block;height:100%;width:${clamp(p.score / max * 100, 4, 100)}%;background:var(--s1)"></i></span></div>`;
}
function bindCites(host, r, onCite) {
  const open = n => {
    const p = (r.passages || []).find(x => x.rank === +n); if (!p) return;
    if (onCite) return onCite(p);
    drawer(`[${n}] ${p.doc_id}`, `<p class="muted" style="font-size:12.5px">${esc(p.title)} § ${esc(p.section)}</p><div class="passage" style="border:0;padding:0"><p style="-webkit-line-clamp:unset;font-size:13.5px;color:var(--ink)">${esc(p.text)}</p></div>`, { sub: p.doc_type });
  };
  $$('.cite[data-n], .chip[data-n]', host).forEach(c => { c.onclick = () => open(c.dataset.n); c.onkeydown = e => { if (e.key === 'Enter') open(c.dataset.n); }; });
}

page('copilot', {
  title: 'Copilot', sub: 'Answers from SOPs, past RCAs and live queue data, with citations', filters: [],
  async render(v, params, alive) {
    const tab = params.tab || 'ask';
    v.innerHTML = `<div class="section-h"><div><span class="eyebrow">Retrieval-augmented generation</span><h1>Operations copilot</h1><p>Questions are matched against the knowledge base with keyword (BM25) and semantic search, fused by reciprocal rank and de-duplicated. The model may only answer from the retrieved passages and live queue data, and must cite them.</p></div>
      <div class="r"><div class="seg" id="ct"><button data-v="ask" aria-pressed="${tab === 'ask'}">Ask</button><button data-v="kb" aria-pressed="${tab === 'kb'}">Knowledge base</button><button data-v="eval" aria-pressed="${tab === 'eval'}">Evaluation</button></div></div></div><div id="cb"></div>`;
    seg($('#ct'), t => go('copilot', { tab: t }));
    const host = $('#cb');
    if (tab === 'kb') return renderKB(host, alive);
    if (tab === 'eval') return renderEval(host, alive);
    renderChat(host, params);
  },
});

function renderChat(host, params) {
  if (params.queue != null && params.queue !== '' && queueById(params.queue)) CHAT.queue = params.queue;
  const llm = STATE.meta.llm || {};
  const provNote = API.mode === 'static' ? (STATIC_LLM.sample ? 'Keyword retrieval in the browser; Claude writes the answer from the passages' : 'Offline snapshot: keyword retrieval in the browser, answers quote the passages') : llm.provider === 'extractive' ? 'No model configured: answers quote the passages. Add ANTHROPIC_API_KEY or run Ollama to get written answers.' : `Answers written by ${PROVIDER_LABEL[llm.provider] || llm.provider} (${llm.model})`;
  host.innerHTML = `<div class="grid">
    <section class="card c8 chat"><div class="card-h"><h3>Ask</h3><span class="sub">${esc(provNote)}</span><div class="r"><select id="cq" aria-label="Live data context"><option value="">No live queue data</option>${STATE.meta.queues.map(q => `<option value="${q.queue_id}" ${CHAT.queue === q.queue_id ? 'selected' : ''}>Ground in ${esc(q.code)} live data</option>`).join('')}</select><button class="btn btn-ghost btn-sm" id="cclr" title="Clear conversation">Clear</button></div></div>
      <div style="display:flex;gap:6px;flex-wrap:wrap;padding:10px 16px 0" id="cdt"><span class="muted" style="font-size:12px;align-self:center">Search in</span><button class="chip" data-t="all" aria-pressed="${!CHAT.docTypes.length}">All documents</button>${DOC_TYPES.map(t => `<button class="chip" data-t="${t}" aria-pressed="${CHAT.docTypes.includes(t)}">${t}</button>`).join('')}</div>
      <div class="msgs" id="msgs" aria-live="polite"></div>
      <div class="suggest" id="sug">${SUGGEST.map(s => `<button class="chip" data-s="${esc(s)}">${esc(s.length > 64 ? s.slice(0, 62) + '…' : s)}</button>`).join('')}</div>
      <form class="composer" id="cf"><textarea id="ci" rows="2" placeholder="Ask about a queue, a metric, a procedure or a past incident…" aria-label="Question"></textarea><button class="btn btn-primary" id="cs" type="submit">${ICON.spark}Ask</button></form></section>
    <section class="card c4"><div class="card-h"><h3>Sources</h3><span class="sub" id="psub">retrieved for the latest answer</span></div><div class="card-b" id="pas" style="display:flex;flex-direction:column;gap:10px;max-height:72vh;overflow:auto"></div></section></div>`;
  const draw = () => {
    const m = $('#msgs');
    m.innerHTML = CHAT.msgs.length ? CHAT.msgs.map(x => x.role === 'user' ? `<div class="msg user">${esc(x.text)}</div>` : x.pending ? `<div class="msg bot"><div class="bubble muted">Retrieving passages and writing the answer…</div></div>` : x.err ? `<div class="msg bot"><div class="bubble st-bad">${esc(x.err)}</div></div>` : answerHTML(x.r)).join('')
      : `<div class="empty" style="padding:40px 10px"><b style="color:var(--ink)">Ask the copilot</b><p style="margin-top:6px">It answers from ${'15'} operating documents (SOPs, RCAs, playbooks, metric definitions) and, if you pick a queue, from that queue's last seven days.</p></div>`;
    m.scrollTop = m.scrollHeight;
    const last = [...CHAT.msgs].reverse().find(x => x.r);
    $$('.msg.bot', m).forEach((el, i) => { const bots = CHAT.msgs.filter(x => x.role === 'bot' && !x.pending && !x.err); const r = bots[i]?.r; if (r) bindCites(el, r, p => { showPassages(r, p.rank); }); });
    if (last) showPassages(last.r); else $('#pas').innerHTML = '<p class="muted" style="font-size:12.5px">Passages appear here with their fused, dense and keyword scores, so every claim can be checked.</p>';
    $('#sug').hidden = CHAT.msgs.length > 0;
  };
  const showPassages = (r, hl) => {
    const cited = new Set((r.citations || []).filter(c => c.cited).map(c => c.n));
    $('#pas').innerHTML = (r.passages || []).map(p => passageHTML(p, cited.has(p.rank))).join('') || '<p class="muted">No passages.</p>';
    $('#psub').textContent = `${(r.passages || []).length} passages · ${cited.size} cited`;
    if (hl) { const el = $(`#pas .passage[data-rank="${hl}"]`); if (el) { el.classList.add('hl'); el.scrollIntoView({ block: 'nearest', behavior: 'smooth' }); } }
  };
  const ask = async q => {
    q = q.trim(); if (q.length < 3) return;
    CHAT.msgs.push({ role: 'user', text: q }, { role: 'bot', pending: true }); draw();
    $('#cs').disabled = true;
    try {
      const onText = t => { const b = $$('#msgs .msg.bot .bubble').at(-1); if (b) { b.classList.remove('muted'); b.textContent = t; } };
      const r = await API.post('copilot/ask', { question: q, k: 5, doc_types: CHAT.docTypes.length ? CHAT.docTypes : null, queue_id: CHAT.queue || null }, { onText });
      CHAT.msgs[CHAT.msgs.length - 1] = { role: 'bot', r };
    } catch (e) { CHAT.msgs[CHAT.msgs.length - 1] = { role: 'bot', err: e.message }; }
    if ($('#msgs')) { draw(); $('#cs').disabled = false; }
  };
  $('#cf').onsubmit = e => { e.preventDefault(); const q = $('#ci').value; $('#ci').value = ''; ask(q); };
  $('#ci').onkeydown = e => { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); $('#cf').requestSubmit(); } };
  $('#cq').onchange = e => CHAT.queue = e.target.value;
  $('#cclr').onclick = () => { CHAT.msgs = []; draw(); };
  $$('#sug [data-s]').forEach(b => b.onclick = () => ask(b.dataset.s));
  $$('#cdt [data-t]').forEach(b => b.onclick = () => {
    const t = b.dataset.t; const set = new Set(CHAT.docTypes);
    if (t === 'all') set.clear(); else set.has(t) ? set.delete(t) : set.add(t);
    CHAT.docTypes = set.size === DOC_TYPES.length ? [] : [...set];
    $$('#cdt [data-t]').forEach(x => x.setAttribute('aria-pressed', String(x.dataset.t === 'all' ? !CHAT.docTypes.length : CHAT.docTypes.includes(x.dataset.t))));
  });
  draw();
  if (params.q && CHAT.lastAuto !== params.q) { CHAT.lastAuto = params.q; ask(params.q); }
  else setTimeout(() => $('#ci')?.focus(), 30);
}

async function renderKB(host, alive) {
  loading(host, 300);
  const [d, chunks] = await Promise.all([cached('kbdocs', () => API.get('copilot/docs')), cached('kbchunks', () => API.get('copilot/chunks'))]);
  if (!alive()) return;
  const ix = d.index; const byType = {}; d.docs.forEach(x => byType[x.doc_type] = (byType[x.doc_type] || 0) + 1);
  host.innerHTML = `<section class="kpis" style="margin-bottom:14px">
      <div class="kpi"><span class="l">Documents</span><span class="v">${d.docs.length}</span><span class="meta">${Object.entries(byType).map(([k, n]) => `${n} ${k}`).join(' · ')}</span></div>
      <div class="kpi"><span class="l">Chunks</span><span class="v">${F.int(ix.chunks)}</span><span class="meta">≈${ix.chunk_words} words, split on headings</span></div>
      <div class="kpi"><span class="l">Embeddings</span><span class="v" style="font-size:17px;padding-top:5px">${esc(ix.embedder)}</span><span class="meta">${ix.dims} dimensions</span></div>
      <div class="kpi"><span class="l">Retrieval</span><span class="v" style="font-size:17px;padding-top:5px">Hybrid</span><span class="meta">BM25 + dense, RRF k=60, MMR λ=0.7</span></div></section>
    <div class="grid"><section class="card c7"><div class="card-h"><h3>Documents</h3><span class="sub">click to read the chunks the model sees</span></div><div class="card-b flush" id="kd"></div></section>
    <section class="card c5"><div class="card-h"><h3>How a document becomes searchable</h3></div><div class="card-b"><div class="narr">
      <p>Markdown with front matter (id, type, owner, effective date) is the source of truth; each file is reviewed by its owner before it enters the index.</p>
      <p>Documents are split on headings, then into chunks of about ${ix.chunk_words} words. Every chunk starts with a header line "Title &gt; Section" so it still makes sense on its own.</p>
      <p>Tables are rewritten as sentences ("For Meridian Cards, the service level target is 80% in 20 seconds") because a retrieved table row loses its column names.</p>
      <p>Abbreviations such as AHT, SL and RTA are expanded at index and query time, so either form finds the passage.</p>
      <p>Each chunk keeps its document id and section, which is what the [n] citations point to.</p></div></div></section></div>`;
  sortableTable($('#kd'), [
    { key: 'doc_id', label: 'Document', render: x => `<b class="mono" style="font-size:12px">${esc(x.doc_id)}</b><div class="ink2" style="font-size:12.5px;white-space:normal">${esc(x.title)}</div>`, wrap: true },
    { key: 'doc_type', label: 'Type', render: x => `<span class="tag">${esc(x.doc_type)}</span>` },
    { key: 'chunks', label: 'Chunks', num: true },
    { key: 'sections', label: 'Sections', sort: false, wrap: true, render: x => `<span class="muted" style="font-size:12px">${esc(x.sections.slice(0, 4).join(' · '))}${x.sections.length > 4 ? ` +${x.sections.length - 4}` : ''}</span>` },
  ], d.docs.map(x => ({ ...x, id: x.doc_id })), { sortKey: 'doc_id', sortDir: 1, onRow: x => {
    const cs = chunks.filter(c => c.doc_id === x.doc_id);
    drawer(x.title, cs.map((c, i) => `<div class="passage"><div class="h"><b class="mono" style="font-size:11.5px">${esc(c.chunk_id)}</b><span class="tag">${esc(c.section)}</span><span class="muted" style="margin-left:auto;font-size:11.5px">${c.text.split(/\s+/).length} words</span></div><p style="-webkit-line-clamp:unset">${esc(c.text)}</p></div>`).join(''), { sub: `${x.doc_id} · ${x.doc_type} · ${cs.length} chunks` });
  } });
}

async function renderEval(host, alive) {
  loading(host, 300);
  const e = await cached('rageval', () => API.get('copilot/eval')); if (!alive()) return;
  if (!e.final) { host.innerHTML = '<div class="empty">Run python -m oip index to evaluate retrieval.</div>'; return; }
  const f = e.final; const sizes = [...new Set(e.grid.map(g => g.chunk_words))]; const modes = ['bm25', 'dense', 'hybrid']; const mlab = { bm25: 'Keyword (BM25)', dense: 'Semantic (dense)', hybrid: 'Hybrid (RRF)' };
  const g = (m, s) => e.grid.find(x => x.mode === m && x.chunk_words === s) || {};
  const misses = f.rows.filter(r => r.first_correct_rank !== 1);
  host.innerHTML = `<section class="kpis" style="margin-bottom:14px">
      <div class="kpi"><span class="l">Test questions</span><span class="v">${f.n}</span><span class="meta">each with the documents that should answer it</span></div>
      <div class="kpi"><span class="l">Hit @ 1</span><span class="v">${F.pct0(f.hit_at_1)}</span><span class="meta">right document ranked first</span></div>
      <div class="kpi"><span class="l">Hit @ 3</span><span class="v">${F.pct0(f.hit_at_3)}</span><span class="meta">right document in the top three</span></div>
      <div class="kpi"><span class="l">Mean reciprocal rank</span><span class="v">${F.ratio(f.mrr)}</span><span class="meta">1.0 = always first</span></div>
      <div class="kpi"><span class="l">Citation accuracy</span><span class="v">${F.pct0(f.citation_accuracy)}</span><span class="meta">top passage is an expected source</span></div>
      <div class="kpi"><span class="l">Chosen setup</span><span class="v" style="font-size:17px;padding-top:5px">${esc(mlab[f.mode])}</span><span class="meta">${f.chunk_words}-word chunks</span></div></section>
    <div class="grid">
      <section class="card c6"><div class="card-h"><h3>Hit @ 3 by chunk size and retrieval mode</h3></div><div class="card-b"><div id="e1"></div><div class="legend" style="margin-top:6px">${modes.map((m, i) => `<span><i style="background:${['var(--s4)', 'var(--s2)', 'var(--s1)'][i]}"></i>${mlab[m]}</span>`).join('')}</div></div></section>
      <section class="card c6"><div class="card-h"><h3>Mean reciprocal rank</h3></div><div class="card-b"><div id="e2"></div></div></section>
      <section class="card c12"><div class="card-b"><div class="narr"><p>Keyword search wins on exact terms such as queue codes and SOP numbers; semantic search wins on paraphrases ("customers hanging up" for abandonment). Fusing the two put the right document in the top three for every test question at ${f.chunk_words}-word chunks.</p><p>Larger chunks did not help: they mix several procedures in one passage, which blurs the ranking and makes citations less precise.</p><p>${misses.length ? `${misses.length} question${misses.length > 1 ? 's' : ''} did not get the right document first; they are listed first below and are the cases to improve (usually two documents that both legitimately cover the topic).` : 'Every question retrieved an expected document first.'}</p></div></div></section>
      <section class="card c12"><div class="card-h"><h3>Test set</h3><span class="sub">hybrid, ${f.chunk_words}-word chunks</span></div><div class="card-b flush" id="e3"></div></section></div>`;
  const chart = (el, key) => comboChart(el, { x: sizes.map(s => s + ' words'), height: 220, xTickW: 50,
    series: modes.map((m, i) => ({ name: mlab[m], values: sizes.map(s => g(m, s)[key]), kind: 'bar', color: ['var(--s4)', 'var(--s2)', 'var(--s1)'][i] })),
    yl: { format: F.pct0, min: key === 'mrr' ? 0.6 : 0.6, max: 1 }, tipTitle: l => `Chunks of ${l}` });
  chart($('#e1'), 'hit_at_3'); chart($('#e2'), 'mrr');
  sortableTable($('#e3'), [
    { key: 'question', label: 'Question', wrap: true, render: r => esc(r.question) },
    { key: 'expected', label: 'Expected', render: r => r.expected.map(x => `<span class="tag">${esc(x)}</span>`).join(' ') },
    { key: 'retrieved', label: 'Retrieved (top 5)', sort: false, wrap: true, render: r => r.retrieved.map((x, i) => `<span class="mono" style="font-size:11.5px;${r.expected.includes(x) ? 'color:var(--good-ink);font-weight:600' : 'color:var(--ink-3)'}">${i + 1}.${esc(x)}</span>`).join(' ') },
    { key: 'first_correct_rank', label: 'First hit', num: true, render: r => r.first_correct_rank < 99 ? `<span class="${r.first_correct_rank === 1 ? 'st-good' : ''}">#${r.first_correct_rank}</span>` : '<span class="st-bad">miss</span>' },
    { key: 'citation_correct', label: 'Citation', render: r => r.citation_correct ? '<span class="pill good">correct</span>' : '<span class="pill crit">wrong</span>' },
  ], f.rows.map((r, i) => ({ ...r, id: i, first_correct_rank: r.first_correct_rank || 99 })), { sortKey: 'first_correct_rank', sortDir: -1 });
}
