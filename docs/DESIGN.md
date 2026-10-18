# Design notes

Why each module is built the way it is. Read with the README.

## 1. Data: generate defects on purpose

The platform's value is in handling messy data, so the generator produces it: 17 spellings of the same queue in the dialler, re-exported duplicate rows, a second timestamp format, negative waits from clock skew, blank dispositions, missing hold time, unclosed agent sessions, and clear PII in the CRM. Each defect has a numbered rule that fixes it and a test that proves it stays fixed. Business events are planted with known causes (a roster change, a system slowdown, a sale, an app release), so the analytics can be checked against the truth rather than judged by eye.

## 2. Masking happens on the way in

Customer phone numbers, emails and names are hashed with a salted SHA-256 the moment an extract lands in staging, and a masked display form is kept for case look-ups. The clear values never reach the warehouse. The hash keeps customers joinable across channels, which first contact resolution needs. Staging tables are blocked from the SQL lab; the API uses a read-only connection.

## 3. Cleaning is a log, not a script

Every rule is a function that records rows before, after and affected, plus the decision and its history (`gov_cleaning_log`). Two rules carry history from review:

- **R06**: the first version dropped answered contacts with a blank agent login. Reconciling three sample dates against the dialler's own report showed answered counts a few short each day. The rule now keeps and flags those rows.
- **R08**: extreme handle times were only flagged until the session-log investigation showed most were unclosed sessions; capping those (and only those) at the queue P99 was approved afterwards.

## 4. One definition per metric

`warehouse/metrics.py` is the single registry. Each metric is a numerator and a denominator built from additive cube columns, with the exclusions written out. The SQL views, the dashboard's in-browser engine and the generated Power BI measures all read from it, so a ratio is always a ratio of sums and re-aggregates correctly across any filter. Parity tests compare the cube with the fact table.

The short-abandon rule is the example that justified this: service level computed with and without the five-second exclusion differed from the operations month-end figure until the rule was aligned.

## 5. Cube grain: queue × day × half-hour

Thirty minutes is the workforce-planning grain. Daily numbers hide the problem the root-cause study exists to find (Billing looks acceptable per day and fails in four morning half-hours). The cube has 28k rows, small enough to send to the browser, so filters and drill-downs are instant without round trips.

## 6. Root cause: significance before attribution

- **Breach rule**: an interval is a breach only when its service level is below target by more than 1.645 binomial standard errors at its volume. A half-hour with eight calls missing target by one call is noise.
- **Pareto and hotspots**: breaches are counted by half-hour; a half-hour is a hotspot when its breach rate is significantly above the queue's.
- **Change point**: a split search on the hotspot breach rate dates when the problem started (6 April).
- **Hypotheses**: staffing shortfall, volume spike and handle-time inflation are each tested breach vs normal intervals (Mann–Whitney U).
- **Attribution**: for each breach interval, service level is recomputed with Erlang C, setting staffing, volume and handle time back to plan in all eight combinations; Shapley values split the gap fairly. This avoids the order-dependence of "change one factor at a time".
- **What-if**: staffing the hotspots to requirement lifts the queue from 82.4% to 85.0%.

## 7. Forecasting: beat the baseline, never shuffle

Daily volume per queue, chronological split (train before 11 May, test 11–31 May). A random split leaks the future through lag features. Every model must beat a seven-day moving average and a seasonal-naive forecast. Random forest wins on eight of nine queues (mean MAPE 9.3% vs 19.5% for the moving average). The 14-day forecast is recursive (each day's prediction feeds the next day's lags), spread over intervals with the queue's intraday profile, and converted to heads with Erlang C and 30% shrinkage. The Kestrel sale is under-called by every model because promotions are not a feature yet; that is stated rather than hidden.

## 8. Alerts: robust baselines and structural problems

Daily KPIs are compared with a 28-day rolling median and MAD (robust z ≥ 3.5, harmful direction only); volume uses a same-weekday baseline so Mondays are not anomalies. A seven-day mean shift test catches level changes a daily score adapts to. Recurring RCA hotspots become incidents because a structural problem rarely produces a single extreme day.

## 9. Copilot: retrieval you can check

- Knowledge base as Markdown with front matter (id, type, owner, effective date). Owners review documents before indexing.
- Heading-aware chunks with a "Title > Section" header, tables rewritten as sentences, abbreviations expanded at index and query time.
- Hybrid retrieval: BM25 for exact terms (queue codes, SOP numbers), embeddings for paraphrases, reciprocal-rank fusion, then MMR to avoid near-duplicate passages.
- The model may answer only from numbered passages and the live data block, citing [n] and [L]. Without a model, an extractive mode quotes sentences with the same citations.
- Evaluation: 32 questions with expected documents, a grid over chunk size (80/160/320 words) and mode (BM25, dense, hybrid). Hybrid at 80 words: hit@3 1.00, MRR 0.93, citation accuracy 1.00.

## 10. Access: roles and row-level security in the API

Four demo identities stand in for SSO: Admin, Analyst, a Billing team leader (rows for Q01 only) and a Meridian Bank client viewer (Q04 and Q09, agent names replaced by IDs, no data-quality or SQL pages). The API applies the filter before data leaves the server; the dashboard only hides navigation. The same roles are documented as Power BI RLS in the export.

## 11. Front end without a build step

Vanilla JavaScript modules, hand-built SVG charts and CSS tokens for light and dark themes. Colour carries meaning only through tokens: one blue for actuals, a categorical palette for series, red and green only for status against target. Every chart has a tooltip or table with the exact values. The same code runs against the live API or an offline snapshot generated by calling the real API in-process, so the hosted preview cannot drift from the server.
