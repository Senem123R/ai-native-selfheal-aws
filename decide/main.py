import json
import logging
import os
import boto3

logger = logging.getLogger()
logger.setLevel(logging.INFO)

sns_client = boto3.client('sns', region_name='us-east-1')
ACT_TOPIC = os.environ.get('ACT_TOPIC_ARN', '')

HEADERS = {
    'Content-Type': 'application/json',
    'Access-Control-Allow-Origin': '*'
}

# Rules for what action to take for each problem
DECISION_RULES = {
    'ecom-payments-service': {
        'timeout':     'restart_function',
        'gateway':     'restart_function',
        'ERROR':       'restart_function',
    },
    'ecom-auth-service': {
        'ERROR':       'alert_only',
    }
}

def lambda_handler(event, context):
    logger.info("DECIDE pillar running...")

    for record in event.get('Records', []):
        try:
            # Get message from SNS
            message = record.get('Sns', {}).get('Message', '{}')
            data = json.loads(message)

            incident = data.get('incident', {})
            analysis = data.get('analysis', {})

            logger.info(f"Making decision for: {incident.get('title')}")

            # Make decision
            decision = make_decision(incident, analysis)
            logger.info(f"Decision: {decision}")

            # Send to ACT pillar
            if ACT_TOPIC and decision['action'] != 'alert_only':
                sns_client.publish(
                    TopicArn=ACT_TOPIC,
                    Message=json.dumps({
                        'incident': incident,
                        'analysis': analysis,
                        'decision': decision
                    })
                )
                logger.info(f"Sent to ACT: {decision['action']}")

        except Exception as e:
            logger.error(f"DECIDE error: {str(e)}")

    return {'statusCode': 200, 'body': json.dumps({'status': 'ok'})}


def make_decision(incident, analysis):
    service = incident.get('service_name', '')
    fix_action = analysis.get('fix_action', 'alert_only')
    confidence = float(analysis.get('confidence', 0))

    # Low confidence → don't auto-fix
    if confidence < 0.7:
        logger.info(f"Confidence too low: {confidence} → alert only")
        return {
            'action': 'alert_only',
            'reason': f'confidence too low: {confidence}'
        }

    # Get rule for this service
    rules = DECISION_RULES.get(service, {})
    description = incident.get('description', '')

    # Find matching rule
    for keyword, action in rules.items():
        if keyword.lower() in description.lower():
            return {
                'action': action,
                'service': service,
                'reason': f'matched rule: {keyword}',
                'confidence': confidence
            }

    # Default based on AI recommendation
    return {
        'action': fix_action,
        'service': service,
        'reason': 'AI recommendation',
        'confidence': confidence
    }