"""
OBSERVE Pillar - Orchestrator
Direct equivalent of the professor's main.py: doesn't fetch data itself,
just calls collectors and correlates/stores/publishes what they return.

DEPLOYMENT NOTE: see template.yaml's ObserveFunction Policies block --
it must include cloudwatch:GetMetricStatistics, cloudwatch:ListMetrics,
xray:GetTraceSummaries, and xray:BatchGetTraces, or the metrics/trace
collectors will fail on every call.
"""

import json
import logging
import os
import decimal
import boto3
from datetime import datetime

from collectors.cloudwatch_logs_collector import CloudWatchLogsCollector
from collectors.cloudwatch_metrics_collector import CloudWatchMetricsCollector
from collectors.xray_trace_collector import XRayTraceCollector
from processors.incident_processor import IncidentProcessor
from utils.dynamodb_client import DynamoDBClient
from utils.sns_client import SNSClient
from models.incident import Incident

logger = logging.getLogger()
logger.setLevel(logging.INFO)

REGION = "us-east-1"
TABLE_NAME = os.environ.get("TABLE_NAME", "ecom-incidents")
SNS_TOPIC = os.environ.get("SNS_TOPIC_ARN", "")
LLM_INSTANCE_ID = os.environ.get("LLM_INSTANCE_ID", "")

db_client = DynamoDBClient(table_name=TABLE_NAME, region=REGION)
sns_publisher = SNSClient(topic_arn=SNS_TOPIC) if SNS_TOPIC else None
# NOTE: no resource config, no service list anywhere -- matching the
# professor's actual design (confirmed from their real files): the
# collectors discover what exists dynamically every run, via
# describe_log_groups / list_metrics. Zero maintenance, zero coupling
# to any specific client's app.
processor = IncidentProcessor()

# kept for get_incidents()'s raw scan -- unrelated to the collector rewrite
dynamodb = boto3.resource("dynamodb", region_name=REGION)
table = dynamodb.Table(TABLE_NAME)

HEADERS = {"Content-Type": "application/json", "Access-Control-Allow-Origin": "*"}


class DecimalEncoder(json.JSONEncoder):
    def default(self, obj):
        if isinstance(obj, decimal.Decimal):
            return int(obj) if obj % 1 == 0 else float(obj)
        return super().default(obj)


def lambda_handler(event, context):
    path = event.get("path", "/")
    method = event.get("httpMethod", "GET")
    source = event.get("source", "")
    detail_type = event.get("detail-type", "")

    logger.info(f"Triggered by: source={source}, path={path}, method={method}")

    if source == "aws.events" or "Scheduled" in detail_type:
        return observe()
    elif "incidents" in path and method == "GET":
        return get_incidents()
    elif "observe" in path and method == "POST":
        return observe()
    else:
        return {"statusCode": 200, "headers": HEADERS,
                "body": json.dumps({"status": "ok", "message": "OBSERVE pillar"})}


def get_incidents():
    try:
        result = table.scan()
        items = result.get("Items", [])
        items.sort(key=lambda x: x.get("timestamp", ""), reverse=True)
        return {
            "statusCode": 200, "headers": HEADERS,
            "body": json.dumps({"incidents": items, "total": len(items)}, cls=DecimalEncoder),
        }
    except Exception as e:
        logger.error(f"Error: {e}")
        return {"statusCode": 500, "headers": HEADERS,
                "body": json.dumps({"error": str(e), "incidents": []})}


def observe():
    """
    FIX vs current version: this now calls BOTH collectors (all 6 services,
    logs AND metrics) instead of the old inline 2-service log-only check.
    """
    try:
        logger.info("OBSERVE starting...")

        # Zero config -- both collectors discover their own resources
        # dynamically on every run, exactly matching the professor's
        # actual design (no service list, ever, anywhere).
        logs_collector = CloudWatchLogsCollector(region=REGION)
        metrics_collector = CloudWatchMetricsCollector(region=REGION)
        trace_collector = XRayTraceCollector(region=REGION)

        logs_result = logs_collector.collect_and_detect(minutes=5)
        metrics_result = metrics_collector.collect_and_detect(minutes=5)
        trace_result = trace_collector.collect_and_detect(minutes=5)

        logger.info(f"Logs collector: {logs_result.incidents_detected} incidents "
                    f"from {logs_result.data_count} log lines")
        logger.info(f"Metrics collector: {metrics_result.incidents_detected} incidents "
                    f"from {metrics_result.data_count} data points")
        logger.info(f"Trace collector: {trace_result.incidents_detected} incidents "
                    f"from {trace_result.data_count} spans")

        all_incidents = (
            list(logs_result.incidents)
            + list(metrics_result.incidents)
            + list(trace_result.incidents)
        )
        correlated = _correlate_incidents(all_incidents)

        # NEW: enrich (urgency, critical_service flag) and prioritize
        # before storing -- this is the IncidentProcessor step that
        # didn't exist in the project before.
        correlated = processor.enrich_incidents(correlated)
        correlated = processor.prioritize_incidents(correlated)

        stored_count = 0
        for incident in correlated:
            if db_client.store_incident(incident):
                stored_count += 1
                if sns_publisher:
                    sns_publisher.publish_incident(incident)

        return {
            "statusCode": 200, "headers": HEADERS,
            "body": json.dumps({
                "incidents_found": len(correlated),
                "incidents_stored": stored_count,
                "logs_errors": logs_result.errors,
                "metrics_errors": metrics_result.errors,
            }),
        }

    except Exception as e:
        logger.error(f"OBSERVE error: {e}")
        return {"statusCode": 500, "headers": HEADERS, "body": json.dumps({"error": str(e)})}


def _correlate_incidents(incidents):
    """
    Same rule as the professor's _correlate_incidents: same resource +
    within 5 minutes = merge. This is new -- your current code has no
    correlation at all, since it only ever had one data source (logs).
    Now that logs AND metrics both exist, this is what stops a single
    real problem showing up as two separate incidents.
    """
    if len(incidents) <= 1:
        return incidents

    merged = []
    used = set()

    for i, inc in enumerate(incidents):
        if inc.id in used:
            continue
        group = [inc]
        for other in incidents[i + 1:]:
            if other.id in used:
                continue
            same_resource = other.resource.resource_name == inc.resource.resource_name
            close_in_time = abs(
                (datetime.fromisoformat(other.timestamp) - datetime.fromisoformat(inc.timestamp)).total_seconds()
            ) < 300
            if same_resource and close_in_time:
                group.append(other)
                used.add(other.id)

        if len(group) > 1:
            merged.append(_merge_group(group))
        else:
            merged.append(inc)
        used.add(inc.id)

    return merged


def _merge_group(group):
    """Same idea as the professor's _merge_related_incidents:
    most severe becomes the base, evidence gets combined."""
    severity_rank = {"CRITICAL": 4, "HIGH": 3, "MEDIUM": 2, "LOW": 1}
    base = max(group, key=lambda x: severity_rank.get(x.severity, 0))

    for inc in group:
        if inc.id != base.id:
            base.logs.extend(inc.logs)
            base.metrics.extend(inc.metrics)
            base.traces.extend(inc.traces)

    base.description += f" (Correlated from {len(group)} sources)"
    base.tags["correlated_sources"] = str(len(group))
    base.confidence_score = round(min(1.0, base.confidence_score * 1.2), 2)
    return base


# store/publish now handled by db_client (DynamoDBClient) and
# sns_publisher (SNSClient) -- see the observe() function above.
# Removed the duplicate inline versions that used to live here.