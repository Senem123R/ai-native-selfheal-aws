"""
DynamoDB Client
Equivalent role to the professor's bigquery_client.py.

Your version doesn't need ensure_table_exists()/schema creation the way
BigQuery does -- DynamoDB tables are already declared in template.yaml
via CloudFormation, so "does the table exist" is handled at deploy time,
not at runtime. That's a real, legitimate difference between the two
databases, not a missing feature.
"""

import boto3
import logging
from typing import List, Optional
from boto3.dynamodb.conditions import Key

from models.incident import Incident

logger = logging.getLogger()


class DynamoDBClient:
    def __init__(self, table_name: str, region: str = "us-east-1"):
        self.table_name = table_name
        self.dynamodb = boto3.resource("dynamodb", region_name=region)
        self.table = self.dynamodb.Table(table_name)

    def store_incident(self, incident: Incident) -> bool:
        """Direct equivalent of the professor's store_incident."""
        try:
            self.table.put_item(Item=incident.to_dict())
            logger.info(f"Stored incident {incident.id}")
            return True
        except Exception as e:
            logger.error(f"Error storing incident {incident.id}: {e}")
            return False

    def store_incidents_batch(self, incidents: List[Incident]) -> dict:
        """
        Equivalent of store_incidents_batch -- DynamoDB's batch_writer
        does the same efficiency job as BigQuery's insert_rows_json batch
        call: fewer round trips than calling store_incident in a loop.
        NOTE: your current main.py doesn't use this yet -- same
        "built but not wired in" pattern we found in the reference code.
        """
        if not incidents:
            return {"success": 0, "failed": 0, "total": 0}

        success = 0
        failed = 0
        try:
            with self.table.batch_writer() as batch:
                for incident in incidents:
                    try:
                        batch.put_item(Item=incident.to_dict())
                        success += 1
                    except Exception as e:
                        logger.error(f"Error batching incident {incident.id}: {e}")
                        failed += 1
        except Exception as e:
            logger.error(f"Batch write failed: {e}")
            failed = len(incidents) - success

        return {"success": success, "failed": failed, "total": len(incidents)}

    def get_incident(self, incident_id: str) -> Optional[dict]:
        """Equivalent of get_incident."""
        try:
            resp = self.table.get_item(Key={"id": incident_id})
            return resp.get("Item")
        except Exception as e:
            logger.error(f"Error retrieving incident {incident_id}: {e}")
            return None

    def get_incidents_by_resource(self, resource_name: str, limit: int = 100) -> List[dict]:
        """
        Equivalent of get_incidents_by_resource.
        NOTE: this does a table.scan() with a filter, which is the
        DynamoDB equivalent of BigQuery's WHERE clause -- but scan()
        reads the WHOLE table before filtering, which gets expensive
        as incidents grow. A real fix would add a Global Secondary
        Index on resource_name -- worth doing before this table gets big,
        but out of scope for this conversion pass.
        """
        try:
            resp = self.table.scan(
                FilterExpression="resource.resource_name = :name",
                ExpressionAttributeValues={":name": resource_name},
                Limit=limit,
            )
            items = resp.get("Items", [])
            items.sort(key=lambda x: x.get("timestamp", ""), reverse=True)
            return items
        except Exception as e:
            logger.error(f"Error getting incidents for {resource_name}: {e}")
            return []