import json, logging, os
from datetime import datetime
import boto3
from collectors.cloudwatch_collector import CloudWatchCollector

logger = logging.getLogger()
logger.setLevel(logging.INFO)

# DynamoDB stores incidents (free, replaces BigQuery)
dynamodb = boto3.resource('dynamodb', region_name='us-east-1')
table = dynamodb.Table(os.environ.get('TABLE_NAME', 'ecom-incidents'))

# SNS sends incidents to ANALYZE (replaces Pub/Sub)
sns = boto3.client('sns', region_name='us-east-1')
SNS_TOPIC = os.environ.get('SNS_TOPIC_ARN', '')

def lambda_handler(event, context):
    logger.info("OBSERVE pillar starting...")

    # Step 1: Collect errors from CloudWatch
    collector = CloudWatchCollector()
    incidents = collector.collect_and_detect(minutes=5)
    logger.info(f"Found {len(incidents)} incidents")

    # Step 2: Save each incident to DynamoDB
    for inc in incidents:
        table.put_item(Item=inc.to_dict())
        logger.info(f"Saved incident: {inc.title}")

        # Step 3: Send to ANALYZE via SNS (replaces Pub/Sub)
        if SNS_TOPIC:
            sns.publish(
                TopicArn=SNS_TOPIC,
                Message=json.dumps(inc.to_dict()),
                Subject=f"Incident: {inc.severity} in {inc.service_name}"
            )
            logger.info(f"Sent to ANALYZE: {inc.title}")

    return {
    'statusCode': 200,
    'headers': {
        'Access-Control-Allow-Origin': '*',
        'Access-Control-Allow-Headers': 'Content-Type',
        'Access-Control-Allow-Methods': 'POST,GET,OPTIONS'
    },
    'body': json.dumps({'incidents_found': len(incidents)})
}