import json
import logging
import os
import uuid
import boto3
import decimal                          # ← ADD THIS
from datetime import datetime, timedelta

logger = logging.getLogger()
logger.setLevel(logging.INFO)

REGION = 'us-east-1'
TABLE_NAME = os.environ.get('TABLE_NAME', 'ecom-incidents')
SNS_TOPIC = os.environ.get('SNS_TOPIC_ARN', '') #arn:aws:sns:us-east-1:013461378379:ecom-incidents

dynamodb = boto3.resource('dynamodb', region_name=REGION)
table = dynamodb.Table(TABLE_NAME)
sns_client = boto3.client('sns', region_name=REGION)
logs_client = boto3.client('logs', region_name=REGION)

# ── ADD THIS CLASS ──────────────────────────────────────────
class DecimalEncoder(json.JSONEncoder):
    def default(self, obj):
        if isinstance(obj, decimal.Decimal):
            return int(obj) if obj % 1 == 0 else float(obj)
        return super().default(obj)
# ────────────────────────────────────────────────────────────

HEADERS = {
    'Content-Type': 'application/json',
    'Access-Control-Allow-Origin': '*'
}

LOG_GROUPS = [
    '/aws/lambda/ecom-auth-service',
    '/aws/lambda/ecom-payments-service',
]

def lambda_handler(event, context):
    path = event.get('path', '/')
    method = event.get('httpMethod', 'GET')
    
    # Check if triggered by EventBridge (scheduled)
    source = event.get('source', '')
    detail_type = event.get('detail-type', '')
    
    logger.info(f"Triggered by: source={source}, path={path}, method={method}")

    # EventBridge scheduled trigger → run observe automatically
    if source == 'aws.events' or 'Scheduled' in detail_type:
        logger.info("EventBridge trigger → running OBSERVE automatically")
        return observe()
 
    # HTTP GET /incidents → return incidents list
    elif 'incidents' in path and method == 'GET':
        return get_incidents()

    # HTTP POST /observe → manual trigger
    elif 'observe' in path and method == 'POST':
        return observe()

    else:
        return {
            'statusCode': 200,
            'headers': HEADERS,
            'body': json.dumps({'status': 'ok', 'message': 'OBSERVE pillar'})
        }

def get_incidents():
    try:
        logger.info("Fetching incidents from DynamoDB")
        result = table.scan()
        items = result.get('Items', [])
        items.sort(key=lambda x: x.get('timestamp', ''), reverse=True)
        logger.info(f"Found {len(items)} incidents")
        return {
            'statusCode': 200,
            'headers': HEADERS,
            'body': json.dumps(           # ← USE DecimalEncoder HERE
                {'incidents': items, 'total': len(items)},
                cls=DecimalEncoder
            )
        }
    except Exception as e:
        logger.error(f"Error: {str(e)}")
        return {
            'statusCode': 500,
            'headers': HEADERS,
            'body': json.dumps({'error': str(e), 'incidents': []})
        }

def observe():
    try:
        logger.info("OBSERVE starting...")
        end_ms = int(datetime.utcnow().timestamp() * 1000)
        start_ms = int((datetime.utcnow() - timedelta(minutes=30)).timestamp() * 1000)
        incidents_created = 0

        for log_group in LOG_GROUPS:
            service = log_group.split('/')[-1]
            try:
                resp = logs_client.filter_log_events(
                    logGroupName=log_group,
                    startTime=start_ms,
                    endTime=end_ms,
                    filterPattern='ERROR'
                )
                errors = resp.get('events', [])
                if errors:
                    count = len(errors)
                    sev = 'CRITICAL' if count >= 10 else 'HIGH' if count >= 3 else 'MEDIUM'
                    incident = {
                        'id': str(uuid.uuid4()),
                        'timestamp': datetime.utcnow().isoformat(),
                        'severity': sev,
                        'service_name': service,
                        'title': f"{count} errors in {service}",
                        'description': errors[0]['message'][:200],
                        'error_count': count
                    }
                    table.put_item(Item=incident)
                    logger.info(f"Incident created: {incident['title']}")
                    if SNS_TOPIC:
                        sns_client.publish(
                            TopicArn=SNS_TOPIC,
                            Message=json.dumps(incident)
                        )
                    incidents_created += 1
            except Exception as e:
                logger.warning(f"Could not check {log_group}: {str(e)}")

        return {
            'statusCode': 200,
            'headers': HEADERS,
            'body': json.dumps({'incidents_found': incidents_created})
        }
    except Exception as e:
        logger.error(f"OBSERVE error: {str(e)}")
        return {
            'statusCode': 500,
            'headers': HEADERS,
            'body': json.dumps({'error': str(e)})
        }