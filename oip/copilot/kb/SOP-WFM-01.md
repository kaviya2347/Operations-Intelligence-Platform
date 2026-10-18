---
doc_id: SOP-WFM-01
title: Intraday Management and Real-Time Adherence
doc_type: SOP
owner: Workforce Management
version: 3.2
effective: 2026-01-15
---
# Purpose
This procedure tells the real-time analyst (RTA) and team leaders how to protect service level during the day. It applies to every real-time queue: voice (Billing, Technical Support, Claims, Cards) and chat (Chat Care, Orders).

# Monitoring cadence
The RTA reviews every queue at least every 15 minutes against the interval plan: forecast volume, forecast AHT, required agents and scheduled agents. The live wallboard shows calls waiting, longest wait, service level for the current interval and the day, agents available, on contact and in aux.

# Trigger levels
- Amber: interval service level more than 5 points below target, or more than 3 calls waiting for longer than the answer threshold.
- Red: interval service level more than 10 points below target for two consecutive intervals, or abandon rate above 10% in an interval, or staffed agents below 90% of required for the next interval.
On amber the RTA alerts the team leader on the floor. On red the RTA follows SOP-OPS-03 (escalation matrix) and records the event in the intraday log.

# Actions in order of cost
1. Pull agents out of aux and offline work: coaching, meetings and training are moved to the next interval with surplus.
2. Delay breaks within the agreed 15-minute window.
3. Move cross-skilled agents from queues running above target (overflow, see SOP-OPS-03).
4. Activate the callback offer for waiting callers (SOP-OPS-04).
5. Offer voluntary overtime or early log-in for the next day's affected intervals.
6. Re-forecast the rest of the day if volume is running more than 10% above forecast for two intervals.

# Adherence
Schedule adherence target is 92%. Agents should be in the state their schedule shows; logging in late to a morning shift is the most common cause of a weak first hour. Team leaders review adherence exceptions daily.

# Recurring gaps
If the same intervals breach on more than three days in a week, the issue is structural, not intraday. The RTA raises a roster review request to the WFM planner (SOP-WFM-02, section "Roster change control") with the interval list and the staffed-to-required ratio for each interval. Intraday actions should not be used to cover a structural roster gap for more than one week.

# Records
Every red event is logged with time, queue, trigger, action taken and outcome. The log feeds weekly service reviews and root-cause analysis.
