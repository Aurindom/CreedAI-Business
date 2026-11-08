import copy
from datetime import date

import pytest

from app import auto_verification, db
from app.schemas import AutomaticReview, Capability, Fact, Tool
from app.matching import _option

URL = 'https://example.com/pricing'
FEATURE = 'Our bookkeeping software automates bookkeeping for small businesses.'
FIT = 'Our platform is built for small businesses across industries.'
PLAN = 'Core includes bookkeeping for USD 12 per month, with monthly billing.'


@pytest.fixture
def pending():
    return Tool(id='new-ledger', name='New Ledger', url='https://example.com', trades=[],
                origin='discovered', summary='Discovered',
                capabilities=[Capability(capability='bookkeeping', access=Fact(status='unknown'))])


def extraction():
    return {'feature': {'value': True, 'url': URL, 'quote': FEATURE},
            'business_fit': {'value': True, 'url': URL, 'quote': FIT},
            'plan': {'name': 'Core', 'price_usd_monthly': 12, 'billing': 'flat_monthly', 'included': True,
                     'url': URL, 'quote': PLAN}}


def test_exact_evidence_promotes_only_the_checked_task(pending, catalog):
    checked = auto_verification.evaluate(pending, 'bookkeeping', catalog, {URL: ' '.join([FEATURE, FIT, PLAN])}, extraction())
    assert checked.status == 'verified' and checked.auto_review.eligible
    assert checked.capability('bookkeeping').included_from.value == 'Core'
    assert checked.plan_prices.value == {'Core': 12}
    assert not checked.entry_monthly_usd.known  # A qualifying price is not necessarily the cheapest entry price.
    assert all(checked.auto_review.checks.values())


@pytest.mark.parametrize('mutation', ['fabricated_quote', 'external_source', 'bare_dollar', 'annual', 'per_seat', 'wrong_feature', 'negated', 'missing_fit', 'wrong_plan'])
def test_insufficient_or_misleading_evidence_never_promotes(pending, catalog, mutation):
    raw = extraction()
    page = ' '.join([FEATURE, FIT, PLAN])
    if mutation == 'fabricated_quote':
        raw['feature']['quote'] = 'A completely invented bookkeeping claim that was never fetched.'
    elif mutation == 'external_source':
        raw['plan']['url'] = 'https://reviews.example.org/pricing'
    elif mutation == 'bare_dollar':
        raw['plan']['quote'] = PLAN.replace('USD ', '$'); page = page.replace(PLAN, raw['plan']['quote'])
    elif mutation == 'annual':
        raw['plan']['quote'] = PLAN + ' Billed annually.'; page += ' Billed annually.'
    elif mutation == 'per_seat':
        raw['plan']['quote'] = PLAN + ' Per user.'; page += ' Per user.'
    elif mutation == 'wrong_feature':
        raw['plan']['quote'] = PLAN.replace('bookkeeping', 'phone answering'); page = page.replace(PLAN, raw['plan']['quote'])
    elif mutation == 'negated':
        raw['feature']['quote'] = 'Our software does not support bookkeeping for small businesses.'; page = page.replace(FEATURE, raw['feature']['quote'])
    elif mutation == 'missing_fit':
        raw['business_fit']['value'] = False
        page = page.replace(FIT, '').replace('small businesses', 'accountants')
        raw['feature']['quote'] = FEATURE.replace('small businesses', 'accountants')
    else:
        raw['plan']['name'] = 'Premium'
    checked = auto_verification.evaluate(pending, 'bookkeeping', catalog, {URL: page}, raw)
    assert checked.status == 'pending_review' and not checked.auto_review.eligible and checked.auto_review.notes


def test_verified_scope_does_not_make_other_capabilities_verified(pending, catalog):
    checked = auto_verification.evaluate(pending, 'bookkeeping', catalog, {URL: ' '.join([FEATURE, FIT, PLAN])}, extraction())
    checked.capabilities.append(Capability(capability='phone', access=Fact(status='unknown')))
    assert _option(checked, 'phone', [], 'any_business', '').status == 'pending_review'


def test_failed_recheck_demotes_previously_checked_product(pending, catalog):
    checked = auto_verification.evaluate(pending, 'bookkeeping', catalog, {URL: ' '.join([FEATURE, FIT, PLAN])}, extraction())
    raw = extraction(); raw['plan']['included'] = False
    again = auto_verification.evaluate(checked, 'bookkeeping', catalog, {URL: ' '.join([FEATURE, FIT, PLAN])}, raw)
    assert again.status == 'pending_review' and not again.auto_review.eligible


def test_qualified_auto_checked_product_can_reach_recommendation(pending, catalog):
    from app.matching import recommend
    from app.schemas import BusinessProfile
    checked = auto_verification.evaluate(pending, 'bookkeeping', catalog, {URL: ' '.join([FEATURE, FIT, PLAN])}, extraction())
    expanded = catalog.model_copy(update={'tools': [*catalog.tools, checked]})
    answer = recommend(expanded, BusinessProfile(), expanded.problem('books'))
    assert answer.winner_tool_id == checked.id


def test_audited_promotion_cannot_overwrite_a_curated_product(tmp_path, pending, catalog):
    conn = db.connect(tmp_path / 'audit.db')
    db.seed(conn, catalog)
    checked = auto_verification.evaluate(pending, 'bookkeeping', catalog, {URL: ' '.join([FEATURE, FIT, PLAN])}, extraction())
    with pytest.raises(ValueError):
        auto_verification.save(conn, checked)
    db.add_discovered_tool(conn, pending)
    auto_verification.save(conn, checked)
    assert conn.execute('SELECT count(*) FROM automatic_review_log').fetchone()[0] == 1
    assert conn.execute('SELECT status FROM tool WHERE id=?', (checked.id,)).fetchone()[0] == 'verified'
    conn.close()
