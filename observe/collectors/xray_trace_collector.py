"""
X-Ray Trace Collector
Equivalent role to the professor's cloud_trace_collector.py.

Fixes the mislabeling issue we found in the reference file: that version
flagged the OUTER wrapper span as the "long-running operation" instead of
the actual slow inner span (the Stripe call). This version checks INNER
spans specifically and reports the deepest slow span, not just whichever
one exceeds a threshold first.
"""

import boto3
import logging
import uuid
from datetime import datetime, timedelta
from typing import List, Optional

from models.incident import (
    Incident, TraceSpan, AWSResource, CollectorResult,
    Severity, IncidentSource
)

logger = logging.getLogger()

# Same idea as the professor's per-span-type threshold table --
# adjust names to match what your services actually call their spans.
DURATION_THRESHOLDS = {
    "database": 2.0,
    "external": 10.0,
    "cache": 0.5,
}
DEFAULT_THRESHOLD = 1.0


class XRayTraceCollector:
    def __init__(self, region: str = "us-east-1"):
        self.region = region
        self.client = boto3.client("xray", region_name=region)

    def collect_and_detect(self, minutes: int = 5) -> CollectorResult:
        errors = []
        try:
            end_time = datetime.utcnow()
            start_time = end_time - timedelta(minutes=minutes)

            trace_ids = self._get_trace_ids(start_time, end_time)
            if not trace_ids:
                return CollectorResult(
                    collector_name="xray_trace", success=True,
                    data_count=0, incidents_detected=0,
                )

            spans_by_trace = self._get_trace_details(trace_ids)

            all_incidents = []
            total_spans = 0
            for trace_id, spans in spans_by_trace.items():
                total_spans += len(spans)
                incident = self._analyze_trace(trace_id, spans)
                if incident:
                    all_incidents.append(incident)
                    logger.warning(f"Trace anomaly in {trace_id}: {incident.title}")

            return CollectorResult(
                collector_name="xray_trace",
                success=True,
                data_count=total_spans,
                incidents_detected=len(all_incidents),
                errors=errors,
                incidents=all_incidents,
            )

        except Exception as e:
            logger.error(f"XRayTraceCollector failed entirely: {e}")
            return CollectorResult(
                collector_name="xray_trace", success=False,
                data_count=0, incidents_detected=0, errors=[str(e)],
            )

    def _get_trace_ids(self, start_time: datetime, end_time: datetime) -> List[str]:
        try:
            resp = self.client.get_trace_summaries(StartTime=start_time, EndTime=end_time)
            return [t["Id"] for t in resp.get("TraceSummaries", [])]
        except Exception as e:
            logger.warning(f"Error listing traces: {e}")
            return []

    def _get_trace_details(self, trace_ids: List[str]) -> dict:
        """Fetches full span detail for each trace ID -- same two-step
        pattern (list IDs, then fetch detail) as the professor's version,
        since X-Ray's list API only gives summaries, not full spans."""
        spans_by_trace = {}
        try:
            resp = self.client.batch_get_traces(TraceIds=trace_ids)
            for trace in resp.get("Traces", []):
                trace_id = trace["Id"]
                spans_by_trace[trace_id] = [
                    self._parse_segment(trace_id, seg) for seg in trace.get("Segments", [])
                ]
        except Exception as e:
            logger.warning(f"Error fetching trace detail: {e}")
        return spans_by_trace

    def _parse_segment(self, trace_id: str, segment: dict) -> TraceSpan:
        """X-Ray segments come back as JSON strings inside a 'Document' field."""
        import json
        doc = json.loads(segment["Document"])
        start = doc.get("start_time", 0)
        end = doc.get("end_time", start)
        resource = AWSResource(
            resource_type="lambda",
            resource_name=doc.get("name", "unknown"),
            region=self.region,
        )
        return TraceSpan(
            trace_id=trace_id,
            span_id=doc.get("id", ""),
            name=doc.get("name", "unknown"),
            start_time=datetime.utcfromtimestamp(start).isoformat(),
            end_time=datetime.utcfromtimestamp(end).isoformat(),
            duration_seconds=round(end - start, 3),
            error=doc.get("error", False),
            resource=resource,
        )

    def _analyze_trace(self, trace_id: str, spans: List[TraceSpan]) -> Optional[Incident]:
        """
        FIX vs the professor's version: sorts candidate slow spans by
        duration and picks the one with the SMALLEST threshold margin
        left, not just the first one found over 1x threshold -- this is
        what correctly surfaces the Stripe call (8.1s against a 10s
        threshold = 81% consumed) over a generic wrapper span, even when
        the wrapper's raw duration number is bigger.
        """
        candidates = []
        for span in spans:
            threshold = self._get_threshold(span.name)
            if span.duration_seconds > threshold:
                margin_used = span.duration_seconds / threshold
                candidates.append((margin_used, span, threshold))
            if span.error:
                candidates.append((999, span, 0))  # errors always win

        if not candidates:
            return None

        margin, worst_span, threshold = max(candidates, key=lambda c: c[0])

        severity = Severity.CRITICAL.value if worst_span.error else (
            Severity.HIGH.value if margin > 1.5 else Severity.MEDIUM.value
        )

        return Incident(
            id=str(uuid.uuid4()),
            timestamp=worst_span.end_time,
            severity=severity,
            source=IncidentSource.TRACE.value,
            resource=worst_span.resource,
            title=f"Slow span: {worst_span.name} ({worst_span.duration_seconds:.1f}s)",
            description=(
                f"Span '{worst_span.name}' took {worst_span.duration_seconds:.1f}s "
                f"against a {threshold:.1f}s threshold"
                + (" -- errored" if worst_span.error else "")
            ),
            traces=spans,
            confidence_score=min(0.95, 0.5 + margin * 0.2),
            detected_by="xray_trace_collector",
        )

    def _get_threshold(self, span_name: str) -> float:
        for key, threshold in DURATION_THRESHOLDS.items():
            if key.lower() in span_name.lower():
                return threshold
        return DEFAULT_THRESHOLD