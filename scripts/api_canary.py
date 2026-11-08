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
    args = parser.parse_args()
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
            for case, text, expected in [
                ('review_replies', 'I never get around to replying to reviews', ['review_replies']),
                ('booking', 'Customers call or text to book a time and I juggle it by hand.', ['appointment_booking']),
                ('negation', 'I do not need help answering calls. I need help with bookkeeping.', ['bookkeeping']),
                ('greeting', 'Hello, how are you?', []),
            ]:
                start = time.monotonic()
                response = client.post(base + '/api/chat', json={'conversation_id': 'canary-' + uuid.uuid4().hex,
                    'message': text})
                result['paid_chat_turns'] += 1
                events = [json.loads(line[6:]) for line in response.text.splitlines() if line.startswith('data: ')]
                messages = [event for event in events if event['type'] == 'message_delta']
                tasks = [event['problem_id'] for event in events if event['type'] == 'recommendation']
                passed = bool(messages) and all(e.get('validation') == 'validated' for e in messages)
                passed = passed and set(tasks) == set(expected) and not any(e['type'] == 'error' for e in events)
                result['checks'].append({'case': case, 'http': response.status_code, 'passed': passed,
                                         'tasks': tasks, 'seconds': round(time.monotonic() - start, 2)})
                if not passed:
                    break
    result['passed'] = all(row['passed'] for row in result['checks'])
    print(json.dumps(result, indent=2))
    return 0 if result['passed'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
