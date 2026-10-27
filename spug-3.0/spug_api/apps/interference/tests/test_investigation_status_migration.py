# -*- coding: utf-8 -*-
"""规律调查状态迁移验证（0021）：专属隔离库上的真实迁移行为测试。

自包含隔离机制（2026-10-26 重构，消除"必须最后单独跑/失败污染默认测试库"
的隔离缺口）——不依赖默认测试库、不留痕、任意顺序可跑：

- setUpClass 用 settings.DATABASES['default'] 的深拷贝注册专属 alias
  ``migration_validation``（NAME=专属库 ``test_spug_qa_invlife_mig``）；
- 先经 NAME='' 的无库 DatabaseWrapper 执行 DROP DATABASE IF EXISTS +
  CREATE DATABASE（spug 用户具备全局 CREATE/DROP，无需补 GRANT），再
  ``call_command('migrate', database=...)`` 在专属库全量迁移到最新；
- 专属库头部状态采用克隆而非从零全量迁移：项目里个别历史迁移的
  RunPython 直用模块级全局 ``connection`` 裸游标（如 contract 0002、
  document 0005），``--database`` 与路由都无法重定向，别名库从零
  全量迁移在本项目不可行。克隆以 SHOW CREATE TABLE 逐表复制 default
  测试库（迁移完成后的头部状态）的全部表结构并复制 django_migrations
  记录，对源库只读（测试运行器已把 default 指向 test_spug_qa_invlife）；
- 随后仅对 interference 执行 0021 回退/前滚（真实执行迁移代码）；
  干扰 0021 迁移的数据操作按 schema_editor.connection.alias 显式
  using，保证落在专属库；
- 夹具与断言全部走专属 alias：User/InterferenceEvent/InvestigationEvent
  用 ``.using(ALIAS)``（三张表 0020 与 0021 列一致，ORM 安全），调查行
  保持 raw SQL（0020 时点无 0021 新列），CHECK 终态经 information_schema
  在 alias 连接上查询；
- addClassCleanup fail-safe：关连接 → DROP DATABASE → 摘除 alias，
  用毕即删、失败不留痕。

为什么不把 alias 写进 ``databases`` 类属性：测试运行器会扫描测试类的
``databases`` 并接管其中别名测试库的建库/迁移（时序不可控，且其他 app
迁移的 RunPython 会把数据写到 default），禁查守卫也会随之安装。本类
``databases={'default'}``（全程零查询，仅作 TestCase 事务包装载体），
alias 在预备阶段临时注册、预备完成后即摘除注册，连接对象由类持有继续
使用——运行器与守卫均不可见，库生命周期完全由本类自管。类为普通
TestCase：全部迁移执行收敛在 setUpClass 且位于 super().setUpClass()
进入的类级事务之前，DDL 永不处于事务管理之下，测试方法只读，无任何
flush 路径。

断言内容：
1. 状态映射：draft/observing/measuring → investigating；concluded/closed
   → ended；cancelled → cancelled；
2. 不从 conclusion 文本推断 result：所有行（含带结论文本行）result==''
   且 cancel_reason==''；
3. InvestigationEvent 事件关联与 tenant_id 全部保留；
4. information_schema 查询 inter_inv_status_valid CHECK 只含
   investigating/ended/cancelled。
"""

import copy
import time
from datetime import datetime

from django.conf import settings
from django.core.management import call_command
from django.db import connections
from django.db.backends.mysql import base as mysql_base
from django.test import TestCase

from apps.account.models import User
from apps.interference.models import InterferenceEvent, InvestigationEvent

DB_ALIAS = 'migration_validation'
DB_NAME = 'test_spug_qa_invlife_mig'
INVESTIGATION_TABLE = 'tdyw_interference_investigations'
LINK_TABLE = 'tdyw_interference_investigation_events'

# (tenant_id, 用户名后缀, name, 旧 status, conclusion)
STATUS_FIXTURES = (
    ('tenant-mig-a', 'a', '迁移草稿', 'draft', ''),
    ('tenant-mig-a', 'a', '迁移观察', 'observing', ''),
    ('tenant-mig-a', 'a', '迁移测量', 'measuring', ''),
    ('tenant-mig-b', 'b', '迁移已结论', 'concluded', '发现规律：同频干扰'),
    ('tenant-mig-b', 'b', '迁移已关闭', 'closed', ''),
    ('tenant-mig-b', 'b', '迁移已取消', 'cancelled', ''),
)

EXPECTED_STATUS_MAP = {
    '迁移草稿': 'investigating',
    '迁移观察': 'investigating',
    '迁移测量': 'investigating',
    '迁移已结论': 'ended',
    '迁移已关闭': 'ended',
    '迁移已取消': 'cancelled',
}


