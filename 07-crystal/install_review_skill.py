#!/usr/bin/env python3
"""Install the self-contained review skill; public PR consent is opt-in."""
import argparse
import json
from pathlib import Path
import shutil
import sys


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--agent',choices=['codex','claude-code'],default='codex')
    parser.add_argument('--destination',help='Exact skill directory override (not its parent)')
    parser.add_argument('--enable-public-pr',action='store_true',help='Consent: future review requests may submit public reports to rfdiosuao/prize-ops')
    args=parser.parse_args(argv)
    source=Path(__file__).resolve().parents[1]/'skills/prizeops-review'
    destination=Path(args.destination).expanduser().resolve() if args.destination else Path.home()/('.codex' if args.agent=='codex' else '.claude')/'skills/prizeops-review'
    if destination.exists():
        print('Skill directory already exists; existing files and consent were not changed.',file=sys.stderr); return 1
    files=['SKILL.md','scripts/review_flow.py']
    if not all((source/name).is_file() and not (source/name).is_symlink() for name in files):
        print('Skill package is incomplete.',file=sys.stderr); return 1
    destination.mkdir(parents=True)
    for name in files:
        target=destination/name; target.parent.mkdir(parents=True,exist_ok=True)
        shutil.copyfile(source/name,target)
    if args.enable_public_pr:
        (destination/'.public-pr-consent.json').write_text(json.dumps({'version':1,'target':'rfdiosuao/prize-ops','public_pr':True}),encoding='utf-8')
    print('Installed prizeops-review. Reload your agent to discover the skill.')
    print('Public PR automatic submission: '+('ENABLED (rfdiosuao/prize-ops)' if args.enable_public_pr else 'OFF (first-use consent required)'))
    return 0


if __name__=='__main__': sys.exit(main())
