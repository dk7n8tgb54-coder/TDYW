# -*- coding: utf-8 -*-
"""探活部署配置契约：sidecar 写入路径、主应用读取路径与卷挂载必须一致。

部署编排（docker-compose.yml）无法用行为测试覆盖，这里以结构化 YAML
解析做静态契约校验；探活采集与聚合的行为本身由 test_run_metrics.py 的
真实 ingest/flush 测试保证。运行环境需能访问 docker/docker-compose.yml
（tdyw-test 内通过 docker cp 放置），缺失时整类跳过并标记原因。
"""
import unittest
from pathlib import Path

from django.conf import settings
from django.test import SimpleTestCase

try:
    import yaml
except ImportError:  # pragma: no cover - 测试容器按需安装
    yaml = None

COMPOSE_PATH = Path(settings.BASE_DIR).parent / 'docker' / 'docker-compose.yml'


@unittest.skipUnless(yaml is not None, 'PyYAML not installed in test env')
@unittest.skipUnless(COMPOSE_PATH.exists(), f'compose file not visible at {COMPOSE_PATH}')
class ProbeDeployConfigTest(SimpleTestCase):
    """sidecar 日志路径 / 卷挂载 / healthcheck 与后端配置的一致性。"""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        with open(COMPOSE_PATH, 'r', encoding='utf-8') as stream:
            cls.compose = yaml.safe_load(stream)
        cls.services = cls.compose['services']
        cls.probe = cls.services['tdyw-health-probe']

    def _probe_env(self):
        env = {}
        for item in self.probe['environment']:
            key, _, value = item.partition('=')
            env[key] = value
        return env

    def test_sidecar_log_paths_match_app_settings(self):
        env = self._probe_env()
        self.assertEqual(env.get('HEALTH_PROBE_LOG'), settings.RUN_METRICS_PROBE_LOG)
        self.assertEqual(env.get('NGINX_LOG'), settings.RUN_METRICS_NGINX_LOG)
        self.assertEqual(self.probe['entrypoint'], ['python', '/opt/health_probe.py'])

    def test_probe_volume_shared_readonly_with_app(self):
        app_mounts = [v for v in self.services['tdyw']['volumes'] if v.startswith('tdyw-health-probe-logs')]
        sidecar_mounts = [v for v in self.probe['volumes'] if v.startswith('tdyw-health-probe-logs')]
        # 主应用只读消费，sidecar 可写；同一 named volume、同一容器内路径
        self.assertEqual(app_mounts, ['tdyw-health-probe-logs:/var/log/tdyw:ro'])
        self.assertEqual(sidecar_mounts, ['tdyw-health-probe-logs:/var/log/tdyw'])
        self.assertIn('tdyw-health-probe-logs', self.compose.get('volumes', {}))

    def test_sidecar_healthcheck_targets_real_probe_output(self):
        healthcheck = self.probe.get('healthcheck', {})
        test_cmd = ' '.join(healthcheck.get('test', []))
        self.assertIn(settings.RUN_METRICS_PROBE_LOG, test_cmd)
        # 不得检查 sidecar 内不存在的 localhost:80（镜像内置 healthcheck 的坑）
        self.assertNotIn('localhost', test_cmd)
