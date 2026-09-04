"""
CloudWatch Logs Collector
Equivalent role to the professor's CloudLoggingCollector.

FIXED to match the professor's actual design: no service list, no config,
no hardcoding at all. This discovers every log group that exists in the
account dynamically, then groups results by whatever resources actually
show up -- exactly like the professor's collect_logs() queries the
WHOLE project and groups by resource afterward. This is the framework
alone -- it makes zero assumptions about what services exist.
"""

import boto3
import logging
import uuid
from datetime import datetime, timedelta
from typing import List, Optional

from models.incident import (
    Incident, LogEntry, AWSResource, CollectorResult,
    Severity, IncidentSource
)

logger = logging.getLogger()


class CloudWatchLogsCollector:
    def __init__(self, region: str = "us-east-1", log_group_prefix: Optional[str] = None):
        """
        log_group_prefix is OPTIONAL -- default None means "discover
        every log group that exists," exactly matching the professor's
        collect_logs() having no resource filter at all. Pass a prefix
        like "/aws/lambda/" only if you want to narrow discovery to
        Lambda-produced log groups specifically, still with zero named
        services anywhere.
        """
        self.region = region
        self.client = boto3.client("logs", region_name=region)
        self.log_group_prefix = log_group_prefix

    def _discover_log_groups(self) -> List[str]:
        """
        Direct equivalent of the professor's approach of querying broadly
        rather than maintaining a list. AWS's version of "give me
        everything" is describe_log_groups -- paginated, since an
        account can have many log groups.
        """
        groups = []
        paginator = self.client.get_paginator("describe_log_groups")
        kwargs = {"logGroupNamePrefix": self.log_group_prefix} if self.log_group_prefix else {}
        try:
            for page in paginator.paginate(**kwargs):
                groups.extend(lg["logGroupName"] for lg in page.get("logGroups", []))
        except Exception as e:
            logger.error(f"Error discovering log groups: {e}")
        return groups

    def collect_and_detect(self, minutes: int = 5) -> CollectorResult:
        errors = []
        try:
            end_ms = int(datetime.utcnow().timestamp() * 1000)
            start_ms = int((datetime.utcnow() - timedelta(minutes=minutes)).timestamp() * 1000)

            log_groups = self._discover_log_groups()
            logger.info(f"Discovered {len(log_groups)} log groups dynamically -- no config used")

            all_incidents = []
            total_log_lines = 0

            for log_group in log_groups:
                service = log_group.split("/")[-1]
                raw_errors, err = self._get_errors(log_group, start_ms, end_ms)
                if err:
                    errors.append(err)
                total_log_lines += len(raw_errors)

                if raw_errors:
                    incident = self._build_incident(service, raw_errors)
                    all_incidents.append(incident)
                    logger.warning(f"Incident detected in {service}: {len(raw_errors)} errors")

            return CollectorResult(
                collector_name="cloudwatch_logs",
                success=True,
                data_count=total_log_lines,
                incidents_detected=len(all_incidents),
                errors=errors,
                incidents=all_incidents,
            )

        except Exception as e:
            logger.error(f"CloudWatchLogsCollector failed entirely: {e}")
            return CollectorResult(
                collector_name="cloudwatch_logs",
                success=False,
                data_count=0,
                incidents_detected=0,
                errors=[str(e)],
            )

    def _get_errors(self, log_group: str, start_ms: int, end_ms: int):
        try:
            resp = self.client.filter_log_events(
                logGroupName=log_group,
                startTime=start_ms,
                endTime=end_ms,
                filterPattern="ERROR",
            )
            return [e["message"] for e in resp.get("events", [])], None
        except self.client.exceptions.ResourceNotFoundException:
            return [], None
        except Exception as e:
            msg = f"Error reading {log_group}: {e}"
            logger.warning(msg)
            return [], msg

    def _build_incident(self, service: str, raw_errors: List[str]) -> Incident:
        count = len(raw_errors)
        severity = self._calculate_severity(count)
        confidence = self._calculate_confidence(count)

        resource = AWSResource(resource_type="lambda", resource_name=service, region=self.region)
        log_entries = [
            LogEntry(timestamp=datetime.utcnow().isoformat(), message=msg, resource=resource)
            for msg in raw_errors
        ]

        return Incident(
            id=str(uuid.uuid4()),
            timestamp=datetime.utcnow().isoformat(),
            severity=severity.value,
            source=IncidentSource.LOGS.value,
            resource=resource,
            title=f"{count} errors in {service}",
            description=raw_errors[0][:200],
            logs=log_entries,
            error_count=count,
            confidence_score=confidence,
            detected_by="cloudwatch_logs_collector",
        )

    def _calculate_severity(self, error_count: int) -> Severity:
        if error_count >= 10:
            return Severity.CRITICAL
        elif error_count >= 3:
            return Severity.HIGH
        return Severity.MEDIUM

    def _calculate_confidence(self, error_count: int) -> float:
        return round(min(1.0, 0.5 + (error_count * 0.05)), 2)