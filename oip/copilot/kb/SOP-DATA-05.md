---
doc_id: SOP-DATA-05
title: Unclosed Agent Sessions and Reporting Data Corrections
doc_type: SOP
owner: Reporting and Analytics
version: 1.3
effective: 2026-03-01
---
# Problem
When an agent closes the softphone without logging out, or the desktop crashes during a call, the dialler may not record the call's end. The call then shows an extreme talk time, sometimes several hours, and inflates average handle time for the agent, the team and the queue.

# Detection rule
A handled contact is treated as an unclosed session when all three are true:
1. Its handle time is above the queue's upper fence (third quartile plus three times the interquartile range).
2. Its handle time is above 7,200 seconds.
3. The agent's session log for that day has no logout event.
Extreme handle times that do not meet all three conditions are kept: they can be genuine complex calls and must not be removed just for being long.

# Treatment
Unclosed-session contacts are capped at the queue's 99th percentile handle time and flagged. The raw value is preserved in a separate column for audit. The capping rule was approved by the reporting lead after an investigation of the session logs; before approval, outliers were flagged only.

# Other corrections
- Negative wait times (clock skew between dialler nodes) are set to zero and flagged.
- Missing hold time on answered calls takes the queue median, because hold time is right-skewed.
- Answered calls with no agent captured are kept as UNASSIGNED. An earlier rule dropped them and caused answered counts to fall below the dialler's own daily report; reconciliation exposed the gap.

# Reconciliation
After every cleaning run, offered, answered and abandoned counts per queue per day are compared with the dialler and chat platform daily reports. Any variance must be explained before reports are published.
