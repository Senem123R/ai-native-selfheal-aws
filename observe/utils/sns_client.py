"""
SNS Client
Equivalent role to the professor's eventarc_client.py -- SNS is your
Pub/Sub, same underlying mechanism the reference file actually used
(remember: their "EventarcClient" was really a Pub/Sub publisher too).

Your architecture is actually SIMPLER and arguably cleaner here: you have
one topic per pillar transition already declared in template.yaml
(IncidentTopic -> AnalyzeFunction, DecideTopic -> DecideFunction, etc.),
wired via SNS-trigger Events blocks. The professor's version manually
picks a topic by name string at publish time; yours lets each Lambda's
own SNS trigger declare which topic it listens to. Same job, different
(equally valid) way of doing it.
"""

import json
import logging
import boto3

from models.incident import Incident

logger = logging.getLogger()


class SNSClient:
    def __init__(self, topic_arn: str):
        self.topic_arn = topic_arn
        self.client = boto3.client("sns")

    def publish_incident(self, incident: Incident) -> bool:
        """Direct equivalent of publish_incident_event -- but you don't
        need a target_pillar argument, since your topic_arn IS the target
        (IncidentTopic vs DecideTopic vs ActTopic), matching your
        template.yaml's one-topic-per-transition design."""
        try:
            message_attributes = {
                "severity": {"DataType": "String", "StringValue": incident.severity},
                "resource_name": {"DataType": "String", "StringValue": incident.resource.resource_name},
                "confidence_score": {"DataType": "Number", "StringValue": str(incident.confidence_score)},
            }
            resp = self.client.publish(
                TopicArn=self.topic_arn,
                Message=json.dumps(incident.to_dict()),
                MessageAttributes=message_attributes,
            )
            logger.info(f"Published incident {incident.id} (message: {resp['MessageId']})")
            return True
        except Exception as e:
            logger.error(f"Error publishing incident {incident.id}: {e}")
            return False

    def publish_batch(self, incidents: list) -> dict:
        """Equivalent of publish_batch_incidents."""
        success, failed = 0, 0
        for incident in incidents:
            if self.publish_incident(incident):
                success += 1
            else:
                failed += 1
        return {"success": success, "failed": failed, "total": len(incidents)}