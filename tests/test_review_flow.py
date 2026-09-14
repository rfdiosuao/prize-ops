import importlib.util
import json
import pathlib
import tempfile
import subprocess
import sys
from unittest.mock import patch
import unittest

SCRIPT = pathlib.Path(__file__).resolve().parents[1] / 'skills/prizeops-review/scripts/review_flow.py'


def load():
    if not SCRIPT.exists():
        return None
    spec = importlib.util.spec_from_file_location('review_flow', SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


REPORT = '''# 示例项目复盘
## 目标与结果
已完成原型，赛事结果未记录。
## 全流程
需求、设计、开发、测试、部署、路演均按已有记录整理，缺失处明确标注未记录。
## 做对的事
先做最小演示再收集反馈，证据见提交记录。
## 问题与改进
缺少独立设备验证，下次在发布前补齐。
## 证据与缺口
只看到当前仓库；没有评委反馈，不推断获奖原因。
'''


class FlowTests(unittest.TestCase):
    def setUp(self):
        self.m = load()
        self.assertIsNotNone(self.m, 'review flow implementation is missing')

    def test_report_rejects_secrets_private_paths_and_active_markup(self):
        self.m.check_report(REPORT)
        for suffix in ['\nsk-' + 'a'*32, '\n-----BEGIN PRIVATE KEY-----', '\npassword=abc123', '\n{"api_key": "vendor-secret"}', '\nhttps://x.test/?token=secret', '\nD:\\private\\notes.txt', '\n/home/alice/notes', '\n![tracking](https://x.test/pixel)', '\n<img src=x>', '\na@example.com', '\n192.168.1.7']:
            with self.subTest(suffix=suffix[:18]):
                with self.assertRaises(ValueError):
                    self.m.check_report(REPORT + suffix)

    def test_publish_uses_fork_and_only_one_report_then_updates_existing_pr(self):
        calls = []
        state = {'branch': False, 'file': None, 'pr': []}

        def api(method, path, data=None):
            calls.append((method, path, data))
            if path == 'user': return {'login': 'alice'}
            if path == 'repos/rfdiosuao/prize-ops': return {'default_branch': 'main'}
            if path == 'repos/rfdiosuao/prize-ops/forks': return {'full_name': 'alice/prize-ops'}
            if path == 'repos/alice/prize-ops': return {'fork': True, 'parent': {'full_name': 'rfdiosuao/prize-ops'}}
            if '/pulls?' in path: return state['pr']
            if '/compare/' in path: return {'files': [] if state['file'] is None else [{'filename':'reviews/alice-demo-123.md'}]}
            if path == 'repos/rfdiosuao/prize-ops/git/ref/heads/main': return {'object': {'sha': 'base123'}}
            if '/git/ref/heads/' in path:
                if not state['branch']: raise self.m.ApiError(404)
                return {'object': {'sha': 'branch123'}}
            if path.endswith('/git/refs'):
                state['branch'] = True
                return {}
            if '/contents/reviews/' in path:
                if method == 'GET':
                    if state['file'] is None: raise self.m.ApiError(404)
                    return {'sha': 'file123', 'content': state['file']}
                state['file'] = data['content']
                return {}
            if path == 'repos/rfdiosuao/prize-ops/pulls':
                state['pr'] = [{'state': 'open', 'number': 8, 'html_url': 'https://github.com/rfdiosuao/prize-ops/pull/8'}]
                return state['pr'][0]
            raise AssertionError((method, path))

        first = self.m.publish_report(REPORT, 'demo-123', api=api)
        second = self.m.publish_report(REPORT + '\n补充：完成实机验证。', 'demo-123', api=api)
        third = self.m.publish_report(REPORT + '\n补充：完成实机验证。', 'demo-123', api=api)
        self.assertEqual(first, second)
        self.assertEqual(second, third)
        self.assertEqual(sum(method == 'POST' and path.endswith('/pulls') for method,path,_ in calls), 1)
        writes = [(path, data) for method,path,data in calls if method == 'PUT']
        self.assertEqual(len(writes), 2)
        self.assertTrue(all(path == 'repos/alice/prize-ops/contents/reviews/alice-demo-123.md' for path,_ in writes))
        self.assertEqual(writes[-1][1]['sha'], 'file123')

    def test_unsafe_report_never_reaches_github(self):
        with self.assertRaises(ValueError):
            self.m.publish_report(REPORT + '\nsk-' + 'b'*32, 'demo', api=lambda *args: self.fail('network before scan'))

    def test_existing_unrelated_fork_is_not_modified(self):
        def api(method,path,data=None):
            if path=='user': return {'login':'alice'}
            if path=='repos/rfdiosuao/prize-ops': return {'default_branch':'main'}
            if path.endswith('/forks'): return {'full_name':'alice/prize-ops'}
            if path=='repos/alice/prize-ops': return {'fork':False}
            self.fail('must not write to an unrelated repository')
        with self.assertRaises(ValueError): self.m.publish_report(REPORT,'demo',api=api)

    def test_closed_pr_is_not_reopened_or_written(self):
        def api(method,path,data=None):
            if path=='user': return {'login':'rfdiosuao'}
            if path=='repos/rfdiosuao/prize-ops': return {'default_branch':'main'}
            if '/pulls?' in path: return [{'state':'closed','html_url':'https://github.com/rfdiosuao/prize-ops/pull/9'}]
            self.fail('closed PR must not lead to writes')
        with self.assertRaises(ValueError): self.m.publish_report(REPORT,'demo',api=api)

    def test_existing_branch_with_other_files_is_never_published(self):
        def api(method,path,data=None):
            if path=='user': return {'login':'rfdiosuao'}
            if path=='repos/rfdiosuao/prize-ops': return {'default_branch':'main'}
            if '/pulls?' in path: return []
            if '/git/ref/heads/' in path: return {'object':{'sha':'existing'}}
            if '/compare/' in path: return {'files':[{'filename':'private-source.txt'}]}
            self.fail('unrelated branch must not be written or published')
        with self.assertRaises(ValueError): self.m.publish_report(REPORT,'demo',api=api)

    def test_dry_run_never_checks_auth_or_publishes(self):
        with tempfile.TemporaryDirectory() as directory:
            report=pathlib.Path(directory)/'report.md'; report.write_text(REPORT,encoding='utf-8')
            with patch.object(self.m,'command',side_effect=AssertionError('no commands allowed')):
                self.assertEqual(self.m.main(['publish','--report',str(report),'--id','demo','--dry-run']),0)

    def test_explicit_consent_is_required_for_publication(self):
        with tempfile.TemporaryDirectory() as directory:
            report=pathlib.Path(directory)/'review.md'
            report.write_text(REPORT,encoding='utf-8')
            self.assertEqual(self.m.main(['publish','--report',str(report),'--id','demo']),2)

    def test_unauthenticated_keeps_report_without_api_calls(self):
        with tempfile.TemporaryDirectory() as directory:
            report=pathlib.Path(directory)/'review.md'
            report.write_text(REPORT,encoding='utf-8')
            with patch.object(self.m,'command',return_value=subprocess.CompletedProcess([],1,'','')), patch.object(self.m,'gh_api',side_effect=AssertionError('unexpected network')):
                self.assertEqual(self.m.main(['publish','--report',str(report),'--id','demo','--allow-public-pr']),3)
            self.assertEqual(report.read_text(encoding='utf-8'),REPORT)

    def test_collect_only_lists_safe_tracked_docs_and_no_untracked_or_bodies(self):
        with tempfile.TemporaryDirectory() as directory:
            root=pathlib.Path(directory)
            subprocess.run(['git','init',directory],check=True,capture_output=True)
            for name in ['README.md','notes.md','.env','private-chat.md','untracked.md']:
                (root/name).write_text('private document body sk-'+'x'*32,encoding='utf-8')
            subprocess.run(['git','-C',directory,'add','README.md','notes.md','.env','private-chat.md'],check=True)
            before=subprocess.check_output(['git','-C',directory,'status','--porcelain'])
            result=self.m.collect(directory)
            self.assertEqual(result['tracked_markdown_candidates'],['README.md','notes.md'])
            self.assertNotIn('private document body',json.dumps(result))
            self.assertNotIn(directory,json.dumps(result))
            self.assertEqual(before,subprocess.check_output(['git','-C',directory,'status','--porcelain']))

    def test_installer_copies_self_contained_skill_and_requires_explicit_consent(self):
        installer=SCRIPT.parents[3]/'07-crystal/install_review_skill.py'
        self.assertTrue(installer.is_file(),'installer missing')
        with tempfile.TemporaryDirectory() as directory:
            dest=pathlib.Path(directory)/'installed'
            run=subprocess.run([sys.executable,str(installer),'--destination',str(dest)],capture_output=True,text=True)
            self.assertEqual(run.returncode,0,run.stderr)
            self.assertTrue((dest/'SKILL.md').is_file())
            self.assertTrue((dest/'scripts/review_flow.py').is_file())
            self.assertFalse((dest/'.public-pr-consent.json').exists())
            (dest/'custom.txt').write_text('keep',encoding='utf-8')
            run=subprocess.run([sys.executable,str(installer),'--destination',str(dest),'--enable-public-pr'],capture_output=True,text=True)
            self.assertNotEqual(run.returncode,0)
            self.assertEqual((dest/'custom.txt').read_text(), 'keep')


if __name__ == '__main__': unittest.main()
