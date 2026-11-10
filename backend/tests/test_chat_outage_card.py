"""What the owner sees when the AI cannot answer, and compound questions whose AI plan drops a part.

Every outage case must make zero model runs, say honestly why, and offer the closest catalog tasks.
"""
import pytest

from app import chat
from app.agent import readiness
from app.penny_grounding import relevant_task_ids
from conftest import account_header
from test_chat_hermes import FakeHermes, answer, frames, hermes  # noqa: F401
from test_chat_spend_meter import gateway  # noqa: F401
from test_conversation_journeys import public_reads  # noqa: F401

COFFEE = {'business_description': 'coffee shop', 'business_goal': 'attract customers'}
OLD_SENTENCE = "Arkadio's AI is unavailable right now"
FAVOURITES_REPLY = 'You have no saved favourite tools yet'


@pytest.fixture
def production(monkeypatch, hermes, gateway, public_reads):
    monkeypatch.setenv('CHAT_BUDGET_AUTHORITY', 'gateway')
    monkeypatch.setenv('CHAT_CATALOG_FAST_PATH', 'true')
    return hermes


@pytest.fixture
def down(monkeypatch):
    def set_code(code):
        async def check():
            return readiness.Readiness(False, code)
        monkeypatch.setattr(readiness, 'check', check)
    return set_code


def ask(client, message, memory=COFFEE, user=1):
    response = client.post('/api/chat', headers=account_header(user) if user else {}, json={
        'conversation_id': 'outage-card', 'message': message, 'memory': memory, 'history': [], 'ui_version': 3})
    assert response.status_code == 200
    events = frames(response)
    assert events[-1] == {'type': 'done'}
    return events


def texts(events):
    return [e['message'] for e in events if e['type'] == 'a2ui' and e.get('surface') == 'text']


def card_tasks(events):
    memories = [e['memory'] for e in events if e['type'] == 'memory']
    return memories[-1]['pending_task_ids'] if memories and memories[-1]['pending_question'] == 'task' else []


def runs(fake):
    return sum(1 for r in fake.requests if r[1] == '/v1/runs')


@pytest.mark.parametrize('code', ['hermes_unreachable', 'gateway_unreachable'])
def test_outage_offers_the_closest_tasks_and_says_why(client, production, down, code):
    fake = production(FakeHermes(answer))
    down(code)
    events = ask(client, 'how do I attract customers.')
    assert runs(fake) == 0 and not [e for e in events if e['type'] == 'error']
    assert card_tasks(events)[0] == 'email_marketing'
    note = ' '.join(texts(events))
    assert 'unavailable for a moment' in note and 'closest match' in note and 'ask again in a minute' in note
    assert OLD_SENTENCE not in note
    order = [e['type'] for e in events]
    assert order.index('a2ui') < order.index('clarify')


def test_budget_outage_says_budget_and_does_not_promise_a_minute(client, production, down):
    fake = production(FakeHermes(answer))
    down('gateway_exhausted')
    events = ask(client, 'how do I attract customers.')
    note = ' '.join(texts(events))
    assert runs(fake) == 0 and 'usage budget' in note and 'minute' not in note
    assert card_tasks(events)[0] == 'email_marketing'


def test_outage_card_for_a_guest_without_a_business_still_matches(client, production, down):
    production(FakeHermes(answer))
    down('hermes_unreachable')
    events = ask(client, 'how do I attract customers', memory={}, user=None)
    assert 'closest match' in ' '.join(texts(events))
    assert set(card_tasks(events)) & {'slow_lead_replies', 'review_requests', 'email_marketing'}


def test_ai_that_fails_to_start_gets_the_same_card_not_a_bare_error(client, production):
    fake = production(FakeHermes(answer, start_status=503))
    events = ask(client, 'how do I attract customers.')
    assert runs(fake) == 1
    assert not [e for e in events if e['type'] == 'error']
    assert card_tasks(events)[0] == 'email_marketing'
    assert 'closest match' in ' '.join(texts(events))


def test_tapping_an_outage_card_choice_needs_no_ai(client, production, down):
    fake = production(FakeHermes(answer))
    down('hermes_unreachable')
    memory = [e['memory'] for e in ask(client, 'how do I attract customers.') if e['type'] == 'memory'][-1]
    events = ask(client, 'Past customers do not come back', memory=memory)
    assert runs(fake) == 0 and not [e for e in events if e['type'] == 'error']
    assert 'email_marketing' in [e['memory'] for e in events if e['type'] == 'memory'][-1]['active_task_ids']


@pytest.mark.parametrize('code, wording', [('hermes_unreachable', 'unavailable for a moment'),
                                           ('gateway_exhausted', 'usage budget')])
def test_compound_outage_answers_the_known_part_and_offers_tasks_for_the_rest(client, production, down, code, wording):
    fake = production(FakeHermes(answer))
    down(code)
    events = ask(client, 'how do I attract customers. Do I have any favourite tools yet?')
    said = ' '.join(texts(events))
    assert runs(fake) == 0
    assert FAVOURITES_REPLY in said and 'how do I attract customers' in said and wording in said
    assert OLD_SENTENCE not in said
    assert card_tasks(events)[0] == 'email_marketing'


def test_healthy_compound_keeps_the_part_the_ai_plan_dropped(client, production):
    production(FakeHermes(answer))
    events = ask(client, 'how do I attract customers. Do I have any favourite tools yet?')
    said = texts(events)
    assert sum(FAVOURITES_REPLY in text for text in said) == 1
    assert not [e for e in events if e['type'] == 'error']


@pytest.mark.parametrize('title, task', [('Past customers do not come back', 'email_marketing'),
                                         ('The register does not do enough', 'point_of_sale'),
                                         ('Getting paid is slow', 'invoicing')])
def test_every_card_title_routes_without_ai_even_when_it_reads_as_negated(client, production, down, title, task):
    fake = production(FakeHermes(answer))
    down('hermes_unreachable')
    events = ask(client, title)
    assert runs(fake) == 0 and not [e for e in events if e['type'] == 'error']
    assert any(e['type'] == 'recommendation' and e['problem_id'] == task for e in events)


def test_healthy_compound_does_not_repeat_action_receipts(client, production):
    production(FakeHermes(answer))
    events = ask(client, 'Save Mailchimp to favourites. how do I attract customers?')
    receipts = [e for e in events if e['type'] == 'action']
    assert len(receipts) == len({repr(sorted(e.items())) for e in receipts})
    assert sum(e['type'] == 'favourites_changed' for e in events) <= 1


def test_relevance_orders_matches_first_and_reports_no_match_honestly(client):
    catalog = client.app.state.catalog
    ids, matched = relevant_task_ids(catalog, ['my customers pay late'], 'coffee_shop')
    assert ids[0] == 'invoicing' and matched
    assert relevant_task_ids(catalog, ['nobody leaves reviews'], 'coffee_shop')[0][0] == 'review_replies'
    assert relevant_task_ids(catalog, ['people leave my website'], 'coffee_shop')[1] is False
    assert relevant_task_ids(catalog, ['people leave my website'], 'plumbing')[0][0] == 'website_chat_leads'
    ids, matched = relevant_task_ids(catalog, ['hello there'], 'coffee_shop')
    assert not matched and len(ids) == 3
    ids, matched = relevant_task_ids(catalog, [''], None)
    assert not matched and len(ids) == 3
