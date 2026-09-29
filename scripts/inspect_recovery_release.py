"""Read release state for recovery; only a confirmed HTTP 404 means orphan."""
import json
import re
import subprocess
import sys


def inspect(tag, run=subprocess.run):
    if not re.fullmatch(r'v\d+\.\d+\.\d+', tag):
        raise ValueError('invalid release tag')
    # Confirm authenticated repository access before interpreting absence.
    run(['gh', 'api', 'repos/Neburb/legends'], check=True, capture_output=True, text=True)
    result = run(['gh', 'api', '--include', f'repos/Neburb/legends/releases/tags/{tag}'], capture_output=True, text=True)
    statuses = re.findall(r'^HTTP/\S+ (\d{3})\b', result.stdout, re.M)
    if result.returncode:
        if statuses and statuses[-1] == '404':
            return None
        raise RuntimeError(result.stderr or result.stdout or 'release API failed')
    # gh --include prefixes the JSON with HTTP headers.
    body = re.split(r'\r?\n\r?\n', result.stdout, maxsplit=1)[-1]
    return json.loads(body)


if __name__ == '__main__':
    try:
        print(json.dumps(inspect(sys.argv[1])))
    except (ValueError, RuntimeError, subprocess.CalledProcessError, IndexError) as error:
        raise SystemExit(f'Recovery inspection failed: {error}')
