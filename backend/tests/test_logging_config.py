import json
import logging
from app.logging_config import SafeFormatter


def test_rejection_logs_have_diagnostic_codes_without_private_extras():
    record = logging.LogRecord('app.chat', logging.INFO, '', 0, 'penny_routing_rejected', (), None)
    record.stage = 'routing'
    record.routing_reason = 'context_not_affirmative'
    record.token = 'private-token'
    record.user_id = 'private-account'
    record.prompt = 'private-owner-text'
    raw = SafeFormatter().format(record)
    assert json.loads(raw)['routing_reason'] == 'context_not_affirmative'
    assert 'private-' not in raw
