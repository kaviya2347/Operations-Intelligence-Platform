---
doc_id: GOV-01
title: Data Governance, PII Handling and Access Control
doc_type: Governance
owner: Information Security and Reporting
version: 2.0
effective: 2026-01-05
---
# Classification
Customer names, phone numbers, email addresses and account numbers are personally identifiable information (PII). Employee names are internal data. Aggregated metrics are internal data.

# Masking and pseudonymisation
PII is masked when it enters the staging area. Phone numbers keep the first two and last two digits (98XXXXXX21); email addresses keep the first character and the domain (a***@gmail.com); names become initials. For joining records about the same customer across systems, identifiers are replaced with a salted SHA-256 key. Clear PII exists only in the restricted landing zone and is never loaded into the warehouse or dashboards.

# Extraction approval
No dataset leaves production without an approved request stating purpose, fields, period and retention. Only masked extracts are approved for analysis. Approvals are recorded before access is granted.

# Retention
Landing-zone extracts: 30 days. Staging and warehouse: 24 months. Call recordings follow client contracts.

# Role-based access
| Role | Access |
|---|---|
| Admin | All reporting data, governance logs, pipeline controls |
| Analyst | All queues, masked customer data, SQL lab on the warehouse (read-only) |
| Team leader | Own queues only (row-level security), agent names for own teams |
| Client viewer | Own client's queues only, no agent names |
Access is reviewed quarterly and removed on exit.

# Read-only analysis
Ad-hoc SQL runs on a read-only connection. Only SELECT statements are allowed, results are limited, and statements touching staging tables are blocked.

# Incidents
Any suspected PII exposure is reported to Information Security within one hour.
