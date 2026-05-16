import json, logging, uuid, random, time, os
from datetime import datetime
import boto3

dynamodb = boto3.resource('dynamodb', region_name='us-east-1')
table = dynamodb.Table('ecom-payments')
logger = logging.getLogger()
logger.setLevel(logging.INFO)

def lambda_handler(event, context):
    path = event.get('path', '/')
    body = json.loads(event.get('body') or '{}')

    if '/pay' in path:
        return _process(body)
    elif '/health' in path:
        return _resp(200, {"status": "healthy"})
    return _resp(404, {"error": "not found"})

def _process(body):
    amount = body.get('amount', 0)

    # FAKE FAILURES — these create CloudWatch errors
    # which OBSERVE will detect and trigger self-healing
    if random.random() < 0.05:
        logger.error("CRITICAL: Payment gateway timeout — connection refused")
        time.sleep(5)
        return _resp(504, {"error": "gateway timeout"})

    if random.random() < 0.10:
        logger.warning("Payment declined by issuing bank")
        return _resp(402, {"status": "declined"})

    # Success path
    txn_id = str(uuid.uuid4())
    table.put_item(Item={
        'txn_id': txn_id,
        'amount': str(amount),
        'status': 'approved',
        'timestamp': datetime.utcnow().isoformat()
    })
    logger.info(f"Payment approved: {txn_id}")
    return _resp(200, {"status": "approved", "txn_id": txn_id})

def _resp(status, body):
    return {'statusCode': status,
            'headers': {'Content-Type': 'application/json', 'Access-Control-Allow-Origin': '*'},
            'body': json.dumps(body)}