---
doc_id: SOP-CRM-06
title: Disposition Coding Standard
doc_type: SOP
owner: Quality
version: 2.1
effective: 2026-01-20
---
# Why it matters
Dispositions drive first contact resolution, root-cause reporting and client invoices. Inconsistent coding makes all three unreliable.

# Outcome codes
Every handled contact receives exactly one outcome at wrap-up:
- Resolved: the customer's issue is fixed and nothing further is expected.
- Escalated: the issue has been handed to a second-level team; the case stays open.
- Callback scheduled: the agent has promised to call the customer at an agreed time.
- Pending customer: waiting for documents or information from the customer.
Free-text variants such as "RSLVD", "Res.", "CB Sched" or "escalated to L2" are not allowed. The CRM drop-down is the only valid input. Analytics maps legacy variants to the four codes and imputes blank codes from the case's latest status.

# Reason codes
Each queue has five reason codes (for example Billing: bill explanation, payment arrangement, plan change, dispute raised, refund request). Choose the reason the customer called about, not the action taken.

# After-call work
Disposition and notes must be completed in after-call work, not during the next call. Target ACW is 10 to 20% of handle time. Long ACW is coached, but agents must never skip notes to save time.

# Audits
Quality audits check disposition accuracy as part of the resolution parameter (QA-01). Two wrong outcome codes in a month trigger a coaching session.
