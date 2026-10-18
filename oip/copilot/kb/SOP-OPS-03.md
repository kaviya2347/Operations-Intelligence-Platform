---
doc_id: SOP-OPS-03
title: Queue Overflow and Escalation Matrix
doc_type: SOP
owner: Operations
version: 4.0
effective: 2026-01-10
---
# Escalation matrix
| Condition | Escalate to | Within |
|---|---|---|
| Interval service level 10+ points below target for two intervals | Team leader and RTA | Immediately |
| Daily service level below target by 3 p.m. | Operations manager | 30 minutes |
| Abandon rate above 10% for an interval | Operations manager | 15 minutes |
| Service level below target for three consecutive days | Head of delivery and client account manager | Same day |
| System outage or latency affecting handle time | IT service desk (P1) and operations manager | Immediately |

# Overflow rules
Agents skilled on more than one queue can be moved temporarily. Overflow is allowed only from a queue running at least 5 points above its target, and only for the intervals at risk. Priority order when several queues are at risk: Platinum clients (Meridian Bank) first, then Gold (Northwind Telecom, Kestrel Retail), then Silver (Halcyon Insurance). Overflow agents must be released when the receiving queue returns to target for one full interval.

# Cross-skilled pools
- Northwind Billing and Northwind Chat Care share 12 cross-skilled agents.
- Meridian Cards agents are trained on Meridian KYC back office and can be pulled back to voice during peaks.
- Kestrel Orders chat agents can work Kestrel Returns email in quiet intervals.

# Communication
Every overflow move is posted in the floor channel with queue, number of agents and expected duration. Client account managers are informed of any day expected to miss contractual service level before the end of that day.

# After the event
For any day that misses the contractual target, the operations manager records the cause within 24 hours. Three such days in a month trigger a formal root-cause analysis.
