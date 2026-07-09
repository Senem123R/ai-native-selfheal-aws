import json
import logging
import os
import boto3
import urllib.request
import base64

logger = logging.getLogger()
logger.setLevel(logging.INFO)

lambda_client = boto3.client('lambda', region_name='us-east-1')

# Jira config from environment variables
JIRA_URL    = os.environ.get('JIRA_URL', '')
JIRA_EMAIL  = os.environ.get('JIRA_EMAIL', '')
JIRA_TOKEN  = os.environ.get('JIRA_TOKEN', '')
JIRA_PROJECT = os.environ.get('JIRA_PROJECT', 'SHP')

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
            analysis = data.get('analysis', {})
            action   = decision.get('action', 'alert_only')
            service  = decision.get('service', '')

            logger.info(f"Executing action: {action} for {service}")

            result = execute_action(action, service, incident, analysis, decision)
            logger.info(f"Action result: {result}")

        except Exception as e:
            logger.error(f"ACT error: {str(e)}")

    return {'statusCode': 200, 'body': json.dumps({'status': 'ok'})}


def execute_action(action, service, incident, analysis, decision):
    if action == 'restart_function':
        # Restart Lambda then create Jira info ticket
        result = restart_lambda(service)
        create_jira_ticket(incident, analysis, decision, auto_fixed=True)
        return result

    elif action == 'scale_up':
        result = scale_up_lambda(service)
        create_jira_ticket(incident, analysis, decision, auto_fixed=True)
        return result

    elif action == 'alert_only':
        # Cannot auto-fix — create Jira ticket for team
        logger.info(f"Alert only — creating Jira ticket for {service}")
        return create_jira_ticket(incident, analysis, decision, auto_fixed=False)

    else:
        logger.info(f"Unknown action: {action}")
        return {'result': 'unknown_action'}


def create_jira_ticket(incident, analysis, decision, auto_fixed=False):
    """
    Creates a Jira ticket for the incident
    auto_fixed=True  → ticket says system fixed it automatically
    auto_fixed=False → ticket says team needs to investigate
    """
    if not all([JIRA_URL, JIRA_EMAIL, JIRA_TOKEN]):
        logger.warning("Jira not configured — skipping ticket creation")
        return {'result': 'jira_not_configured'}

    try:
        service   = incident.get('service_name', 'unknown')
        severity  = incident.get('severity', 'MEDIUM')
        title     = incident.get('title', 'Incident detected')
        description = incident.get('description', '')
        error_count = incident.get('error_count', 0)
        timestamp = incident.get('timestamp', '')

        root_cause  = analysis.get('root_cause', 'Unknown')
        fix_action  = analysis.get('fix_action', 'alert_only')
        confidence  = analysis.get('confidence', 0)
        explanation = analysis.get('explanation', '')

        reason = decision.get('reason', '')

        # Jira priority mapping
        priority_map = {
            'CRITICAL': 'Highest',
            'HIGH':     'High',
            'MEDIUM':   'Medium',
            'LOW':      'Low'
        }
        priority = priority_map.get(severity, 'Medium')

        # Ticket title
        if auto_fixed:
            summary = f"[AUTO-FIXED] {title} — {service}"
        else:
            summary = f"[ACTION REQUIRED] {title} — {service}"

        # Ticket description
        body = f"""
h2. Incident Details
*Service:* {service}
*Severity:* {severity}
*Errors detected:* {error_count}
*Timestamp:* {timestamp}
*Error sample:* {description}

h2. AI Analysis
*Root cause:* {root_cause}
*Recommended action:* {fix_action}
*Confidence:* {confidence}
*Explanation:* {explanation}

h2. Decision
*Action taken:* {decision.get('action')}
*Reason:* {reason}
*Auto-fixed:* {'Yes ✅' if auto_fixed else 'No — manual investigation required ⚠️'}

h2. Next Steps
{'The system automatically restarted the service. Please monitor for recurrence.' if auto_fixed else 'AI confidence was too low for auto-fix. Please investigate manually.'}

_This ticket was automatically created by the AWS Self-Healing DevOps Platform._
        """

        # Build Jira API request
        ticket_data = json.dumps({
            "fields": {
                "project":     {"key": JIRA_PROJECT},
                "summary":     summary,
                "description": body,
                "issuetype":   {"name": "Bug"},
                "priority":    {"name": priority}
            }
        }).encode('utf-8')

        # Basic auth — email:token encoded as base64
        credentials = base64.b64encode(
            f"{JIRA_EMAIL}:{JIRA_TOKEN}".encode('utf-8')
        ).decode('utf-8')

        req = urllib.request.Request(
            f"{JIRA_URL}/rest/api/2/issue",
            data=ticket_data,
            headers={
                'Content-Type':  'application/json',
                'Authorization': f'Basic {credentials}'
            },
            method='POST'
        )

        with urllib.request.urlopen(req, timeout=10) as response:
            result = json.loads(response.read().decode())
            ticket_key = result.get('key', 'unknown')
            logger.info(f"Jira ticket created: {ticket_key}")
            logger.info(f"Ticket URL: {JIRA_URL}/browse/{ticket_key}")
            return {
                'result':     'jira_ticket_created',
                'ticket_key': ticket_key,
                'ticket_url': f"{JIRA_URL}/browse/{ticket_key}"
            }

    except Exception as e:
        logger.error(f"Jira error: {str(e)}")
        return {'result': 'jira_failed', 'error': str(e)}


def restart_lambda(service):
    try:
        function_name = SERVICE_TO_FUNCTION.get(service, service)
        from datetime import datetime
        new_desc = f"Auto-restarted at {datetime.utcnow().isoformat()}"
        lambda_client.update_function_configuration(
            FunctionName=function_name,
            Description=new_desc
        )
        logger.info(f"Restarted Lambda: {function_name}")
        return {'result': 'restarted', 'function': function_name}
    except Exception as e:
        logger.error(f"Could not restart {service}: {str(e)}")
        return {'result': 'failed', 'error': str(e)}


def scale_up_lambda(service):
    try:
        function_name = SERVICE_TO_FUNCTION.get(service, service)
        lambda_client.put_function_concurrency(
            FunctionName=function_name,
            ReservedConcurrentExecutions=10
        )
        logger.info(f"Scaled up Lambda: {function_name}")
        return {'result': 'scaled_up', 'function': function_name}
    except Exception as e:
        logger.error(f"Could not scale {service}: {str(e)}")
        return {'result': 'failed', 'error': str(e)}