---
name: incident-severity-classification
description: Agora IT ops organization-approved criteria for classifying incident severity and category
---

# Incident Severity & Category Classification

This skill defines the classification standards approved by the Agora IT operations team.
Apply these criteria consistently across all incident handling stages.

## Severity Tiers

| Severity | Definition | SLA Response Target |
|---|---|---|
| **critical** | Production fully down, data loss risk, or active security breach | 15 minutes |
| **high** | Major feature broken, many users impacted, SLA breach imminent | 1 hour |
| **medium** | Partial degradation, workaround exists, limited user impact | 4 hours |
| **low** | Minor issue, cosmetic bug, or single-user impact | 1 business day |

When in doubt between two severity levels, escalate to the higher one.

## Category Taxonomy

| Category | When to apply |
|---|---|
| **database** | Connection errors, query timeouts, replication lag, OOM in DB process |
| **network** | Timeouts, 502/503/504 errors, DNS failures, AWS API throttling, packet loss |
| **memory** | OOM kills, high memory usage alerts, memory leak indicators |
| **deploy** | Post-deployment regressions, container startup failures, config drift |
| **performance** | High CPU/latency, slow queries, throughput degradation |
| **security** | Authentication failures, unauthorized access attempts, certificate errors |
| **other** | Anything that does not clearly fit the above categories |

**Note on AWS API throttling**: `ThrottlingException` and `RequestLimitExceeded` errors from
AWS APIs (e.g., EC2, Lambda) map to the **network** category, as they represent service
availability degradation from the caller's perspective.
