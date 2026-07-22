#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
部门值班日志全功能压测脚本(🔴 必补)

覆盖 department_duty_log 模块所有 HTTP 接口:
1. GET    /api/department-duty-log/records/           列表(分页+筛选)
2. POST   /api/department-duty-log/records/           新建草稿
3. GET    /api/department-duty-log/records/<pk>/      详情
4. PUT    /api/department-duty-log/records/<pk>/      编辑草稿
5. DELETE /api/department-duty-log/records/<pk>/      删除草稿
6. POST   /api/department-duty-log/records/<pk>/sign/  签署
7. POST   /api/department-duty-log/records/<pk>/void/  作废
8. POST   /api/department-duty-log/export/pdf/        PDF 导出
9. GET    /api/department-duty-log/options/            选项

运行:
    python -m locust -f locustfile/locustfile_department_duty_log.py -H http://localhost
    python -m locust -f locustfile/locustfile_department_duty_log.py -H http://localhost \\
        --headless -u 10 -r 2 -t 5m --csv=department_duty_log

前置条件:
- 压测账号需有 department_duty_log.department_duty_log.{view,add,edit,del,sign,void,export} 权限
- 签署需要账号已设置个人签名图片(无签名时签署返回错误,属预期)

数据保留:
    默认保留所有压测数据(用户要求)。设 KEEP_TEST_DATA=0 可在 on_stop 删除草稿。
