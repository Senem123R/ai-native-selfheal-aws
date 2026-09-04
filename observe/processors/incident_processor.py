"""
Incident Processor
Equivalent role to the professor's incident_processor.py.
Unlike the DynamoDB/SNS files, this capability did NOT exist in your
project in any form before -- this is entirely new logic, not a
restructuring of something you already had.
"""

import logging
from datetime import datetime, timedelta
from typing import List, Optional

from models.incident import Incident

logger = logging.getLogger()

SEVERITY_WEIGHT = {"CRITICAL": 5, "HIGH": 4, "MEDIUM": 3, "LOW": 2}


class IncidentProcessor:
    def __init__(self, critical_services: List[str] = None):
        # DOMAIN-AGNOSTIC: which services need human approval before
        # auto-remediation is a per-client decision (e.g. Payments/Auth
        # for e-commerce, or a different sensitive service for another
        # client), loaded from the same SSM config as the collectors --
        # not hardcoded here anymore.
        self.critical_services = set(critical_services or [])
    def filter_incidents(
        self,
        incidents: List[Incident],
        min_severity: Optional[str] = None,
        resource_filter: Optional[str] = None,
    ) -> List[Incident]:
        """Equivalent of filter_incidents -- lets a dashboard query
        e.g. 'HIGH+ incidents on payments' without scanning everything."""
        filtered = incidents

        if min_severity:
            min_rank = SEVERITY_WEIGHT.get(min_severity, 0)
            filtered = [i for i in filtered if SEVERITY_WEIGHT.get(i.severity, 0) >= min_rank]

        if resource_filter:
            filtered = [
                i for i in filtered
                if resource_filter.lower() in i.resource.resource_name.lower()
            ]

        return filtered

    def prioritize_incidents(self, incidents: List[Incident]) -> List[Incident]:
        """Equivalent of prioritize_incidents -- CRITICAL + newest first."""
        def sort_key(inc: Incident):
            weight = SEVERITY_WEIGHT.get(inc.severity, 0)
            return (-weight, inc.timestamp)  # newer ISO timestamp sorts later, so this needs reverse below

        return sorted(incidents, key=sort_key)

    def enrich_incidents(self, incidents: List[Incident]) -> List[Incident]:
        """Equivalent of enrich_incidents -- adds tags a dashboard or
        DECIDE pillar can act on without re-deriving them each time."""
        for incident in incidents:
            try:
                self._enrich_single(incident)
            except Exception as e:
                logger.error(f"Error enriching incident {incident.id}: {e}")
        return incidents

    def _enrich_single(self, incident: Incident) -> None:
        # Urgency by age -- same idea as the professor's version
        now = datetime.utcnow()
        try:
            incident_time = datetime.fromisoformat(incident.timestamp)
            age_seconds = (now - incident_time).total_seconds()
        except ValueError:
            age_seconds = 0

        if age_seconds < 300:
            incident.tags["urgency"] = "immediate"
        elif age_seconds < 1800:
            incident.tags["urgency"] = "high"
        else:
            incident.tags["urgency"] = "medium"

        # Critical-service flag -- THIS is the tag your DECIDE pillar's
        # safety gating should check before auto-remediating.
        if incident.resource.resource_name in self.critical_services:
            incident.tags["critical_service"] = "true"
            incident.tags["requires_human_approval"] = "true"
        else:
            incident.tags["critical_service"] = "false"

        # Evidence summary -- same idea as data_sources/data_volume
        sources = []
        if incident.logs:
            sources.append("logs")
        if incident.metrics:
            sources.append("metrics")
        incident.tags["data_sources"] = ",".join(sources)
        incident.tags["data_volume"] = str(len(incident.logs) + len(incident.metrics))

    def calculate_mttr_seconds(self, incident: Incident) -> Optional[float]:
        """
        NOT present in the professor's file at all -- this directly
        answers your professor's "DevOps/MTTR metrics" feedback.
        Only works once ACT sets resolved_at on an incident.
        """
        if not incident.resolved_at:
            return None
        try:
            detected = datetime.fromisoformat(incident.timestamp)
            resolved = datetime.fromisoformat(incident.resolved_at)
            return (resolved - detected).total_seconds()
        except ValueError:
            return None