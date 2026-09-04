"""
Resource Config Loader
This is the piece that makes the whole OBSERVE pillar domain-agnostic --
the SAME collector code can watch e-commerce services, a ride-sharing
app's services, or anything else, purely by changing what's stored in
SSM Parameter Store. No code change, no redeploy needed to switch domains.
"""

import boto3
import json
import logging
from typing import List, Dict

logger = logging.getLogger()

DEFAULT_PARAM_PATH = "/self-healing-platform/monitored-resources"


class ResourceConfig:
    def __init__(self, region: str = "us-east-1", param_path: str = DEFAULT_PARAM_PATH):
        self.ssm = boto3.client("ssm", region_name=region)
        self.param_path = param_path
        self._config = None

    def load(self) -> Dict:
        """
        Fetches and caches the resource list for this deployment.
        Expected JSON shape in SSM:
        {
          "log_groups": ["/aws/lambda/svc-a", "/aws/lambda/svc-b"],
          "lambda_functions": ["svc-a", "svc-b"],
          "dynamodb_tables": ["table-a"],
          "sqs_queues": ["queue-a"],
          "api_gateway_name": "MyApi",
          "critical_services": ["svc-payments-equivalent"]
        }
        """
        if self._config is not None:
            return self._config

        try:
            resp = self.ssm.get_parameter(Name=self.param_path)
            self._config = json.loads(resp["Parameter"]["Value"])
            logger.info(f"Loaded resource config from {self.param_path}")
        except self.ssm.exceptions.ParameterNotFound:
            logger.warning(f"No config at {self.param_path} -- using empty defaults")
            self._config = self._empty_config()
        except Exception as e:
            logger.error(f"Error loading resource config: {e} -- using empty defaults")
            self._config = self._empty_config()

        return self._config

    def log_groups(self) -> List[str]:
        return self.load().get("log_groups", [])

    def lambda_functions(self) -> List[str]:
        return self.load().get("lambda_functions", [])

    def dynamodb_tables(self) -> List[str]:
        return self.load().get("dynamodb_tables", [])

    def sqs_queues(self) -> List[str]:
        return self.load().get("sqs_queues", [])

    def api_gateway_name(self) -> str:
        return self.load().get("api_gateway_name", "")

    def critical_services(self) -> List[str]:
        return self.load().get("critical_services", [])

    def _empty_config(self) -> Dict:
        return {
            "log_groups": [], "lambda_functions": [], "dynamodb_tables": [],
            "sqs_queues": [], "api_gateway_name": "", "critical_services": [],
        }