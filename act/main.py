import json
import logging
import os
import boto3

logger = logging.getLogger()
logger.setLevel(logging.INFO)

lambda_client = boto3.client('lambda', region_name='us-east-1')

HEADERS = {
    'Content-Type': 'application/json',
    'Access-Control-Allow-Origin': '*'
}

# Map service names to Lambda function names
SERVICE_TO_FUNCTION = {
    'ecom-payments-service': 'ecom-payments-service',
    'ecom-auth-service':     'ecom-auth-service',
}

def lambda_handler(event, context):
    logger.info("ACT pillar running...")

    for record in event.get('Records', []):
        try:
            message = record.get('Sns', {}).get('Message', '{}')
            data = json.loads(message)

            incident = data.get('incident', {})
            decision = data.get('decision', {})
            action = decision.get('action', 'alert_only')
            service = decision.get('service', '')

            logger.info(f"Executing action: {action} for {service}")

            # Execute the action
            result = execute_action(action, service, incident)
            logger.info(f"Action result: {result}")

        except Exception as e:
            logger.error(f"ACT error: {str(e)}")

    return {'statusCode': 200, 'body': json.dumps({'status': 'ok'})}


def execute_action(action, service, incident):
    if action == 'restart_function':
        return restart_lambda(service)
    elif action == 'scale_up':
        return scale_up_lambda(service)
    elif action == 'alert_only':
        logger.info(f"Alert only — no auto-fix for {service}")
        return {'result': 'alerted', 'service': service}
    else:
        logger.info(f"Unknown action: {action}")
        return {'result': 'unknown_action'}


def restart_lambda(service):
    """
    Restart a Lambda by updating its description
    This forces a cold start — effective restart
    """
    try:
        function_name = SERVICE_TO_FUNCTION.get(service, service)

        # Get current config
        current = lambda_client.get_function_configuration(
            FunctionName=function_name
        )

        # Update description to force restart
        from datetime import datetime
        new_desc = f"Auto-restarted at {datetime.utcnow().isoformat()}"

        lambda_client.update_function_configuration(
            FunctionName=function_name,
            Description=new_desc
        )

        logger.info(f"Restarted Lambda: {function_name}")
        return {
            'result': 'restarted',
            'function': function_name,
            'timestamp': datetime.utcnow().isoformat()
        }

    except Exception as e:
        logger.error(f"Could not restart {service}: {str(e)}")
        return {'result': 'failed', 'error': str(e)}


def scale_up_lambda(service):
    """
    Scale up Lambda by increasing memory and concurrency
    """
    try:
        function_name = SERVICE_TO_FUNCTION.get(service, service)

        # Increase reserved concurrency
        lambda_client.put_function_concurrency(
            FunctionName=function_name,
            ReservedConcurrentExecutions=10
        )

        logger.info(f"Scaled up Lambda: {function_name}")
        return {
            'result': 'scaled_up',
            'function': function_name,
            'concurrency': 10
        }

    except Exception as e:
        logger.error(f"Could not scale {service}: {str(e)}")
        return {'result': 'failed', 'error': str(e)}