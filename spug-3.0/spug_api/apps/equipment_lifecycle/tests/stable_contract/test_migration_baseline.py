# -*- coding: utf-8 -*-
"""equipment_lifecycle 迁移基线契约测试（2026-10-24 基线重建）。

背景：EL 模块未上线（生产 tdyw 库无 django_migrations 记录、无 tdyw_el_*
表），旧迁移 0001-0029 全部删除，0001_initial 由当前注册模型重新生成，
成为唯一迁移节点。本测试固化新基线契约（真实迁移图/迁移状态/数据库
introspection，非源码文本匹配）：

1. 迁移图：equipment_lifecycle 有且仅有 0001_initial 一个节点，
   无后继迁移、无数据操作（RunPython/RunSQL）——EL 未上线，
   历史回填/状态归一/权限换发逻辑全部不进入基线；
2. 依赖解析：upgrade.0022 对 ('equipment_lifecycle', '0001_initial')
   的依赖在迁移图中可解析（依赖边真实存在）；
3. 模型终态：0001 的 project_state 渲染模型集合与当前注册模型完全一致
   （双向集合相等，不多不少）；
4. 表终态：测试库（由测试运行器从空库按新基线 migrate 建出）的
   tdyw_el_* 表与当前模型 db_table 集合完全一致；已退役巡检/在线布局/
   旧故障/旧运行记录/系统履历/原生台账表一律不存在。

历史对照（迁移 0026 退役原生路线时曾有 MigrationExecutor 时间点测试与
0026 清数函数测试）：基线重建后历史迁移模块已删除，本文件以
"基线从不创建退役对象"的更强断言收口同类契约。
"""
from django.apps import apps
from django.db import connection
from django.db.migrations.loader import MigrationLoader
from django.db.migrations.operations import RunPython, RunSQL
from django.test import TestCase

APP_LABEL = 'equipment_lifecycle'

# 已退役业务族的表名前缀（任何一条出现在新基线库中即为违约）
RETIRED_TABLE_PREFIXES = (
    'tdyw_el_inspection',       # 值班巡检六表（2026-10-14 退役）
    'tdyw_el_ins_',             # 巡检值班人员
    'tdyw_el_ledger_layout',    # 在线设计器模板/版本（2026-10-14 退役）
    'tdyw_el_fault',            # 旧故障处置/处理进展（2026-10-11 退役）
    'tdyw_el_runtime_record',   # 旧运行记录三表（2026-10-11 退役）
    'tdyw_el_system_event',     # 系统履历（2026-10-11 退役）
    'tdyw_el_ledger_native',    # 原生台账路线三表（2026-10-20 退役）
)


def _disk_loader():
    loader = MigrationLoader(None, ignore_no_migrations=True)
    loader.build_graph()
    return loader


class MigrationGraphContractTest(TestCase):
    """迁移图结构契约（磁盘图，不触碰数据库迁移状态）。"""

    def test_single_baseline_node(self):
        """el 有且仅有 0001_initial 一个迁移节点。"""
        loader = _disk_loader()
        el_nodes = sorted(k for k in loader.graph.nodes if k[0] == APP_LABEL)
        self.assertEqual(el_nodes, [(APP_LABEL, '0001_initial')])

    def test_baseline_has_no_data_operations(self):
        """0001 仅含 schema 操作：EL 未上线，无任何历史数据回填逻辑。"""
        loader = _disk_loader()
        migration = loader.disk_migrations[(APP_LABEL, '0001_initial')]
        data_ops = [
            op.__class__.__name__ for op in migration.operations
            if isinstance(op, (RunPython, RunSQL))
        ]
        self.assertEqual(data_ops, [])

    def test_upgrade_0022_dependency_resolves(self):
        """upgrade.0022 对 el.0001_initial 的依赖边真实存在于迁移图。"""
        loader = _disk_loader()
        node_key = ('upgrade', '0022_upgrade_record_template_link_lifecycle_system')
        self.assertIn(node_key, loader.graph.nodes)
        parents = loader.graph.node_map[node_key].parents
        self.assertIn((APP_LABEL, '0001_initial'), parents)

    def test_project_state_matches_registered_models(self):
        """0001 渲染模型集合与当前注册模型双向一致。"""
        loader = _disk_loader()
        state = loader.project_state((APP_LABEL, '0001_initial'))
        baseline_models = set(
            state.apps.get_app_config(APP_LABEL).get_models())
        registered_models = set(
            apps.get_app_config(APP_LABEL).get_models())
        self.assertEqual(
            {m.__name__ for m in baseline_models},
            {m.__name__ for m in registered_models})


class BaselineTablesContractTest(TestCase):
    """新基线建出的数据库表与当前模型完全对应（introspection 实查）。

    测试库由测试运行器从空库按当前迁移图（新 0001）完整 migrate 建出，
    表清单即新基线的真实建表结果。
    """

    def test_tables_match_registered_models(self):
        with connection.cursor() as cursor:
            tables = set(connection.introspection.table_names(cursor))
        expected = {
            model._meta.db_table
            for model in apps.get_app_config(APP_LABEL).get_models()
        }
        el_tables = {t for t in tables if t.startswith('tdyw_el_')}
        self.assertEqual(el_tables, expected)

    def test_retired_family_tables_absent(self):
        with connection.cursor() as cursor:
            tables = connection.introspection.table_names(cursor)
        leftovers = [
            t for t in tables
            if t.startswith(RETIRED_TABLE_PREFIXES)
        ]
        self.assertEqual(
            leftovers, [],
            '新基线不应创建任何已退役业务族的表')
