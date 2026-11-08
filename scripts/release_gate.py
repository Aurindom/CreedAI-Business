"""Offline merge gate. Run with the Python environment containing requirements-dev.

All output stays in ignored sandbox/release-gate. Never sends provider calls.
The separate production-stack canary validates actual services and provider use.
"""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
from datetime import datetime, timezone

ROOT = Path(__file__).resolve().parents[1]


def main():
    out = ROOT / 'sandbox/release-gate' / datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S')
    out.mkdir(parents=True)
    env = dict(os.environ, PYTHONDONTWRITEBYTECODE='1', PYTEST_DISABLE_PLUGIN_AUTOLOAD='1')
    for key in list(env):
        if any(part in key for part in ('OPENROUTER', 'ANTHROPIC', 'SUPABASE', 'HERMES', 'MODEL_GATEWAY', 'DISCOVERY', 'REDIS_URL', 'CHAT_')):
            env.pop(key)
    temp = out / 'tmp'
    temp.mkdir()
    env.update(TMP=str(temp), TEMP=str(temp))
    npm = shutil.which('npm.cmd' if os.name == 'nt' else 'npm')
    if not npm:
        raise RuntimeError('npm unavailable')
    jobs = [
        ('backend', [sys.executable, '-m', 'pytest', 'tests', '-q', '-p', 'no:cacheprovider',
                     '--basetemp=' + str(temp / 'pytest'), '--junitxml=' + str(out / 'backend.xml')], ROOT / 'backend'),
        ('frontend', [npm, 'test'], ROOT / 'frontend'),
        ('build', [npm, 'run', 'build', '--', '--outDir', str(out / 'frontend-dist')], ROOT / 'frontend'),
    ]
    report = {'paid_calls': 0, 'checks': []}
    for name, command, cwd in jobs:
        with (out / (name + '.log')).open('w', encoding='utf-8') as log:
            done = subprocess.run(command, cwd=cwd, env=env, stdout=log, stderr=log)
        report['checks'].append({'name': name, 'passed': done.returncode == 0})
        (out / 'result.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
        print(name + ': ' + ('PASS' if done.returncode == 0 else 'FAIL'), flush=True)
        if done.returncode:
            print('Evidence: ' + str(out))
            return 1
    print('Offline gate passed. Evidence: ' + str(out))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
