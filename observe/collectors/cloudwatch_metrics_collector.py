"""
CloudWatch Metrics Collector
Equivalent role to the professor's CloudMonitoringCollector.

FIXED per feedback: this now uses a single flat metric_types list,
matching the professor's format and breadth -- spanning MULTIPLE AWS
services (Lambda, DynamoDB, SQS, API Gateway), not just Lambda alone.
No CPU -- Lambda doesn't expose it -- but everything else follows the
same "one flat list of service:metric strings" shape.
"""

import boto3
import logging
import os
import uuid
from datetime import datetime, timedelta
from typing import List, Optional, Dict

from ..models.incident import (
    Incident, MetricPoint, AWSResource, CollectorResult,
    Severity, IncidentSource
)

logger = logging.getLogger()


class CloudWatchMetricsCollector:
    def __init__(self, region: str = "us-east-1"):
        self.region = region
        self.client = boto3.client("cloudwatch", region_name=region)

        # NEW: EC2 instance ID for the self-hosted LLM box, passed in
        # via template.yaml's LLM_INSTANCE_ID environment variable.
        # These CPU/disk/memory metrics are now meaningful, since a real
        # workload (Ollama) runs on this instance -- not padding.
        self.llm_instance_id = os.environ.get("LLM_INSTANCE_ID", "")

        # Direct structural equivalent of the professor's metric_types list:
        # one flat list, spanning multiple AWS services, formatted as
        # "Namespace:MetricName" (AWS's closest analog to GCP's single
        # dotted-path string).
        self.metric_types = [
            "AWS/Lambda:Duration",
            "AWS/Lambda:Errors",
            "AWS/Lambda:Throttles",
            "AWS/Lambda:Invocations",
            "AWS/Lambda:ConcurrentExecutions",
            "AWS/ApiGateway:Latency",
            "AWS/ApiGateway:5XXError",
            "AWS/DynamoDB:ConsumedReadCapacityUnits",
            "AWS/DynamoDB:ThrottledRequests",
            "AWS/SQS:ApproximateNumberOfMessagesVisible",
            "AWS/EC2:CPUUtilization",     # ← NEW -- now has a real VM to measure
            "AWS/EC2:NetworkIn",           # ← NEW
        ]

        # Which specific resource(s) each namespace should be checked
        # against, and which CloudWatch dimension key identifies them.
        # This is the piece GCP doesn't need (their filter string handles
        # it implicitly) but AWS's API requires explicitly.
        self.resources_by_namespace: Dict[str, List[Dict[str, str]]] = {
            "AWS/Lambda": [
                {"dimension": "FunctionName", "value": f}
                for f in [
                    "ecom-auth-service", "ecom-payments-service",
                    "ecom-products-service", "ecom-orders-service",
                    "ecom-cart-service", "ecom-tracking-service",
                ]
            ],
            "AWS/ApiGateway": [
                {"dimension": "ApiName", "value": "MyApi"},
            ],
            "AWS/DynamoDB": [
                {"dimension": "TableName", "value": t}
                for t in ["ecom-incidents", "ecom-users", "ecom-payments"]
            ],
            "AWS/SQS": [
                {"dimension": "QueueName", "value": "ecom-events-queue"},
            ],
            "AWS/EC2": [
                {"dimension": "InstanceId", "value": self.llm_instance_id}
            ] if self.llm_instance_id else [],  # skip cleanly if not deployed yet
        }

    def collect_and_detect(self, minutes: int = 5) -> CollectorResult:
        errors = []
        try:
            end_time = datetime.utcnow()
            start_time = end_time - timedelta(minutes=minutes)

            all_points = []
            # Same "loop through each metric type, tolerate individual
            # failures" pattern as the professor's collect_metrics --
            # one bad metric type doesn't stop the rest.
            for metric_type in self.metric_types:
                points, err = self._collect_single_metric_type(metric_type, start_time, end_time)
                if err:
                    errors.append(err)
                all_points.extend(points)

            incidents = self._detect_incidents(all_points)

            return CollectorResult(
                collector_name="cloudwatch_metrics",
                success=True,
                data_count=len(all_points),
                incidents_detected=len(incidents),
                errors=errors,
                incidents=incidents,
            )

        except Exception as e:
            logger.error(f"CloudWatchMetricsCollector failed entirely: {e}")
            return CollectorResult(
                collector_name="cloudwatch_metrics",
                success=False, data_count=0, incidents_detected=0, errors=[str(e)],
            )

    def _collect_single_metric_type(self, metric_type: str, start_time: datetime, end_time: datetime):
        """
        Direct equivalent of the professor's _collect_single_metric_type.
        Parses "Namespace:MetricName", then loops over every resource
        registered under that namespace (the extra step AWS needs that
        GCP's filter string handled implicitly).
        """
        namespace, metric_name = metric_type.split(":")
        resources = self.resources_by_namespace.get(namespace, [])
        points = []

        for resource in resources:
            try:
                resp = self.client.get_metric_statistics(
                    Namespace=namespace,
                    MetricName=metric_name,
                    Dimensions=[{"Name": resource["dimension"], "Value": resource["value"]}],
                    StartTime=start_time,
                    EndTime=end_time,
                    Period=60,
                    Statistics=["Average", "Sum"],
                )
                for dp in sorted(resp.get("Datapoints", []), key=lambda x: x["Timestamp"]):
                    is_count_style = metric_name in (
                        "Errors", "Throttles", "Invocations", "5XXError",
                        "ThrottledRequests", "ApproximateNumberOfMessagesVisible",
                    )
                    value = dp.get("Sum") if is_count_style else dp.get("Average")
                    points.append({
                        "namespace": namespace,
                        "metric_name": metric_name,
                        "resource_name": resource["value"],
                        "value": value,
                        "unit": dp.get("Unit", ""),
                        "timestamp": dp["Timestamp"].isoformat(),
                    })
            except Exception as e:
                msg = f"Error collecting {metric_type} for {resource['value']}: {e}"
                logger.warning(msg)
                return points, msg

        return points, None

    def _detect_incidents(self, points: List[dict]) -> List[Incident]:
        """Group by resource (same as the professor's _group_metrics_by_resource),
        then analyze each resource's metrics together."""
        grouped: Dict[str, List[dict]] = {}
        for p in points:
            key = f"{p['namespace']}:{p['resource_name']}"
            grouped.setdefault(key, []).append(p)

        incidents = []
        for key, group_points in grouped.items():
            incident = self._analyze_resource(key, group_points)
            if incident:
                incidents.append(incident)
                logger.warning(f"Metric anomaly in {key}: {incident.title}")
        return incidents

    def _analyze_resource(self, resource_key: str, points: List[dict]) -> Optional[Incident]:
        namespace, resource_name = resource_key.split(":", 1)

        def values_for(metric_name):
            return [p["value"] for p in points if p["metric_name"] == metric_name and p["value"] is not None]

        anomaly = (
            self._check_throttle_anomaly(values_for("Throttles") + values_for("ThrottledRequests"))
            or self._check_error_anomaly(values_for("Errors") + values_for("5XXError"))
            or self._check_cpu_anomaly(values_for("CPUUtilization"))
            or self._check_duration_anomaly(values_for("Duration") + values_for("Latency"))
            or self._check_queue_backlog_anomaly(values_for("ApproximateNumberOfMessagesVisible"))
        )
        if not anomaly:
            return None

        resource = AWSResource(
            resource_type=namespace.replace("AWS/", "").lower(),
            resource_name=resource_name,
            region=self.region,
        )
        metric_points = [
            MetricPoint(name=p["metric_name"], value=p["value"], unit=p["unit"],
                        timestamp=p["timestamp"], resource=resource)
            for p in points
        ]

        return Incident(
            id=str(uuid.uuid4()),
            timestamp=datetime.utcnow().isoformat(),
            severity=anomaly["severity"],
            source=IncidentSource.METRICS.value,
            resource=resource,
            title=anomaly["title"],
            description=anomaly["description"],
            metrics=metric_points,
            confidence_score=anomaly["confidence"],
            detected_by="cloudwatch_metrics_collector",
        )

    def _check_throttle_anomaly(self, throttle_sums: List[float]) -> Optional[dict]:
        total = sum(throttle_sums) if throttle_sums else 0
        if total > 0:
            return {
                "severity": Severity.HIGH.value,
                "title": f"Throttled {int(total)} times",
                "description": f"{int(total)} requests were throttled",
                "confidence": 0.85,
            }
        return None

    def _check_error_anomaly(self, error_sums: List[float]) -> Optional[dict]:
        total = sum(error_sums) if error_sums else 0
        if total >= 10:
            return {
                "severity": Severity.CRITICAL.value,
                "title": f"High error count: {int(total)}",
                "description": f"{int(total)} errors reported",
                "confidence": 0.9,
            }
        elif total >= 3:
            return {
                "severity": Severity.HIGH.value,
                "title": f"Elevated errors: {int(total)}",
                "description": f"{int(total)} errors reported",
                "confidence": 0.7,
            }
        return None

    def _check_duration_anomaly(self, durations: List[float]) -> Optional[dict]:
        """Honest AWS equivalent of the professor's CPU/latency check --
        relative spike, since neither Lambda Duration nor API Gateway
        Latency has a universal fixed threshold the way CPU% does."""
        if len(durations) < 2:
            return None
        latest = durations[-1]
        avg = sum(durations) / len(durations)
        if avg > 0 and latest > avg * 2:
            return {
                "severity": Severity.MEDIUM.value,
                "title": f"Duration/latency spike: {latest:.0f}ms",
                "description": f"Latest {latest:.0f}ms vs avg {avg:.0f}ms",
                "confidence": 0.6,
            }
        return None

    def _check_cpu_anomaly(self, cpu_values: List[float]) -> Optional[dict]:
        """
        NEW -- this is now a genuine, direct match to the professor's
        _check_cpu_anomaly, same thresholds (90%/80%), because you now
        have a real EC2 instance (the LLM host) to actually measure.
        This did NOT exist before, since Lambda has no CPU to check.
        """
        if not cpu_values:
            return None
        latest = cpu_values[-1]
        avg = sum(cpu_values) / len(cpu_values)

        if latest > 90:
            return {
                "severity": Severity.HIGH.value,
                "title": f"High CPU utilization: {latest:.1f}%",
                "description": f"CPU usage at {latest:.1f}% (avg: {avg:.1f}%) on LLM host",
                "confidence": 0.8,
            }
        elif latest > 80:
            return {
                "severity": Severity.MEDIUM.value,
                "title": f"Elevated CPU utilization: {latest:.1f}%",
                "description": f"CPU usage at {latest:.1f}% (avg: {avg:.1f}%) on LLM host",
                "confidence": 0.6,
            }
        return None

    def _check_queue_backlog_anomaly(self, queue_depths: List[float]) -> Optional[dict]:
        """No GCP equivalent -- SQS-specific. A growing backlog means
        consumers can't keep up, a real signal your architecture uses
        given you already rely on SQS buffering."""
        if not queue_depths:
            return None
        latest = queue_depths[-1]
        if latest > 100:
            return {
                "severity": Severity.HIGH.value,
                "title": f"SQS backlog: {int(latest)} messages",
                "description": f"{int(latest)} messages waiting -- consumers may be falling behind",
                "confidence": 0.75,
            }
        return None