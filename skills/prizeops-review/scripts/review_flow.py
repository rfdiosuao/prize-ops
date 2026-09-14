#!/usr/bin/env python3
"""Local evidence inventory and report-only GitHub publication via existing gh login."""
import argparse
import base64
import hashlib
import json
import os
import pathlib
import re
import subprocess
import sys
import time
from urllib.parse import quote, urlencode

UPSTREAM = 'rfdiosuao/prize-ops'
CONSENT = pathlib.Path(__file__).resolve().parents[1] / '.public-pr-consent.json'
MARKER = '<!-- prizeops-review:v1 -->\n'
SECRET_PATTERNS = [
    r'\bsk-[A-Za-z0-9_-]{16,}', r'\bgh[opurs]_[A-Za-z0-9]{20,}',
    r'\bgithub_pat_[A-Za-z0-9_]+', r'\bAKIA[A-Z0-9]{16}\b',
    r'-----BEGIN [A-Z ]*PRIVATE KEY-----',
    r'''(?i)\b(?:api[_-]?key|access[_-]?token|password|secret|authorization|cookie)\b["']?\s*[=:]\s*\S+''',
    r'(?i)[?&](?:token|key|secret|signature|auth|code)=[^\s&)]+',
    r'https?://[^\s/]+:[^\s/]+@',
    r'(?i)\b[A-Z]:[\\/]', r'/(?:home|Users|root)/\S+',
    r'\b[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}\b', r'(?<!\d)1[3-9]\d{9}(?!\d)',
    r'\b(?:10\.\d+|192\.168|127\.\d+|172\.(?:1[6-9]|2\d|3[01]))\.\d+\.\d+\b',
]


class ApiError(RuntimeError):
    def __init__(self, status=0):
        self.status = status
        super().__init__('GitHub request failed (HTTP %s); check login/permissions/network.' % status)


def command(args, cwd=None, stdin=None, timeout=60):
    # No shell, credentials, git config mutation or raw command/error logging.
    return subprocess.run(args, cwd=cwd, input=stdin, capture_output=True,
                          encoding='utf-8', errors='replace', timeout=timeout)


def gh_api(method, path, data=None):
    args = ['gh', 'api', '--hostname', 'github.com', '--method', method, path]
    if data is not None:
        args += ['--input', '-']
    result = command(args, stdin=json.dumps(data) if data is not None else None)
    if result.returncode:
        match = re.search(r'HTTP (\d{3})', result.stderr)
        raise ApiError(int(match.group(1)) if match else 0)
    return json.loads(result.stdout) if result.stdout.strip() else {}


def check_report(text):
    if not 100 <= len(text.encode('utf-8')) <= 100000:
        raise ValueError('Report must be 100–100000 UTF-8 bytes.')
    if not re.search(r'^#\s+\S', text, re.M):
        raise ValueError('Report needs a title.')
    # Block known secrets without echoing matches. Human/agent review is still needed.
    if any(re.search(pattern, text) for pattern in SECRET_PATTERNS):
        raise ValueError('Report contains possible credentials or private information; redact before publication.')
    without_marker = text.replace(MARKER, '')
    if re.search(r'<[^>]+>|!\[', without_marker):
        raise ValueError('Publish text and links only; HTML and embedded images are not allowed.')


