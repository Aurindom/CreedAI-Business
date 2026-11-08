import json
import logging

import pytest

from app import chat
from app.agent.evidence import build_evidence
from app.agent.grounding import default_answer, validate_answer
from app.agent.guard import LeakGuard
from app.penny_selection import selection_schema, submit_selection
from app.schemas import BusinessProfile
from test_chat import client, calls, script, send


@pytest.fixture
def package(catalog):
    return build_evidence(catalog, BusinessProfile(trade='hvac'), ['calls'])


def test_default_selection_binds_every_reference_on_the_server(package):
    selected = submit_selection({'claim_ids': []}, package, LeakGuard([]))
    baseline = validate_answer(default_answer(package), package)
    assert selected.status == 'validated'
    assert selected.text == baseline.text


@pytest.mark.parametrize('extra', [
    {'package_id': 'copied-wrong'},
    {'evidence_ids': ['invented-citation']},
    {'winner_tool_ids': ['invented-winner']},
    {'text': 'ImaginaryTool costs $999'},
])
def test_model_cannot_supply_backend_owned_fields(package, extra):
    reply = submit_selection({'claim_ids': [], **extra}, package, LeakGuard([]))
    assert reply.status == 'fallback'
    assert reply.reason == 'invalid_selection_schema'


def test_optional_selection_cannot_remove_required_uncertainty(package):
    optional = next((claim.id for claim in package.claims if claim.id not in package.required_claim_ids), None)
    reply = submit_selection({'claim_ids': [optional] if optional else []}, package, LeakGuard([]))
    assert reply.status == 'validated'
    assert set(package.required_claim_ids) <= set(reply.claim_ids)


@pytest.mark.parametrize('selection,reason', [
    ({}, 'invalid_selection_schema'),
    ({'claim_ids': ['not-in-this-package']}, 'unsupported_claim'),
    ({'claim_ids': ['calls:decision', 'calls:decision']}, 'duplicate_claim'),
    ({'claim_ids': [], 'followup_id': 'invented-followup'}, 'unsupported_followup'),
    ({'claim_ids': 'calls:decision'}, 'invalid_selection_schema'),
    ({'claim_ids': [42]}, 'invalid_selection_schema'),
])
def test_invalid_selections_have_specific_safe_reasons(package, selection, reason):
    reply = submit_selection(selection, package, LeakGuard([]))
    assert reply.status == 'fallback'
    assert reply.reason == reason
    assert 'not-in-this-package' not in reply.text


def test_provider_schema_limits_ids_to_the_active_package(package):
    schema = selection_schema(package)
    assert schema['properties']['claim_ids']['items']['enum'] == [claim.id for claim in package.claims]
    assert set(schema['properties']) == {'claim_ids', 'followup_id'}
    assert schema['additionalProperties'] is False


def test_request_specific_schema_does_not_mutate_global_tools(catalog, package):
    other = build_evidence(catalog, BusinessProfile(trade='hvac'), ['books'])
    original = json.dumps(chat.ACTIONS, sort_keys=True)

    def payload(evidence):
        return chat.model_payload([{'role': 'system', 'content': 'fixture', '_evidence_package': evidence.model_dump(mode='json')}])

    first, second = payload(package), payload(other)
    def ids(body):
        tool = next(tool for tool in body['tools'] if tool['function']['name'] == 'submit_answer')
        return tool['function']['parameters']['properties']['claim_ids']['items']['enum']

    assert ids(first) != ids(second)
    assert all('_evidence_package' not in message for body in (first, second) for message in body['messages'])
    assert original == json.dumps(chat.ACTIONS, sort_keys=True)


def test_precise_route_diagnostic_does_not_log_rejected_text(client, monkeypatch, caplog):
    secret_text = 'not-a-catalog-claim-owner-private-marker'
    script(monkeypatch, calls(('submit_answer', {'claim_ids': [secret_text]})))
    with caplog.at_level(logging.INFO, logger='app.chat'):
        events = send(client)
    records = [record for record in caplog.records if record.getMessage() == 'penny_validation']
    assert records[-1].validation_reason == 'unsupported_claim'
    assert secret_text not in repr([record.__dict__ for record in records])
    assert secret_text not in json.dumps(events)


def test_protected_value_is_intercepted_even_in_invalid_selection(package):
    canary = 'FAKE_SELECTOR_CANARY_7654321'
    guard = LeakGuard([canary])
    reply = submit_selection({'claim_ids': [canary]}, package, guard)
    assert reply.status == 'blocked'
    assert guard.tripped
    assert canary not in reply.text


def test_unknown_plan_submission_cannot_request_the_same_question_again(client, monkeypatch):
    script(monkeypatch, calls(('submit_answer', {'claim_ids': [], 'followup_id': 'plan'})))
    events = send(client, message='I need bookkeeping help but do not know my plan.',
                  profile={'trade': 'hvac', 'owned': [{'tool_id': 'quickbooks_online', 'plan': None}]})
    assert all(event.get('validation') != 'validated' for event in events if event['type'] == 'message_delta')
    assert not any(event['type'] == 'clarify' for event in events)


@pytest.mark.parametrize('mutate,reason', [
    (lambda answer: answer.update(package_id='wrong'), 'wrong_package'),
    (lambda answer: answer['claims'][0].update(evidence_ids=['forged']), 'mismatched_evidence'),
    (lambda answer: answer.update(winner_tool_ids=['invented']), 'unsupported_winner'),
    (lambda answer: answer.update(followup_id='invented'), 'unsupported_followup'),
    (lambda answer: answer.update(claims=[]), 'invalid_schema'),
])
def test_legacy_validator_reports_which_check_failed(package, mutate, reason):
    answer = default_answer(package)
    mutate(answer)
    result = validate_answer(answer, package)
    assert result.status == 'fallback'
    assert result.reason == reason
