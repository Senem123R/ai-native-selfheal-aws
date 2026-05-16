import json
import logging

logger = logging.getLogger()
logger.setLevel(logging.INFO)

def lambda_handler(event, context):
    logger.info("OBSERVE pillar running...")
    return {
        'statusCode': 200,
        'body': json.dumps({'incidents_found': 0, 'status': 'ok'})
    }