def collect(project):
    root = pathlib.Path(project).resolve()
    result = command(['git', 'rev-parse', '--show-toplevel'], cwd=root)
    if result.returncode or pathlib.Path(result.stdout.strip()).resolve() != root:
        raise ValueError('Select the Git project root explicitly.')
    # Inventory only: no source bodies, untracked files, remote URLs, authors or emails.
    files = command(['git', 'ls-files', '-z'], cwd=root)
    if files.returncode: raise ValueError('Cannot inspect tracked files.')
    candidates = []
    for name in files.stdout.split('\0'):
        p = pathlib.PurePosixPath(name)
        if not name or any(part.startswith('.') for part in p.parts): continue
        if p.suffix.lower() != '.md' or re.search(r'(?i)secret|private|credential|chat|聊天|问卷|原始|config', name): continue
        local = root / name
        if local.is_symlink() or not local.is_file(): continue
        try: local.resolve().relative_to(root)
        except ValueError: continue
        if any(re.search(pattern, name) for pattern in SECRET_PATTERNS): continue
        candidates.append(name)
    history = command(['git', 'log', '-60', '--format=%h%x09%cs%x09%s'], cwd=root)
    lines = []
    for line in history.stdout.splitlines():
        if any(re.search(pattern, line) for pattern in SECRET_PATTERNS):
            parts = line.split('\t')
            line = '\t'.join(parts[:2] + ['[sensitive subject omitted]'])
        lines.append(line)
    dirty = command(['git', 'status', '--porcelain'], cwd=root)
    identity = hashlib.sha256(str(root).encode()).hexdigest()[:12]
    return {'suggested_id': 'project-' + identity, 'tracked_markdown_candidates': candidates[:100],
            'recent_commits': lines, 'has_uncommitted_changes': bool(dirty.stdout.strip()),
            'limits': 'Local inventory only. No chat history or document bodies collected; missing history is unknown. Review candidate documents selectively, excluding personal/raw records.'}


def publish_report(text, review_id, api=gh_api):
    check_report(text)
    if not re.fullmatch(r'[a-z0-9][a-z0-9-]{0,59}', review_id):
        raise ValueError('ID must be a stable lowercase slug (1–60 characters).')
    login = api('GET', 'user')['login']
    if not re.fullmatch(r'[A-Za-z0-9-]+', login): raise ValueError('Unexpected account name.')
    base = api('GET', 'repos/' + UPSTREAM)['default_branch']
    owner = UPSTREAM.split('/')[0]
    if login.lower() == owner.lower():
        fork = UPSTREAM
    else:
        fork = api('POST', 'repos/' + UPSTREAM + '/forks', {})['full_name']
        if fork.split('/')[0].lower() != login.lower(): raise ValueError('Fork ownership mismatch.')
        for attempt in range(4):
            try:
                metadata = api('GET', 'repos/' + fork)
                break
            except ApiError as error:
                if error.status != 404 or attempt == 3: raise
                time.sleep(1)
        if not metadata.get('fork') or metadata.get('parent', {}).get('full_name', '').lower() != UPSTREAM.lower():
            raise ValueError('Existing repository is not a fork of PrizeOps; nothing was overwritten.')
    branch = 'review/prizeops-' + login.lower() + '-' + review_id
    query = urlencode({'state': 'all', 'head': login + ':' + branch, 'base': base, 'per_page': 100})
    prs = api('GET', 'repos/' + UPSTREAM + '/pulls?' + query)
    opened = next((pr for pr in prs if pr['state'] == 'open'), None)
    if prs and not opened:
        raise ValueError('This review PR is closed/merged. Use a new ID for a new review; it will not be reopened.')
    ref = 'repos/' + fork + '/git/ref/heads/' + quote(branch, safe='/')
    filename = 'reviews/' + login.lower() + '-' + review_id + '.md'
    def check_branch_scope():
        comparison = api('GET', 'repos/' + UPSTREAM + '/compare/' + quote(base, safe='') + '...' + quote(login + ':' + branch, safe=':'))
        files = comparison.get('files')
        if not isinstance(files, list) or any(item.get('filename') != filename or item.get('previous_filename', filename) != filename for item in files):
            raise ValueError('Review branch contains unrelated changes; nothing else will be uploaded. Use a fresh review ID.')
    try:
        api('GET', ref)
        check_branch_scope()
    except ApiError as error:
        if error.status != 404: raise
        sha = api('GET', 'repos/' + UPSTREAM + '/git/ref/heads/' + quote(base, safe='/'))['object']['sha']
        api('POST', 'repos/' + fork + '/git/refs', {'ref': 'refs/heads/' + branch, 'sha': sha})
    path = 'repos/' + fork + '/contents/' + filename
    document = MARKER + (text[len(MARKER):] if text.startswith(MARKER) else text)
    encoded = base64.b64encode(document.encode()).decode()
    data = {'message': 'docs: update project retrospective ' + review_id, 'branch': branch, 'content': encoded}
    unchanged = False
    try:
        existing = api('GET', path + '?' + urlencode({'ref': branch}))
        old = base64.b64decode(existing['content']).decode('utf-8')
        if not old.startswith(MARKER): raise ValueError('Existing file is not tool-owned; refusing to overwrite.')
        data['sha'] = existing['sha']
        unchanged = old == document
    except ApiError as error:
        if error.status != 404: raise
    if not unchanged: api('PUT', path, data)
    check_branch_scope()
    if opened: return opened['html_url']
    pr = api('POST', 'repos/' + UPSTREAM + '/pulls', {
        'title': '项目全流程复盘：' + review_id, 'head': login + ':' + branch, 'base': base,
        'body': '通过 PrizeOps 复盘入口提交。仅包含整理后的复盘 Markdown；结果、证据与缺口见正文。未上传项目源码或原始聊天。',
        'maintainer_can_modify': True})
    return pr['html_url']


