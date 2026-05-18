import boto3, logging, uuid
from datetime import datetime, timedelta
from ..models.incident import Incident, Severity

logger = logging.getLogger()

class CloudWatchCollector:
    def __init__(self):
        # boto3 = AWS version of google-cloud SDK
        self.client = boto3.client('logs', region_name='us-east-1')

        # These are the log groups for each Lambda function
        # AWS auto-creates these when Lambda runs
        self.log_groups = [
            '/aws/lambda/ecom-auth-service',
            '/aws/lambda/ecom-payments-service',
            '/aws/lambda/ecom-products-service',
            '/aws/lambda/ecom-orders-service',
            '/aws/lambda/ecom-cart-service',
            '/aws/lambda/ecom-tracking-service',
        ]

    def collect_and_detect(self, minutes=5):
        end_ms = int(datetime.utcnow().timestamp() * 1000)
        start_ms = int((datetime.utcnow() - timedelta(minutes=minutes)).timestamp() * 1000)

        incidents = []
        for group in self.log_groups:
            service = group.split('/')[-1]  # e.g. "ecom-payments-service"
            errors = self._get_errors(group, start_ms, end_ms)

            if errors:
                count = len(errors)
                sev = (Severity.CRITICAL if count >= 10
                       else Severity.HIGH if count >= 3
                       else Severity.MEDIUM)

                incidents.append(Incident(
                    id=str(uuid.uuid4()),
                    timestamp=datetime.utcnow().isoformat(),
                    severity=sev.value,
                    service_name=service,
                    title=f"{count} errors in {service}",
                    description=errors[0][:200],
                    error_count=count
                ))
                logger.warning(f"Incident detected in {service}: {count} errors")
        return incidents

    def _get_errors(self, log_group, start_ms, end_ms):
        try:
            # Search CloudWatch logs for ERROR messages
            resp = self.client.filter_log_events(
                logGroupName=log_group,
                startTime=start_ms,
                endTime=end_ms,
                filterPattern='ERROR'  # only grab error lines
            )
            return [e['message'] for e in resp.get('events', [])]
        except:
            return []  # log group may not exist yet — that's OK