---
name: resolution-documentation-standard
description: Organizational standard for IT incident resolution documentation and ticket closure
---

# Resolution Documentation Standard

Apply this standard when closing IT incident tickets in the Agora system.
All fields must meet these requirements for the ticket to be considered properly documented.

## Required Fields for Ticket Closure

### `resolution` — Full Resolution Text

- **Must include**: Numbered list of step-by-step actions taken or recommended.
- **Specificity**: Use exact commands, parameter names, and tool names.
  Write `aws fis stop-experiment --id <experiment-id>` not "stop the experiment".
- **Order**: Diagnose → Mitigate → Fix root cause → Verify recovery.
- **Acknowledge uncertainty**: If diagnosis confidence is low, include diagnostic steps
  before fix steps.

### `lesson_learned` — Single Sentence

- **Format**: One concise sentence starting with "Lesson:" that can stand alone as a
  searchable insight.
- **Content**: The key takeaway that prevents recurrence or speeds up future diagnosis.
- **Good examples**:
  - "Lesson: always suppress CloudWatch alarms before running FIS experiments to avoid false incident pages."
  - "Lesson: implement exponential backoff with jitter for all AWS API retry logic to prevent throttling cascades."
- **Bad examples** (too vague): "Lesson: monitor the system carefully." / "Lesson: check logs."

### `status`

Must be `"resolved"`.

### `category`

Use the category determined during triage. Do not change it unless the triage classification
was clearly incorrect — and if so, note the correction reason in the `resolution` text.

## Pre-submission Checklist

Before calling the ticket update tool, verify:

- [ ] `resolution` steps are specific and actionable — no vague language
- [ ] `lesson_learned` is a single, memorable sentence starting with "Lesson:"
- [ ] `status` is set to `"resolved"`
- [ ] `category` matches the triage classification
- [ ] All four fields (`status`, `resolution`, `category`, `lesson_learned`) are present
      — omitting any one is an error