def has_consent():
    try:
        data = json.loads(CONSENT.read_text(encoding='utf-8'))
        return data == {'version': 1, 'target': UPSTREAM, 'public_pr': True}
    except (OSError, ValueError): return False


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='mode', required=True)
    c = sub.add_parser('collect'); c.add_argument('--project', required=True)
    sub.add_parser('status')
    consent = sub.add_parser('consent')
    consent.add_argument('--enable-public-pr', action='store_true')
    consent.add_argument('--revoke', action='store_true')
    p = sub.add_parser('publish')
    p.add_argument('--report', required=True); p.add_argument('--id', required=True)
    p.add_argument('--allow-public-pr', action='store_true', help='Explicit approval for this invocation only')
    p.add_argument('--dry-run', action='store_true')
    args = parser.parse_args(argv)
    try:
        if args.mode == 'collect':
            print(json.dumps(collect(args.project), ensure_ascii=False, indent=2)); return 0
        if args.mode == 'consent':
            if args.revoke:
                CONSENT.unlink(missing_ok=True); print('Automatic public submission disabled.'); return 0
            if not args.enable_public_pr: raise ValueError('Use --enable-public-pr only after explaining the public destination to the user.')
            CONSENT.write_text(json.dumps({'version': 1, 'target': UPSTREAM, 'public_pr': True}), encoding='utf-8')
            print('Enabled: future project review requests may submit a public PR to ' + UPSTREAM); return 0
        if args.mode == 'status':
            auth = command(['gh', 'auth', 'status', '--hostname', 'github.com'])
            print(json.dumps({'github_authenticated': auth.returncode == 0, 'automatic_public_pr': has_consent(), 'target': UPSTREAM})); return 0
        text = pathlib.Path(args.report).read_text(encoding='utf-8')
        check_report(text)
        if args.dry_run:
            print('Report scan passed; no network requests or uploads.'); return 0
        if not (args.allow_public_pr or has_consent()):
            print('Local report retained. Public submission requires first-use consent to ' + UPSTREAM); return 2
        auth = command(['gh', 'auth', 'status', '--hostname', 'github.com'])
        if auth.returncode:
            print('Local report retained. Run: gh auth login --hostname github.com'); return 3
        url = publish_report(text, args.id)
        print(json.dumps({'status': 'submitted', 'url': url}, ensure_ascii=False)); return 0
    except (ValueError, OSError, subprocess.TimeoutExpired, ApiError, KeyError) as error:
        # Never print subprocess stderr or arbitrary API payloads (may contain credentials).
        message = str(error) if isinstance(error, (ValueError, ApiError)) else 'Missing dependency, unreadable file or unexpected response; local report retained.'
        print(message, file=sys.stderr); return 1


if __name__ == '__main__': sys.exit(main())
