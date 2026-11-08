"""Opt-in live owner-journey evaluation; use the application's persistent spend ledger."""
import argparse
import asyncio
import json
import os
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))
from app import chat, db


async def evaluate(args):
    if not chat.chat_available():
        raise SystemExit('Configure the existing provider and spend ledger before running live checks.')
    cases = json.loads((BACKEND / 'tests/fixtures/penny_journeys.json').read_text(encoding='utf-8'))
    if args.case:
        unknown = set(args.case) - {case['id'] for case in cases}
        if unknown:
            raise SystemExit('Unknown case IDs: ' + ', '.join(sorted(unknown)))
        cases = [case for case in cases if case['id'] in args.case]
    before = chat.ledger().total()
    # This process may tighten the configured cap, never raise it or reset spend.
    cap = min(chat.ledger().cap_usd, before + args.max_additional_usd)
    os.environ['CHAT_SPEND_CAP_USD'] = str(cap)
    catalog = db.load_catalog_file(Path(os.environ.get('CATALOG_PATH', BACKEND / 'data/catalog.json')))
    results = []
    for case in cases:
        body = {key: value for key, value in case.items() if not key.startswith('expected_') and key != 'id'}
        body['conversation_id'] = 'qa-' + case['id']
        events = [event async for event in chat.run_agent(catalog, chat.ChatRequest(**body))]
        tasks = [event['problem_id'] for event in events if event['type'] == 'recommendation']
        memories = [event['memory'] for event in events if event['type'] == 'memory']
        conversation = any(event.get('response_mode') == 'conversation' for event in events)
        valid = any(event.get('validation') == 'validated' for event in events)
        errors = [event.get('code') for event in events if event['type'] == 'error']
        question = any(event['type'] == 'clarify' for event in events)
        trade = memories[-1].get('trade') if memories else None
        passed = (set(tasks) == set(case['expected_tasks']) and valid and not question and not errors
                  and (case.get('expected_mode') != 'conversation' or conversation)
                  and (not case.get('expected_trade') or trade == case['expected_trade']))
        row = dict(id=case['id'], passed=passed, tasks=tasks, validated=valid,
                   question=question, errors=errors, conversation=conversation, trade=trade)
        # Case-level evidence only: no credentials, request text or model prose.
        print(json.dumps(row), flush=True)
        results.append(row)
    report = dict(model=chat.DEFAULT_MODEL, cases=results, batch_spend_usd=chat.ledger().total()-before,
                  local_total_usd=chat.ledger().total(), cap_usd=cap)
    print(json.dumps({key: value for key, value in report.items() if key != 'cases'}))
    if args.output:
        Path(args.output).write_text(json.dumps(report, indent=2), encoding='utf-8')
    return 0 if all(row['passed'] for row in results) else 1


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--live', action='store_true', help='Explicitly enable paid model requests.')
    parser.add_argument('--max-additional-usd', type=float, required=True)
    parser.add_argument('--case', action='append', help='Run only these case IDs.')
    parser.add_argument('--output', help='Optional sanitized JSON report path.')
    args = parser.parse_args()
    if not args.live or not 0 < args.max_additional_usd <= 1:
        parser.error('Live checks require --live and a positive additional cap no greater than USD1.')
    raise SystemExit(asyncio.run(evaluate(args)))
