from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum

class Severity(Enum):
    CRITICAL = "CRITICAL"
    HIGH     = "HIGH"
    MEDIUM   = "MEDIUM"
    LOW      = "LOW"

@dataclass
class Incident:
    id: str
    timestamp: str
    severity: str
    service_name: str
    title: str
    description: str
    error_count: int = 0

    def to_dict(self):
        return {
            'id': self.id,
            'timestamp': self.timestamp,
            'severity': self.severity,
            'service_name': self.service_name,
            'title': self.title,
            'description': self.description,
            'error_count': self.error_count
        }