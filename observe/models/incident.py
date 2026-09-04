"""
OBSERVE Pillar - Shared Data Models
Mirrors the professor's models.py pattern: every collector builds these same
objects, so main.py can correlate/merge/store them without caring which
collector produced them.
"""

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Dict, List, Any, Optional


class Severity(Enum):
    CRITICAL = "CRITICAL"
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"


class IncidentStatus(Enum):
    NEW = "NEW"
    ANALYZING = "ANALYZING"
    DECIDING = "DECIDING"
    REMEDIATING = "REMEDIATING"
    RESOLVED = "RESOLVED"
    FAILED = "FAILED"


class IncidentSource(Enum):
    LOGS = "logs"
    METRICS = "metrics"
    TRACE = "trace"


@dataclass
class AWSResource:
    """
    Equivalent of the professor's GCPResource.
    Every incident needs to say WHICH service it's about, in a consistent shape,
    so correlation logic can compare resource_name across collectors reliably.
    """
    resource_type: str      # e.g. "lambda"
    resource_name: str      # e.g. "ecom-payments-service"
    region: str = "us-east-1"
    labels: Dict[str, str] = field(default_factory=dict)


@dataclass
class LogEntry:
    """One raw log line, cleaned up. Professor's collector builds these;
    yours currently just keeps raw strings -- this is what upgrades that."""
    timestamp: str
    message: str
    resource: AWSResource


@dataclass
class MetricPoint:
    """One raw metric reading. New -- you have nothing like this today
    since you don't read CloudWatch Metrics at all yet."""
    name: str          # e.g. "Duration", "Errors"
    value: float
    unit: str
    timestamp: str
    resource: AWSResource


@dataclass
class TraceSpan:
    """
    One step inside a request's journey through X-Ray.
    Direct equivalent of the professor's TraceSpan -- e.g. one of
    'http-request', 'database-query', 'external-payment-gateway-call'.
    """
    trace_id: str
    span_id: str
    name: str
    start_time: str
    end_time: str
    duration_seconds: float
    error: bool
    resource: AWSResource


@dataclass
class Incident:
    """
    Central object -- every collector produces these, main.py correlates
    and stores them. This replaces the flat dict main.py currently builds
    inline, and the simpler Incident in your current incident.py.
    """
    id: str
    timestamp: str
    severity: str
    source: str                      # "logs" or "metrics" -- NEW field
    resource: AWSResource            # NEW -- structured, not just a string
    title: str
    description: str

    # evidence -- only ONE of these gets filled per collector, same as
    # the professor's pattern; main.py combines them when correlating
    logs: List[LogEntry] = field(default_factory=list)
    metrics: List[MetricPoint] = field(default_factory=list)
    traces: List[TraceSpan] = field(default_factory=list)

    error_count: int = 0
    confidence_score: float = 0.0    # NEW -- was missing entirely before
    status: str = IncidentStatus.NEW.value
    tags: Dict[str, str] = field(default_factory=dict)
    detected_by: str = ""            # NEW -- "cloudwatch_logs_collector" etc.

    # filled in later by ANALYZE/DECIDE/ACT -- not touched by OBSERVE
    root_cause: Optional[str] = None
    resolution: Optional[str] = None
    resolved_at: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        """JSON-safe conversion -- needed because DynamoDB/SNS can't take
        a raw Python object, same reason the professor's version exists."""
        return {
            "id": self.id,
            "timestamp": self.timestamp,
            "severity": self.severity,
            "source": self.source,
            "resource": {
                "resource_type": self.resource.resource_type,
                "resource_name": self.resource.resource_name,
                "region": self.resource.region,
                "labels": self.resource.labels,
            },
            "title": self.title,
            "description": self.description,
            "logs": [
                {"timestamp": l.timestamp, "message": l.message}
                for l in self.logs
            ],
            "metrics": [
                {"name": m.name, "value": m.value, "unit": m.unit, "timestamp": m.timestamp}
                for m in self.metrics
            ],
            "traces": [
                {
                    "trace_id": t.trace_id, "span_id": t.span_id, "name": t.name,
                    "start_time": t.start_time, "end_time": t.end_time,
                    "duration_seconds": t.duration_seconds, "error": t.error,
                }
                for t in self.traces
            ],
            "error_count": self.error_count,
            "confidence_score": self.confidence_score,
            "status": self.status,
            "tags": self.tags,
            "detected_by": self.detected_by,
            "root_cause": self.root_cause,
            "resolution": self.resolution,
            "resolved_at": self.resolved_at,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Incident":
        """Reverse of to_dict -- needed when main.py reads incidents back
        out of a CollectorResult, same round-trip as the professor's file."""
        resource = AWSResource(
            resource_type=data["resource"]["resource_type"],
            resource_name=data["resource"]["resource_name"],
            region=data["resource"].get("region", "us-east-1"),
            labels=data["resource"].get("labels", {}),
        )
        logs = [
            LogEntry(timestamp=l["timestamp"], message=l["message"], resource=resource)
            for l in data.get("logs", [])
        ]
        metrics = [
            MetricPoint(
                name=m["name"], value=m["value"], unit=m["unit"],
                timestamp=m["timestamp"], resource=resource
            )
            for m in data.get("metrics", [])
        ]
        traces = [
            TraceSpan(
                trace_id=t["trace_id"], span_id=t["span_id"], name=t["name"],
                start_time=t["start_time"], end_time=t["end_time"],
                duration_seconds=t["duration_seconds"], error=t.get("error", False),
                resource=resource,
            )
            for t in data.get("traces", [])
        ]
        return cls(
            id=data["id"],
            timestamp=data["timestamp"],
            severity=data["severity"],
            source=data["source"],
            resource=resource,
            title=data["title"],
            description=data["description"],
            logs=logs,
            metrics=metrics,
            traces=traces,
            error_count=data.get("error_count", 0),
            confidence_score=data.get("confidence_score", 0.0),
            status=data.get("status", IncidentStatus.NEW.value),
            tags=data.get("tags", {}),
            detected_by=data.get("detected_by", ""),
            root_cause=data.get("root_cause"),
            resolution=data.get("resolution"),
            resolved_at=data.get("resolved_at"),
        )


@dataclass
class CollectorResult:
    """
    Equivalent of the professor's CollectorResult -- every collector
    returns one of these, so main.py has a consistent way to check
    success/failure without knowing which collector ran.
    """
    collector_name: str
    success: bool
    data_count: int
    incidents_detected: int
    errors: List[str] = field(default_factory=list)
    incidents: List[Incident] = field(default_factory=list)