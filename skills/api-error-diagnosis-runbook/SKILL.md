---
name: api-error-diagnosis-runbook
description: Approved runbook for diagnosing AWS API throttling errors and SDK client failures
---

# API Error Diagnosis Runbook

Apply this runbook when an incident involves AWS API throttling (`ThrottlingException`,
`RequestLimitExceeded`), SDK `ClientError`, or service quota exhaustion.

## Investigation Sequence

Follow these steps **in order** — stop and record findings at each step before proceeding.

### Step 1 — Check for active FIS fault injection

Call `list_active_fis_experiments` first.

- If a FIS experiment is **running**: treat it as the confirmed root cause.
  Record the experiment template name and the target action (e.g., `aws:ec2:api-unavailable`
  targeting `ec2:DescribeInstances`). No further root-cause investigation is needed —
  proceed directly to step 5 for documentation.
- If no FIS experiment is active: continue to step 2.

### Step 2 — Check CloudWatch alarms

Call `get_active_alarms` to identify which alarms are in ALARM state.
Then call `get_alarm_history` on the specific alarm to understand when throttling started
and whether it is worsening or stabilizing.

### Step 3 — Inspect the failing Lambda

Call `inspect_lambda` for the function named in the incident (e.g., `agora-fake-api-server`).

Check for:
- **Reserved concurrency**: High concurrency × high call frequency amplifies throttling.
- **Timeout setting**: Short timeouts with aggressive retries cause retry storms.
- **Environment variables**: Look for retry configuration (backoff, max attempts).

### Step 4 — Search community knowledge

Search Stack Overflow and GitHub Issues for the specific error message and service name
(e.g., `"ThrottlingException ec2 DescribeInstances boto3"`).
Search AWS Documentation for current service quotas and best practices for the affected API.

### Step 5 — Check past incidents

Call `search_past_tickets` to find previous throttling incidents.
If a prior ticket exists with a `lesson_learned` field, that pattern likely recurs — note it
explicitly in your diagnosis.

## Confidence Levels

| Level | When to assign |
|---|---|
| **high** | FIS experiment active AND error pattern matches the injected action |
| **medium** | No FIS active, but quota metrics show sustained throttling above the service limit |
| **low** | No clear evidence — recommend investigating retry logic and SDK configuration |

## Key Diagnostic Questions

1. Is the throttling caused by FIS (controlled) or organic traffic growth (uncontrolled)?
2. What is the observed API call rate vs. the account service quota?
3. Are retries implemented with exponential backoff and jitter?
4. Does the Lambda have reserved concurrency that limits parallel execution?
