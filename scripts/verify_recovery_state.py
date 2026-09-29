import argparse
import json
import re
import subprocess


def verify_metadata(release, tag, source_sha):
    if not re.fullmatch(r'v[0-9]+\.[0-9]+\.[0-9]+', tag) or not re.fullmatch(r'[0-9a-f]{40}', source_sha):
        raise ValueError('invalid recorded tag/source')
    if not release or release.get('tag_name') != tag:
        raise ValueError('release tag does not match recorded tag')
    source_lines = [line for line in (release.get('body') or '').replace('\\n', '\n').splitlines()
                    if line.startswith('Source:')]
    expected = 'Source: https://github.com/Neburb/gen1recomp-legends/commit/' + source_sha
    if source_lines != [expected]:
        raise ValueError('release must have exactly the recorded Source line')
    if not release.get('draft'):
        raise ValueError('release must remain hidden until publication approval')


def verify_quiescent(run=subprocess.check_output):
    def api(path):
        return json.loads(run(['gh', 'api', path], text=True))
    root = 'repos/Neburb/legends/actions/workflows/publish.yml'
    if api(root)['state'] != 'disabled_manually':
        raise ValueError('disable the receiver workflow before any release write')
    page = 1
    while True:
        runs = api(f'{root}/runs?per_page=100&page={page}')['workflow_runs']
        if any(item['status'] != 'completed' for item in runs):
            raise ValueError('receiver runs remain active or queued; drain them first')
        if len(runs) < 100:
            return
        page += 1


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest='mode', required=True)
    metadata = sub.add_parser('metadata')
    metadata.add_argument('snapshot')
    metadata.add_argument('tag')
    metadata.add_argument('source_sha')
    sub.add_parser('quiescent')
    args = parser.parse_args()
    if args.mode == 'metadata':
        with open(args.snapshot, encoding='utf-8') as snapshot:
            verify_metadata(json.load(snapshot), args.tag, args.source_sha)
    else:
        verify_quiescent()
