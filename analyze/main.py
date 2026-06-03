import json
import logging
import os
import urllib.request

logger = logging.getLogger()
logger.setLevel(logging.INFO)

sns_client = boto3.client('sns', region_name='us-east-1')
DECIDE_TOPIC = os.environ.get('DECIDE_TOPIC_ARN', '')
OPENROUTER_KEY = os.environ.get('OPENROUTER_KEY', '')
OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"

def lambda_handler(event, context):
    logger.info("ANALYZE pillar running...")
    for record in event.get('Records', []):
        message = record.get('Sns', {}).get('Message', '{}')
        incident = json.loads(message)
        logger.info(f"Analyzing incident: {incident.get('title')}")
        analysis = ask_ai(incident)
        logger.info(f"Analysis result: {json.dumps(analysis)}")

        if DECIDE_TOPIC:
            sns_client.publish(
                TopicArn=DECIDE_TOPIC,
                Message=json.dumps({
                    'incident': incident,
                    'analysis': analysis
                })
            )
            logger.info("Sent to DECIDE pillar")
        else:
            logger.warning("DECIDE_TOPIC not set — not sending to DECIDE")

    return {'statusCode': 200, 'body': json.dumps({'status': 'ok'})}

def ask_ai(incident):
    prompt = f"""You are an AWS SRE analyzing an e-commerce incident.

Service: {incident.get('service_name')}
Severity: {incident.get('severity')}
Problem: {incident.get('title')}
Details: {incident.get('description')}
Error count: {incident.get('error_count')}

Reply ONLY with valid JSON no markdown:
{{
  "root_cause": "one sentence why this happened",
  "fix_action": "restart OR scale_up OR alert_only",
  "confidence": 0.85,
  "explanation": "plain English for the team"
}}"""

    body = json.dumps({
        "model": "meta-llama/llama-3.2-3b-instruct:free",
        "messages": [{"role": "user", "content": prompt}]
    }).encode('utf-8')

    try:
        req = urllib.request.Request(
            OPENROUTER_URL,
            data=body,
            headers={
                'Content-Type': 'application/json',
                'Authorization': f'Bearer {OPENROUTER_KEY}',
                'HTTP-Referer': 'https://github.com',
                'X-Title': 'EcomSelfHeal'
            },
            method='POST'
        )
        with urllib.request.urlopen(req, timeout=10) as response:
            result = json.loads(response.read().decode())
            text = result['choices'][0]['message']['content'].strip()
            logger.info(f"AI response: {text}")
            try:
                clean = text.replace('```json','').replace('```','').strip()
                return json.loads(clean)
            except:
                return {
                    "root_cause": text,
                    "fix_action": "alert_only",
                    "confidence": 0.5,
                    "explanation": "parsed from text"
                }
    except Exception as e:
        logger.error(f"AI API error: {str(e)}")
        return {
            "root_cause": "Could not analyze",
            "fix_action": "alert_only",
            "confidence": 0.0,
            "explanation": str(e)
        }