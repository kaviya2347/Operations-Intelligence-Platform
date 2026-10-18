---
doc_id: SOP-OPS-04
title: Abandoned Call Recovery and Callback
doc_type: SOP
owner: Operations
version: 1.6
effective: 2025-11-01
---
# When callback is offered
The virtual callback offer plays when the estimated wait passes 90 seconds on a voice queue. The caller keeps their place and is called back when an agent becomes free. Callback is activated by the RTA during red events (SOP-WFM-01) and is always on for Billing during the first five days of the month.

# Abandoned call recovery
Callers who abandon after more than the short-abandon threshold (5 seconds) are placed on the recovery list if their number is identified. The recovery team calls them back within two hours during business hours. Recovery calls are logged with the disposition "Callback scheduled" until completed.

# Reporting rules
Short abandons (5 seconds or less) are excluded from service level and abandon rate, because they are mostly misdials or callers who hang up on the greeting. Recovery calls are counted as outbound contacts and are not added back to inbound service level.

# Targets
Recovery contact rate: 70% of eligible abandons reached within two hours. Callback completion within the promised window: 90%.

# Customer experience
Callback agents open by referencing the earlier attempt: "We are returning your call from earlier today; thank you for waiting." Repeat contacts caused by abandons lower first contact resolution, so recovering them quickly protects FCR.
