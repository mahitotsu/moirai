from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import boto3
from strands import tool

_TICKETS_TABLE = "agora-tickets"
_REPORTS_TABLE = "agora-reports"
_REGION = "us-east-1"


def _now() -> str:
    return datetime.now(UTC).isoformat()


@tool
def get_ticket_stats() -> str:
    """Aggregate incident ticket statistics for the past 30 days.

    Scans the tickets table and returns counts grouped by status, category,
    and severity. Use this to understand incident trends and workload.

    Returns:
        JSON-formatted summary of ticket counts by dimension.
    """
    try:
        dynamodb = boto3.resource("dynamodb", region_name=_REGION)
        table = dynamodb.Table(_TICKETS_TABLE)
        resp = table.scan()
        tickets: list[dict[str, Any]] = resp.get("Items", [])
    except Exception as exc:
        return f"Ticket stats failed: {exc}"

    by_status: dict[str, int] = {}
    by_category: dict[str, int] = {}
    by_severity: dict[str, int] = {}
    recent_resolved: list[dict[str, str]] = []

    cutoff = (datetime.now(UTC) - timedelta(days=30)).isoformat()
    for t in tickets:
        if t.get("created_at", "") < cutoff:
            continue
        s = t.get("status", "unknown")
        c = t.get("category", "unknown")
        v = t.get("severity", "unknown")
        by_status[s] = by_status.get(s, 0) + 1
        by_category[c] = by_category.get(c, 0) + 1
        by_severity[v] = by_severity.get(v, 0) + 1
        if t.get("status") == "resolved":
            recent_resolved.append({
                "ticket_id": str(t.get("ticket_id", "")),
                "title": str(t.get("title", ""))[:80],
                "category": str(t.get("category", "")),
                "resolved_at": str(t.get("resolved_at", "")),
            })

    return json.dumps({
        "total_tickets_last_30d": sum(by_status.values()),
        "by_status": by_status,
        "by_category": by_category,
        "by_severity": by_severity,
        "recent_resolved": sorted(
            recent_resolved, key=lambda x: x["resolved_at"], reverse=True
        )[:5],
    }, ensure_ascii=False, indent=2)


@tool
def get_lambda_error_metrics(function_names: list[str], hours: int = 24) -> str:
    """Retrieve Lambda error rate metrics from CloudWatch.

    Fetches Errors and Invocations metrics for the specified Lambda functions
    over the given time window. Use this to understand agent invocation health.

    Args:
        function_names: List of Lambda function names to query.
        hours: Lookback window in hours (default 24).

    Returns:
        JSON-formatted error counts and invocation counts per function.
    """
    try:
        cw = boto3.client("cloudwatch", region_name=_REGION)
        end = datetime.now(UTC)
        start = end - timedelta(hours=hours)
        period = max(3600, hours * 60)

        results: dict[str, Any] = {}
        for fn_name in function_names:
            queries = [
                {
                    "Id": "errors",
                    "MetricStat": {
                        "Metric": {
                            "Namespace": "AWS/Lambda",
                            "MetricName": "Errors",
                            "Dimensions": [{"Name": "FunctionName", "Value": fn_name}],
                        },
                        "Period": period,
                        "Stat": "Sum",
                    },
                },
                {
                    "Id": "invocations",
                    "MetricStat": {
                        "Metric": {
                            "Namespace": "AWS/Lambda",
                            "MetricName": "Invocations",
                            "Dimensions": [{"Name": "FunctionName", "Value": fn_name}],
                        },
                        "Period": period,
                        "Stat": "Sum",
                    },
                },
            ]
            resp = cw.get_metric_data(MetricDataQueries=queries, StartTime=start, EndTime=end)
            metric_results = {
                r["Id"]: sum(r.get("Values", [0]))
                for r in resp.get("MetricDataResults", [])
            }
            errors = metric_results.get("errors", 0)
            invocations = metric_results.get("invocations", 0)
            error_rate = round(errors / invocations * 100, 1) if invocations > 0 else 0.0
            results[fn_name] = {
                "invocations": invocations,
                "errors": errors,
                "error_rate_pct": error_rate,
            }
        return json.dumps(results, indent=2)
    except Exception as exc:
        return f"Lambda metrics query failed: {exc}"


@tool
def get_bedrock_costs(days: int = 7) -> str:
    """Retrieve Bedrock API usage costs from Cost Explorer.

    Queries AWS Cost Explorer for Bedrock service costs over the specified
    number of days, grouped by usage type.

    Args:
        days: Number of days to look back (default 7, max 30).

    Returns:
        JSON-formatted cost breakdown for Bedrock service.
    """
    days = min(days, 30)
    try:
        ce = boto3.client("ce", region_name="us-east-1")
        end = datetime.now(UTC).date()
        start = end - timedelta(days=days)

        resp = ce.get_cost_and_usage(
            TimePeriod={"Start": str(start), "End": str(end)},
            Granularity="DAILY",
            Filter={"Dimensions": {"Key": "SERVICE", "Values": ["Amazon Bedrock"]}},
            Metrics=["UnblendedCost"],
            GroupBy=[{"Type": "DIMENSION", "Key": "USAGE_TYPE"}],
        )

        daily_totals: dict[str, float] = {}
        usage_type_totals: dict[str, float] = {}

        for result in resp.get("ResultsByTime", []):
            date = result["TimePeriod"]["Start"]
            day_total = 0.0
            for group in result.get("Groups", []):
                amount = float(group["Metrics"]["UnblendedCost"]["Amount"])
                day_total += amount
                usage_type = group["Keys"][0] if group.get("Keys") else "Unknown"
                usage_type_totals[usage_type] = usage_type_totals.get(usage_type, 0.0) + amount
            daily_totals[date] = round(day_total, 4)

        total = round(sum(daily_totals.values()), 4)
        return json.dumps({
            "period_days": days,
            "total_usd": total,
            "daily_totals_usd": daily_totals,
            "by_usage_type_usd": {k: round(v, 4) for k, v in sorted(
                usage_type_totals.items(), key=lambda x: x[1], reverse=True
            )},
        }, indent=2)
    except Exception as exc:
        return f"Cost Explorer query failed: {exc}"


@tool
def save_report(title: str, report_type: str, summary: str, details: str) -> str:
    """Save a generated analysis report to the reports store.

    Writes the report to DynamoDB so it can be retrieved via the Reports Service.

    Args:
        title: Human-readable report title.
        report_type: One of: incident-summary, cost, operational, custom.
        summary: 2-4 sentence executive summary of key findings.
        details: Full report content in markdown format.

    Returns:
        The new report_id if successful, or an error message.
    """
    valid_types = {"incident-summary", "cost", "operational", "custom"}
    if report_type not in valid_types:
        report_type = "custom"

    try:
        dynamodb = boto3.client("dynamodb", region_name=_REGION)
        report_id = str(uuid.uuid4())
        now = _now()
        dynamodb.put_item(
            TableName=_REPORTS_TABLE,
            Item={
                "report_id": {"S": report_id},
                "title": {"S": title},
                "type": {"S": report_type},
                "summary": {"S": summary},
                "details": {"S": details},
                "created_at": {"S": now},
            },
        )
        return json.dumps({"report_id": report_id, "created_at": now})
    except Exception as exc:
        return f"Failed to save report: {exc}"
