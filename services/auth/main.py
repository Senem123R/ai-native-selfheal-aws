import json, logging, hashlib, uuid, os
from datetime import datetime
import boto3  # boto3 = AWS version of google-cloud libraries

# DynamoDB = AWS version of Firestore (free NoSQL database)
dynamodb = boto3.resource('dynamodb', region_name='us-east-1')
table = dynamodb.Table('ecom-users')
logger = logging.getLogger()
logger.setLevel(logging.INFO)

# AWS calls this function — same as @functions_framework.http in GCP
def lambda_handler(event, context):
    path = event.get('path', '/')
    method = event.get('httpMethod', 'GET')
    body = json.loads(event.get('body') or '{}')

    if '/register' in path and method == 'POST':
        return _register(body)
    elif '/login' in path and method == 'POST':
        return _login(body)
    elif '/health' in path:
        return _resp(200, {"status": "healthy", "service": "auth"})
    return _resp(404, {"error": "not found"})

def _register(body):
    email = body.get('email')
    password = body.get('password')
    user_id = str(uuid.uuid4())
    pw_hash = hashlib.sha256(password.encode()).hexdigest()

    # Save to DynamoDB (same as Firestore in GCP)
    table.put_item(Item={
        'user_id': user_id,
        'email': email,
        'password_hash': pw_hash,
        'created_at': datetime.utcnow().isoformat()
    })
    logger.info(f"User registered: {email}")
    return _resp(201, {"user_id": user_id, "email": email})

def _login(body):
    email = body.get('email')
    password = body.get('password')
    pw_hash = hashlib.sha256(password.encode()).hexdigest()

    result = table.scan(FilterExpression='email = :e',
                        ExpressionAttributeValues={':e': email})
    for user in result.get('Items', []):
        if user['password_hash'] == pw_hash:
            return _resp(200, {"status": "ok", "user_id": user['user_id']})
    return _resp(401, {"error": "wrong email or password"})

# Helper: builds the HTTP response AWS expects
def _resp(status, body):
    return {
        'statusCode': status,
        'headers': {'Content-Type': 'application/json',
                    'Access-Control-Allow-Origin': '*'},
        'body': json.dumps(body)
    }