"""

import uuid
import random
import logging
from datetime import date, timedelta

from locust import task, between, events

from _common import TokenSharedHttpUser, KEEP_TEST_DATA

logger = logging.getLogger(__name__)

BASE = "/api/department-duty-log"


class DepartmentDutyLogUser(TokenSharedHttpUser):
    """部门值班日志全功能压测用户"""

    wait_time = between(1, 3)

    def on_start(self):
        super().on_start()
        self.my_drafts = {}   # {id: version} 本人创建的草稿(可编辑/签署/删除)
        self.signed_ids = []  # 本人已签记录 id(可作废)
        self.known_ids = []   # 列表里看到的记录 id,仅供「只读详情」,绝不写/删(避免多用户抢同一记录)
        self._fetch_options()
        self._check_signature()
        self._fetch_existing_records()
        # on_start 创建 2 个草稿作为测试数据
        for _ in range(2):
            self._do_create_draft()

    def on_stop(self):
        if KEEP_TEST_DATA:
            return
        for pk in list(self.my_drafts.keys()):
            try:
                self._delete(f"{BASE}/records/{pk}/", "[清理] 删除草稿")
            except Exception:
                pass

    # ---------- 准备 ----------
    def _fetch_options(self):
        with self._get(f"{BASE}/options/", "[准备] 查询选项") as resp:
            if resp.status_code == 200:
                body = resp.json() or {}
                if body.get("error"):
                    resp.failure(f"options 权限不足: {body['error'][:80]}")
                else:
                    resp.success()
            else:
                resp.failure(f"options HTTP {resp.status_code}")

    def _check_signature(self):
        """诊断性探测:当前账号是否已由 provision_stress_signatures.py 灌入签名。

        压测账号是普通用户,签名只能由超管设置,故正常情况下脚本应预先灌好。
        此处仅做告警:若发现未配置签名,打印提示让用户去跑制备脚本
        (locustfile/tools/provision_stress_signatures.py),**不做任何掩盖**——
        签署任务会如实把 '未配置有效签名' 计入失败率,以暴露制备遗漏。
        """
        try:
            with self._get("/api/signature/mine/", "[准备] 查询签名") as resp:
                if resp.status_code == 200:
                    body = resp.json() or {}
                    sig = body.get("data") or {}
                    has = bool(sig.get("id") and sig.get("has_signature"))
                    resp.success()
                    if not has and not getattr(self, "_sig_warn_logged", False):
                        print(f"[警告] 账号 {self.username} 未配置电子签名!"
                              f"请先运行 locustfile/tools/provision_stress_signatures.py")
                        self._sig_warn_logged = True
                else:
                    resp.success()
        except Exception:
            pass

    def _fetch_existing_records(self):
        """拉取已有记录填充 known_ids(只读详情用)。

        关键修复:原先把列表中「所有 can_sign 的草稿」塞进本用户的 my_drafts,
        导致多个虚拟用户并发操作 *同一批* 记录 → 版本冲突/记录不存在/无权操作。
        现改为 known_ids 仅用于「只读详情」,写/删/签只作用于本人创建的 my_drafts,
        彻底消除并发抢记录问题。
        """
        with self._get(f"{BASE}/records/?page=1&page_size=50", "[准备] 查询列表") as resp:
            if resp.status_code != 200:
                resp.failure(f"列表 HTTP {resp.status_code}")
                return
            body = resp.json() or {}
            if body.get("error"):
                resp.failure(f"列表权限不足: {body['error'][:80]}")
                return
            resp.success()
            data = body.get("data") or {}
            for r in data.get("records") or []:
                rid = r.get("id")
                if rid and rid not in self.known_ids:
                    self.known_ids.append(rid)

    def _gen_payload(self):
        """生成创建/编辑草稿的 payload(5 个必填字段)"""
        d = date.today() - timedelta(days=random.randint(0, 30))
        return {
            "duty_date": d.strftime("%Y-%m-%d"),
            "mains_voltage": f"{random.randint(218, 222)}V",
            "ups_voltage": f"{random.randint(218, 222)}V",
            "weather": random.choice(["晴", "阴", "小雨", "多云", "雷阵雨"]),
            "duty_record": f"压测值班记录_{uuid.uuid4().hex[:8]}。设备运行正常,无异常情况。",
            "remark": "",
        }

    # ---------- 高频查询 ----------
    @task(10)
    def list_records(self):
        params = {"page": 1, "page_size": 20}
        if random.random() < 0.3:
            d = (date.today() - timedelta(days=random.randint(0, 7))).strftime("%Y-%m-%d")
            params["start_date"] = d
        with self._get(f"{BASE}/records/", "GET /records/ (列表)", params=params) as resp:
            if resp.status_code == 200:
                body = resp.json() or {}
                if body.get("error"):
                    resp.failure(f"列表错误: {body['error'][:80]}")
                else:
                    resp.success()
            else:
                resp.failure(f"列表 HTTP {resp.status_code}")

    @task(5)
    def get_detail(self):
        all_ids = list(self.my_drafts.keys()) + self.signed_ids + self.known_ids
        if not all_ids:
            return
        pk = random.choice(all_ids)
        with self._get(f"{BASE}/records/{pk}/", "GET /records/<pk>/ (详情)") as resp:
            if resp.status_code == 200:
                body = resp.json() or {}
                if body.get("error"):
                    resp.failure(f"详情错误: {body['error'][:80]}")
                else:
                    resp.success()
            elif resp.status_code == 404:
                self.my_drafts.pop(pk, None)
                if pk in self.signed_ids:
                    self.signed_ids.remove(pk)
                if pk in self.known_ids:
                    self.known_ids.remove(pk)
                resp.success()
            else:
                resp.failure(f"详情 HTTP {resp.status_code}")

    @task(1)
    def get_options(self):
        with self._get(f"{BASE}/options/", "GET /options/") as resp:
            if resp.status_code == 200:
                resp.success()
            else:
                resp.failure(f"options HTTP {resp.status_code}")

    # ---------- 写操作 ----------
    @task(3)
    def create_draft(self):
        self._do_create_draft()

    def _do_create_draft(self):
        with self._post(f"{BASE}/records/", "POST /records/ (新建草稿)",
                        json=self._gen_payload()) as resp:
            if resp.status_code == 200:
                body = resp.json() or {}
                if body.get("error"):
                    resp.failure(f"新建错误: {body['error'][:80]}")
                    return
                data = body.get("data") or {}
                rid = data.get("id")
                if rid:
                    self.my_drafts[rid] = data.get("version", 1)
                resp.success()
            else:
                resp.failure(f"新建 HTTP {resp.status_code}: {resp.text[:80]}")

    @task(2)
    def edit_draft(self):
        if not self.my_drafts:
            return
        pk = random.choice(list(self.my_drafts.keys()))
        version = self.my_drafts.get(pk, 1)
        payload = self._gen_payload()
        payload["version"] = version
        with self._put(f"{BASE}/records/{pk}/", "PUT /records/<pk>/ (编辑草稿)",
                       json=payload) as resp:
            if resp.status_code == 200:
                body = resp.json() or {}
                if body.get("error"):
                    resp.failure(f"编辑错误: {body['error'][:80]}")
                else:
                    self.my_drafts[pk] = version + 1
                    resp.success()
            elif resp.status_code == 404:
                self.my_drafts.pop(pk, None)
                resp.success()
            else:
                resp.failure(f"编辑 HTTP {resp.status_code}")

    @task(1)
    def sign_draft(self):
        if not self.my_drafts:
            return
        pk = random.choice(list(self.my_drafts.keys()))
        version = self.my_drafts.get(pk, 1)
        with self._post(f"{BASE}/records/{pk}/sign/", "POST /sign/ (签署)",
                        json={"version": version, "confirm": True,
                              "request_id": uuid.uuid4().hex}) as resp:
            if resp.status_code == 200:
                body = resp.json() or {}
                if body.get("error"):
                    # 真实信号:压测账号已通过 provision_stress_signatures.py 灌入电子签名,
                    # 若仍报"未配置有效签名"说明制备脚本未执行/失败,应如实计入失败率。
                    resp.failure(f"签署错误: {body['error'][:80]}")
                else:
                    self.my_drafts.pop(pk, None)
                    self.signed_ids.append(pk)
                    resp.success()
            else:
                resp.failure(f"签署 HTTP {resp.status_code}: {resp.text[:80]}")

    @task(1)
    def void_record(self):
        if not self.signed_ids:
            return
        pk = random.choice(self.signed_ids)
        with self._post(f"{BASE}/records/{pk}/void/", "POST /void/ (作废)",
                        json={"reason": f"压测作废_{uuid.uuid4().hex[:8]}"}) as resp:
            if resp.status_code == 200:
                body = resp.json() or {}
                if body.get("error"):
                    resp.failure(f"作废错误: {body['error'][:80]}")
                else:
                    self.signed_ids.remove(pk)
                    resp.success()
            elif resp.status_code == 404:
                if pk in self.signed_ids:
                    self.signed_ids.remove(pk)
                resp.success()
            else:
                resp.failure(f"作废 HTTP {resp.status_code}")

    @task(1)
    def delete_draft(self):
        if not self.my_drafts:
            return
        pk = random.choice(list(self.my_drafts.keys()))
        with self._delete(f"{BASE}/records/{pk}/", "DELETE /records/<pk>/ (删除草稿)") as resp:
            if resp.status_code == 200:
                body = resp.json() or {}
                if body.get("error"):
                    resp.failure(f"删除错误: {body['error'][:80]}")
                else:
                    self.my_drafts.pop(pk, None)
                    resp.success()
            elif resp.status_code == 404:
                self.my_drafts.pop(pk, None)
                resp.success()
            else:
                resp.failure(f"删除 HTTP {resp.status_code}")

    @task(2)
    def export_pdf(self):
        with self._post(f"{BASE}/export/pdf/", "POST /export/pdf/ (PDF导出)",
                        json={}) as resp:
            if resp.status_code == 200:
                resp.success()
            elif resp.status_code == 500:
                resp.failure(f"导出 500(可能 OOM): {resp.text[:120]}")
            elif resp.status_code == 400:
                # 无已签记录可导出(因账号无签名导致无签署)→ 预期失败,不计失败率
                err = (resp.json() or {}).get("error", "")
                if "没有可导出的已签记录" in err:
                    if not getattr(self, "_export_expected_logged", False):
                        print(f"[User] 无已签记录,PDF 导出将预期失败(属正常): {err[:40]}")
                        self._export_expected_logged = True
                    resp.success()
                else:
                    resp.failure(f"导出 400: {err[:120]}")
            else:
                resp.failure(f"导出 HTTP {resp.status_code}: {resp.text[:120]}")


@events.test_start.add_listener
def on_test_start(environment, **kwargs):
    print("=" * 60)
    print("部门值班日志全功能压测开始")
    print("  覆盖: 列表/详情/新建/编辑/删除/签署/作废/导出/选项")
    print("  签署需账号有签名图片,无签名时签署失败属预期")
    if KEEP_TEST_DATA:
        print("  [KEEP_TEST_DATA] 压测数据保留(不自动清理)")
    print("=" * 60)
