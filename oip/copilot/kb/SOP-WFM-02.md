---
doc_id: SOP-WFM-02
title: Forecasting, Capacity Planning and Roster Change Control
doc_type: SOP
owner: Workforce Management
version: 2.4
effective: 2026-02-01
---
# Forecasting
Volume is forecast daily for each queue and spread over 30-minute intervals with the recent intraday profile for that weekday. The daily model uses lagged volume (1, 7 and 14 days), rolling means, day of week, month, holiday indicators, the previous day's staffing ratio and handle time. Model accuracy is judged on a hold-out period after the training period; a model is only used if it beats a 7-day moving average baseline. Forecast accuracy (WAPE) is reported weekly. Known events (billing cycle days, client sales, product releases) are added as manual uplifts after the statistical forecast.

# Required agents
Required agents per interval are calculated with Erlang C from forecast volume, forecast AHT and the queue's service level target and threshold. Chat queues assume a concurrency of two sessions per agent. Email and back-office queues use workload: volume x AHT / (interval seconds x 85% occupancy).

# From required to scheduled
Scheduled heads = required agents / (1 - planned shrinkage). Planned shrinkage is 30%, covering leave, unplanned absence, breaks, coaching and training. Shrinkage above 35% for a week is reviewed with operations.

# Roster change control
Any change to shift start times, shift lengths or break patterns must be validated before publishing:
1. Build the new roster in the WFM tool.
2. Compare scheduled heads with required heads for every interval of a typical week, including the busiest weekday.
3. No interval may fall below 95% of required heads, unless the operations manager approves it in writing.
4. Publish two weeks ahead and monitor the first two weeks interval by interval.
A roster that moves a shift start later in the morning must be checked specifically for the 10:00 to 12:00 peak, which carries the highest volume on most voice queues.

# Peaks and events
Client-driven peaks (sales, bill runs, policy renewals) are planned with the client's account team at least three weeks ahead. See PLAYBOOK-KES-01 for retail sale events.

# Review cadence
Weekly: forecast accuracy, shrinkage, staffed-to-required by interval, intervals below 90% coverage. Monthly: model retraining and profile refresh.
