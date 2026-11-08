"""Deployment API canary. Free by default; --live explicitly sends four model turns.

Run inside the backend dev environment (httpx required). Evidence is sanitized;
never pass an account token or provider key on the command line.
"""
import argparse
import json
from pathlib import Path
import sys
import time
import uuid
import httpx


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--base-url', required=True)
    parser.add_argument('--live', action='store_true')
    parser.add_argument('--edges', action='store_true', help='With --live, also check alternatives, ambiguity and vague requests (four extra turns).')
    args = parser.parse_args()
    if args.edges and not args.live:
        parser.error('--edges requires --live')
    base = args.base_url.rstrip('/')
    result = {'checks': [], 'paid_chat_turns': 0}
    with httpx.Client(timeout=120, trust_env=False) as client:
        for path, expected in [('/', 200), ('/api/health', 200), ('/api/chat/ready', 200),
                               ('/api/tools', 200), ('/.git/HEAD', 404), ('/.ssh/id_rsa', 404),
                               ('/actuator/heapdump', 404), ('/.env', 404), ('/api/plans', 401)]:
            response = client.get(base + path)
            result['checks'].append({'path': path, 'http': response.status_code, 'passed': response.status_code == expected})
        if not all(row['passed'] for row in result['checks']):
            print(json.dumps(result, indent=2))
            return 1
        if args.live:
            cases = [
                ('review_replies', 'I never get around to replying to reviews', ['review_replies']),
                ('booking', 'Customers call or text to book a time and I juggle it by hand.', ['appointment_booking']),
                ('negation', 'I do not need help answering calls. I need help with bookkeeping.', ['bookkeeping']),
                ('greeting', 'Hello, how are you?', []),
            ]
            edges = {
                'alternatives': {'message': 'Is there an alternative to that tool?',
                    'memory': {'active_task_ids': ['review_replies']},
                    'history': [{'role': 'assistant', 'text': 'Google Business Profile supports review replies.'}]},
                'call_alternatives': {'message': 'Show other tools for this job.',
                    'memory': {'active_task_ids': ['missed_calls']},
                    'history': [{'role': 'assistant', 'text': 'I showed Jobber for unanswered calls.'}]},
                'ambiguous_scheduling': {'message': 'Not that one, I mean scheduling', 'profile': {'trade': 'hvac'},
                    'memory': {'active_task_ids': ['bookkeeping']}},
                'vague_request': {'message': 'I want an AI tool'},
            }
            if args.edges:
                cases += [(name, body['message'], tasks) for (name, body), tasks in zip(edges.items(),
                          [['review_replies'], ['missed_calls'], [], []])]
            for case, text, expected in cases:
                start = time.monotonic()
                response = client.post(base + '/api/chat', json={'conversation_id': 'canary-' + uuid.uuid4().hex,
                    'message': text, **edges.get(case, {})})
                result['paid_chat_turns'] += 1
                events = [json.loads(line[6:]) for line in response.text.splitlines() if line.startswith('data: ')]
                messages = [event for event in events if event['type'] == 'message_delta']
                tasks = [event['problem_id'] for event in events if event['type'] == 'recommendation']
                passed = bool(messages) and all(e.get('validation') == 'validated' for e in messages)
                passed = passed and set(tasks) == set(expected) and not any(e['type'] == 'error' for e in events)
                if case in ('ambiguous_scheduling', 'vague_request'):
                    passed = not tasks and any(e['type'] == 'clarify' for e in events) and not any(e['type'] == 'error' for e in events)
                if case in ('alternatives', 'call_alternatives'):
                    excluded = 'google_business_profile' if case == 'alternatives' else 'jobber'
                    cards = [e['messages'][1]['updateComponents']['components'][0]['recommendation']
                             for e in events if e.get('surface') == 'recommendation']
                    passed = passed and bool(cards) and all(excluded not in [o['tool_id'] for o in c['options'] + c['check_first']] for c in cards)
                    passed = passed and 'Looking for alternatives to' in ''.join(e['text'] for e in messages)
                passed = passed and response.status_code == 200
                result['checks'].append({'case': case, 'http': response.status_code, 'passed': passed,
                                         'tasks': tasks, 'seconds': round(time.monotonic() - start, 2)})
                if not passed:
                    break
    result['passed'] = all(row['passed'] for row in result['checks'])
    print(json.dumps(result, indent=2))
    return 0 if result['passed'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