class InvestigationStatusMigrationTest(TestCase):
    """0021 状态映射/不推断/关联保留/DB CHECK 终态（专属隔离库）。"""

    databases = {'default'}

    @classmethod
    def setUpClass(cls):
        cls._register_alias()
        cls.addClassCleanup(cls._teardown_alias)
        try:
            cls._prepare_isolated_database()
        finally:
            # 预备结束即摘除注册：运行器与禁查守卫不可见；连接对象由
            # cls._conn 持有继续供只读断言使用。
            cls._detach_alias()
        # 类级事务此后只在 default 上进入（零查询）；专属库 DDL 已全部
        # 完成，测试方法只读，无任何 flush 路径。
        super().setUpClass()

    # ---------- alias 生命周期 ----------

    @classmethod
    def _register_alias(cls):
        cls._alias_config = copy.deepcopy(settings.DATABASES['default'])
        cls._alias_config['NAME'] = DB_NAME
        settings.DATABASES[DB_ALIAS] = cls._alias_config
        connections.databases[DB_ALIAS] = cls._alias_config

    @classmethod
    def _detach_alias(cls):
        cls._conn = connections[DB_ALIAS]
        connections.databases.pop(DB_ALIAS, None)
        settings.DATABASES.pop(DB_ALIAS, None)

    @classmethod
    def _nodb_wrapper(cls):
        config = copy.deepcopy(settings.DATABASES['default'])
        config['NAME'] = ''
        return mysql_base.DatabaseWrapper(config, alias=DB_ALIAS + '_nodb')

    @classmethod
    def _drop_database(cls):
        wrapper = cls._nodb_wrapper()
        try:
            with wrapper.cursor() as cursor:
                cursor.execute('DROP DATABASE IF EXISTS `%s`' % DB_NAME)
        finally:
            wrapper.close()

    @classmethod
    def _teardown_alias(cls):
        """fail-safe 清理：关连接 → 删库 → 摘除 alias，任何一步失败不阻断。"""
        try:
            try:
                if getattr(cls, '_conn', None) is not None:
                    cls._conn.close()
                elif connections.databases.get(DB_ALIAS) is not None:
                    connections[DB_ALIAS].close()
            except Exception:
                pass
            try:
                cls._drop_database()
            except Exception:
                pass
        finally:
            connections.databases.pop(DB_ALIAS, None)
            settings.DATABASES.pop(DB_ALIAS, None)

    # ---------- 专属库准备 ----------

    @classmethod
    def _create_database(cls):
        wrapper = cls._nodb_wrapper()
        try:
            with wrapper.cursor() as cursor:
                cursor.execute('DROP DATABASE IF EXISTS `%s`' % DB_NAME)
                cursor.execute(
                    'CREATE DATABASE `%s` CHARACTER SET utf8mb4 '
                    'COLLATE utf8mb4_unicode_ci' % DB_NAME)
        finally:
            wrapper.close()

    @classmethod
    def _insert_investigation(cls, tenant_id, name, status, conclusion,
                              created_by_id):
        """在 0020 时点以旧状态直插调查行（ORM 会带出 0021 新列，故用 SQL）。"""
        sql = (
            'INSERT INTO %s (tenant_id, name, scope, owner, trigger_reason, '
            'start_at, end_at, status, conclusion, follow_up_advice, remark, '
            'created_by_id, created_at, updated_by_id, updated_at, is_deleted, '
            'deleted_at) VALUES (%%s, %%s, \'\', \'\', \'\', NULL, NULL, '
            '%%s, %%s, \'\', \'\', %%s, NOW(), NULL, NULL, 0, NULL)'
            % INVESTIGATION_TABLE)
        with connections[DB_ALIAS].cursor() as cursor:
            cursor.execute(sql, [tenant_id, name, status, conclusion,
                                 created_by_id])
            cursor.execute('SELECT LAST_INSERT_ID()')
            return cursor.fetchone()[0]

    @classmethod
    def _insert_fixtures(cls):
        users = {
            'a': User.objects.using(DB_ALIAS).create(
                username='inv_mig_user_a', nickname='inv_mig_user_a',
                password_hash='x', is_active=True, is_supper=False,
                access_token='inv_mig_user_a_%d' % time.time(),
                token_expired=int(time.time()) + 3600,
                last_login='2026-01-01', last_ip='127.0.0.1',
                type='default', tenant_id='tenant-mig-a'),
            'b': User.objects.using(DB_ALIAS).create(
                username='inv_mig_user_b', nickname='inv_mig_user_b',
                password_hash='x', is_active=True, is_supper=False,
                access_token='inv_mig_user_b_%d' % time.time(),
                token_expired=int(time.time()) + 3600,
                last_login='2026-01-01', last_ip='127.0.0.1',
                type='default', tenant_id='tenant-mig-b'),
        }
        fixtures = []
        for index, (tenant_id, user_key, name, status, conclusion) in enumerate(
                STATUS_FIXTURES):
            event = InterferenceEvent.objects.using(DB_ALIAS).create(
                tenant_id=tenant_id,
                datetime=datetime(2026, 10, 1, 9, index % 60),
                scene_code='ground', phenomenon=name,
                created_by=users[user_key])
            investigation_id = cls._insert_investigation(
                tenant_id, name, status, conclusion, users[user_key].id)
            InvestigationEvent.objects.using(DB_ALIAS).create(
                investigation_id=investigation_id, event=event,
                tenant_id=tenant_id, created_by=users[user_key])
            fixtures.append((investigation_id, tenant_id, name))
        cls._fixtures = fixtures

    @classmethod
    def _clone_head_state(cls):
        """把 default 测试库（头部状态）的表结构与迁移记录克隆进专属库。

        对源库只读；SHOW CREATE TABLE 逐表复制（含索引与 CHECK 约束，
        CREATE TABLE LIKE 不复制 CHECK），建表期间关闭本会话外键检查以
        允许乱序建表，复制 django_migrations 让执行器认定全部已应用。
        """
        source_db = connections['default'].settings_dict['NAME']
        with connections[DB_ALIAS].cursor() as cursor:
            cursor.execute('SET FOREIGN_KEY_CHECKS = 0')
            try:
                cursor.execute(
                    'SELECT table_name FROM information_schema.tables '
                    'WHERE table_schema = %s ORDER BY table_name', [source_db])
                tables = [row[0] for row in cursor.fetchall()]
                for table in tables:
                    cursor.execute('SHOW CREATE TABLE `%s`.`%s`'
                                   % (source_db, table))
                    create_sql = cursor.fetchone()[1]
                    cursor.execute(create_sql)
                cursor.execute(
                    'INSERT INTO `%s`.django_migrations '
                    'SELECT * FROM `%s`.django_migrations'
                    % (DB_NAME, source_db))
            finally:
                cursor.execute('SET FOREIGN_KEY_CHECKS = 1')

    @classmethod
    def _prepare_isolated_database(cls):
        cls._create_database()
        cls._clone_head_state()
        # 真实执行迁移代码：0021 回退/前滚（数据操作 .using(alias) 落专属库）
        call_command('migrate', 'interference', '0020', verbosity=0,
                     interactive=False, database=DB_ALIAS)
        cls._insert_fixtures()
        call_command('migrate', 'interference', verbosity=0,
                     interactive=False, database=DB_ALIAS)

    # ---------- 断言（只读，经类持有的 alias 连接） ----------

    def test_status_migration_mapping_and_check(self):
        with self._conn.cursor() as cursor:
            cursor.execute(
                'SELECT id, tenant_id, status, result, cancel_reason, name '
                'FROM %s ORDER BY id' % INVESTIGATION_TABLE)
            rows = cursor.fetchall()
        self.assertEqual(len(rows), 6, rows)
        by_id = {row[0]: row for row in rows}
        for investigation_id, tenant_id, name in self._fixtures:
            row = by_id[investigation_id]
            self.assertEqual(row[1], tenant_id, name)
            self.assertEqual(row[2], EXPECTED_STATUS_MAP[name], name)
            # 禁止从自由文本 conclusion 推断 result（含带结论文本的行）
            self.assertEqual(row[3], '', name)
            self.assertEqual(row[4], '', name)

        # 事件关联全部保留
        with self._conn.cursor() as cursor:
            cursor.execute(
                'SELECT tenant_id, investigation_id, event_id, is_deleted '
                'FROM %s ORDER BY id' % LINK_TABLE)
            links = cursor.fetchall()
        self.assertEqual(len(links), 6, links)
        valid_ids = set(by_id)
        for tenant_id, investigation_id, event_id, is_deleted in links:
            self.assertEqual(is_deleted, 0)
            self.assertIn(investigation_id, valid_ids)
            self.assertIn(tenant_id, ('tenant-mig-a', 'tenant-mig-b'))

        # DB CHECK 终态：只允许新三态
        with self._conn.cursor() as cursor:
            cursor.execute(
                'SELECT CHECK_CLAUSE FROM information_schema.CHECK_CONSTRAINTS '
                'WHERE CONSTRAINT_SCHEMA = DATABASE() '
                'AND CONSTRAINT_NAME = %s', ['inter_inv_status_valid'])
            check_rows = cursor.fetchall()
        self.assertTrue(check_rows, 'inter_inv_status_valid CHECK 未找到')
        clause = ''.join(str(row[0]) for row in check_rows)
        self.assertIn('investigating', clause)
        self.assertIn('ended', clause)
        self.assertIn('cancelled', clause)
        self.assertNotIn('observing', clause)
        self.assertNotIn('measuring', clause)
        self.assertNotIn('draft', clause)
