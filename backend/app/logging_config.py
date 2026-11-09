"""Production application events with an explicit field allowlist."""
import json
import logging


class SafeFormatter(logging.Formatter):
    def format(self, record):
        event = {'level': record.levelname, 'logger': record.name, 'event': record.getMessage()}
        for name in ('validation_status', 'validation_reason', 'stage', 'routing_reason',
                     'search_engine', 'provider_status', 'failure_type', 'http_status', 'error_code'):
            if hasattr(record, name):
                event[name] = getattr(record, name)
        return json.dumps(event)
