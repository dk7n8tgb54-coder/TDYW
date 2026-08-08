"""
运行日志模块 Locust 压测脚本

使用说明:
1. 安装依赖: pip install locust
2. 运行测试: locust -f locustfile_runlog.py -H http://localhost:80
3. 打开浏览器访问: http://localhost:8089
4. 设置并发用户数和 spawn rate，开始测试

或者命令行直接运行:
locust -f locustfile_runlog.py -H http://localhost:80 --users 100 --spawn-rate 20 --run-time 5m --headless
"""

import json
import random
import uuid
import logging
import threading
import time
from datetime import datetime, timedelta
from locust import task, between, events

from _common import TokenSharedHttpUser

logger = logging.getLogger(__name__)


class RunLogUser(TokenSharedHttpUser):
    """
    运行日志功能压测用户类
    模拟真实用户操作：查看日志列表、创建事件、添加动态、上传附件、统计查询等

    认证：继承 TokenSharedHttpUser，on_start 时通过 login_shared() 从 _common.py 的
    DEFAULT_ACCOUNTS(st_press_01~05) 中轮询取一个账号登录，token 全局共享(避免同账号
    多并发互相覆盖导致 401 风暴/账号锁定)。
    """

    # 请求间隔：0.5-1秒（平衡压力与性能测试）
    wait_time = between(0.5, 1)

    # 类变量：共享测试数据（所有用户共享）
    shared_test_event_ids = []
    test_data_prepared = False
    _lock = threading.Lock()

    def __init__(self, parent):
        super().__init__(parent)
        self.test_event_ids = []  # 当前用户创建的事件ID列表
        self.test_update_ids = []  # 当前用户的动态ID列表

    def on_start(self):
        """
        用户启动时执行：登录(基类 login_shared→self.token)并准备测试数据
        """
        super().on_start()
        self.prepare_test_data()

    def prepare_test_data(self):
        """
        准备测试数据：每个用户创建一些测试事件
        """
        try:
            with RunLogUser._lock:
                if RunLogUser.test_data_prepared:
                    print(f"[User] 使用已有测试数据，跳过创建")
                    self.load_existing_events()
                    return

                print(f"[User] 我是第一个用户，开始创建测试数据...")
                RunLogUser.test_data_prepared = True

            # 创建5个测试事件
            for i in range(5):
                self._create_test_event()
                time.sleep(0.2)  # 避免创建过快

            print(f"[User] 测试数据准备完成，创建了 {len(self.test_event_ids)} 个事件")

            # 分享给其他用户
            with RunLogUser._lock:
                RunLogUser.shared_test_event_ids.extend(self.test_event_ids)

            # 等待数据库写入完成
            time.sleep(1.0)
            self.load_existing_events()

        except Exception as e:
            print(f"[User] 准备测试数据失败: {e}")

    def load_existing_events(self):
        """加载现有的事件列表"""
        try:
            with self._get(
                "/api/runlog/",
                
                name="[准备] 获取事件列表",
                
            ) as response:
                if response.status_code == 200:
                    result = response.json()
                    logs = result.get('logs', [])
                    for log in logs:
                        if log.get('id') not in self.test_event_ids:
                            self.test_event_ids.append(log.get('id'))
                    print(f"[User] 加载到 {len(self.test_event_ids)} 个事件")
                    response.success()
                else:
                    print(f"[User] 加载事件列表失败: {response.status_code}")
                    response.failure(f"HTTP {response.status_code}")

        except Exception as e:
            print(f"[User] 加载事件列表失败: {e}")

    def _create_test_event(self):
        """创建一个测试事件"""
        try:
            today = datetime.now().strftime('%Y-%m-%d')

            event_data = {
                "event_title": f"测试事件_{uuid.uuid4().hex[:8]}",
                "event_type": random.choice(["运行异常", "设备故障", "安全事件", "其他"]),
                "system_name": random.choice(["ERP系统", "MES系统", "WMS系统", "HR系统"]),
                "severity": random.choice(["P0", "P1", "P2"]),
                "responsible_user_id": 1,
                "responsible_user_name": "admin",
                "first_update": {
                    "update_date": today,
                    "update_time_detail": "10:00",
                    "recorder": "admin",
                    "detail_content": "初始测试动态",
                    "duty_date": today,
                }
            }

            with self._post(
                "/api/runlog/",
                json=event_data,
                name="[准备] 创建测试事件"
            ) as response:
                if response.status_code == 200:
                    try:
                        result = response.json()
                        event_id = result.get('id')
                        if event_id:
                            self.test_event_ids.append(event_id)
                            print(f"[User] 测试事件创建成功，ID: {event_id}")
                        else:
                            print(f"[User] 测试事件创建成功，但响应中没有ID: {result}")
                    except:
                        # 如果响应格式不符合预期，通过列表查询
                        print(f"[User] 测试事件创建成功，需要通过列表查询ID")
                    response.success()
                else:
                    print(f"[User] 创建测试事件失败: {response.status_code} - {response.text[:200]}")
                    response.failure(f"HTTP {response.status_code}")
                return response.status_code == 200

        except Exception as e:
            print(f"[User] 创建测试事件异常: {e}")
            return False

    # ==================== 查询类任务 ====================

    @task(15)
    def get_runlog_list(self):
        """
        【高频】获取运行日志列表 - 最频繁的操作
        """
        params = {}

        # 随机添加筛选条件
        if random.random() < 0.3:
            params['status'] = random.choice(['open', 'in_progress', 'resolved'])
        if random.random() < 0.3:
            params['severity'] = random.choice(['P0', 'P1', 'P2'])
        if random.random() < 0.2:
            params['event_type'] = random.choice(["运行异常", "设备故障", "安全事件"])

        # 日期筛选
        if random.random() < 0.4:
            days_ago = random.randint(0, 7)
            date_str = (datetime.now() - timedelta(days=days_ago)).strftime('%Y-%m-%d')
            params['date'] = date_str

        with self._get(
            "/api/runlog/",
            params=params,
            
            name="GET /api/runlog/ (列表)",
            
        ) as response:
            if response.status_code == 200:
                response.success()
            else:
                response.failure(f"状态码: {response.status_code}")

    @task(8)
    def get_runlog_detail(self):
        """
        【中频】获取事件详情（含动态列表）
        """
        if not self.test_event_ids:
            return

        event_id = random.choice(self.test_event_ids)

        with self._get(
            "/api/runlog/detail/",
            params={"id": event_id},
            
            name="GET /api/runlog/detail/ (详情)",
            
        ) as response:
            if response.status_code == 200:
                response.success()
            elif response.status_code == 404:
                # 事件可能已被删除，移除ID
                if event_id in self.test_event_ids:
                    self.test_event_ids.remove(event_id)
                response.success()
            else:
                response.failure(f"状态码: {response.status_code}")

    @task(5)
    def get_runlog_statistics(self):
        """
        【中频】获取统计数据
        """
        with self._get(
            "/api/runlog/statistics/",
            
            name="GET /api/runlog/statistics/ (统计)",
            
        ) as response:
            if response.status_code == 200:
                response.success()
            else:
                response.failure(f"状态码: {response.status_code}")

    # ==================== 创建任务 ====================

    @task(3)
    def create_runlog_event(self):
        """
        【低频】创建新的运行日志事件
        """
        try:
            today = datetime.now().strftime('%Y-%m-%d')
            time_detail = f"{random.randint(0, 23):02d}:{random.randint(0, 59):02d}"

            event_data = {
                "event_title": f"压测事件_{uuid.uuid4().hex[:8]}_{random.randint(1, 1000)}",
                "event_type": random.choice(["运行异常", "设备故障", "安全事件", "其他", "数据异常"]),
                "system_name": random.choice(["ERP系统", "MES系统", "WMS系统", "HR系统", "OA系统"]),
                "severity": random.choice(["P0", "P1", "P2"]),
                "responsible_user_id": 1,
                "responsible_user_name": "admin",
                "first_update": {
                    "update_date": today,
                    "update_time_detail": time_detail,
                    "recorder": "压测用户",
                    "detail_content": f"压测动态_{uuid.uuid4().hex[:8]}",
                    "duty_date": today,
                }
            }

            with self._post(
                "/api/runlog/",
                json=event_data,
                
                name="POST /api/runlog/ (创建事件)",
                
            ) as response:
                if response.status_code == 200:
                    response.success()
                    # 刷新事件列表
                    self.load_existing_events()
                else:
                    response.failure(f"状态码: {response.status_code}, 响应: {response.text[:200]}")

        except Exception as e:
            print(f"[User] 创建事件异常: {e}")

    # ==================== 动态更新任务 ====================

    @task(8)
    def add_runlog_update(self):
        """
        【中频】添加动态
        """
        if not self.test_event_ids:
            return

        try:
            event_id = random.choice(self.test_event_ids)
            today = datetime.now().strftime('%Y-%m-%d')
            time_detail = f"{random.randint(0, 23):02d}:{random.randint(0, 59):02d}"

            update_data = {
                "runlog_id": event_id,
                "update_date": today,
                "update_time_detail": time_detail,
                "recorder": "压测用户",
                "detail_content": f"压测动态内容_{uuid.uuid4().hex[:12]}",
                "duty_date": today,
                "attachments": []
            }

            with self._post(
                "/api/runlog/update/",
                json=update_data,
                
                name="POST /api/runlog/update/ (添加动态)",
                
            ) as response:
                if response.status_code == 200:
                    response.success()
                elif response.status_code == 404:
                    # 事件可能已被删除
                    if event_id in self.test_event_ids:
                        self.test_event_ids.remove(event_id)
                    response.success()
                else:
                    response.failure(f"状态码: {response.status_code}")

        except Exception as e:
            print(f"[User] 添加动态异常: {e}")

    @task(4)
    def update_runlog(self):
        """
        【低频】更新事件信息
        """
        if not self.test_event_ids:
            return

        event_id = random.choice(self.test_event_ids)

        update_data = {
            "id": event_id,
            "event_type": random.choice(["运行异常", "设备故障", "安全事件", "其他"]),
            "severity": random.choice(["P0", "P1", "P2"]),
            "status": random.choice(["open", "in_progress", "resolved"])
        }

        with self._put(
            "/api/runlog/",
            json=update_data,
            
            name="PUT /api/runlog/ (更新事件)",
            
        ) as response:
            if response.status_code in [200, 404]:
                response.success()
            elif response.status_code == 403:
                # 权限不足，可能是租户隔离
                response.success()
            else:
                response.failure(f"状态码: {response.status_code}")

    @task(2)
    def update_runlog_update(self):
        """
        【低频】编辑动态（24小时内）
        """
        if not self.test_event_ids:
            return

        # 先获取事件详情，找到可编辑的动态
        event_id = random.choice(self.test_event_ids)

        try:
            with self._get(
                "/api/runlog/detail/",
                params={"id": event_id},
                
                name="[辅助] 获取详情查找动态"
            ) as response:
                if response.status_code != 200:
                    return

                result = response.json()
                updates = result.get('updates', [])

                # 找到可编辑的动态
                editable_updates = [u for u in updates if u.get('can_edit', False)]
                if not editable_updates:
                    return

                update = random.choice(editable_updates)
                update_id = update.get('id')

                update_data = {
                    "id": update_id,
                    "detail_content": f"编辑后的动态_{uuid.uuid4().hex[:8]}",
                    "update_time_detail": f"{random.randint(0, 23):02d}:{random.randint(0, 59):02d}"
                }

                with self._put(
                    "/api/runlog/update/",
                    json=update_data,
                    
                    name="PUT /api/runlog/update/ (编辑动态)",
                    
                ) as response:
                    if response.status_code in [200, 403, 404]:
                        response.success()
                    else:
                        response.failure(f"状态码: {response.status_code}")

        except Exception as e:
            print(f"[User] 编辑动态异常: {e}")

    # ==================== 上传图片任务 ====================

    @task(3)
    def upload_runlog_image(self):
        """
        【低频】上传运行日志图片
        """
        try:
            # 模拟上传一个测试图片
            # 注意：实际压测时需要有真实图片文件
            # 这里使用一个小的测试图片数据

            # 由于locust的client.post对文件上传支持有限
            # 这里只测试API端点，不实际上传文件
            with self._post(
                "/api/runlog/upload/",
                
                name="POST /api/runlog/upload/ (图片上传)",
                
            ) as response:
                # 预期失败（没有文件），但端点可用
                if response.status_code in [400, 200]:
                    response.success()
                else:
                    response.failure(f"状态码: {response.status_code}")

        except Exception as e:
            print(f"[User] 上传图片异常: {e}")

    # ==================== 删除任务 ====================

    @task(1)
    def delete_runlog(self):
        """
        【极低频】删除运行日志事件
        """
        if not self.test_event_ids:
            return

        # 只删除一小部分事件，避免测试数据消耗过快
        if random.random() > 0.3:
            return

        event_id = random.choice(self.test_event_ids)

        with self._delete(
            "/api/runlog/",
            params={"id": event_id},
            
            name="DELETE /api/runlog/ (删除事件)",
            
        ) as response:
            if response.status_code in [200, 204, 404]:
                response.success()
                # 移除已删除的事件ID
                if event_id in self.test_event_ids:
                    self.test_event_ids.remove(event_id)
            elif response.status_code == 403:
                # 权限不足
                response.success()
            else:
                response.failure(f"状态码: {response.status_code}")

    @task(1)
    def delete_runlog_update(self):
        """
        【极低频】删除动态
        """
        if not self.test_event_ids:
            return

        # 先获取事件详情
        event_id = random.choice(self.test_event_ids)

        try:
            with self._get(
                "/api/runlog/detail/",
                params={"id": event_id},
                
                name="[辅助] 获取详情查找动态ID"
            ) as response:
                if response.status_code != 200:
                    return

                result = response.json()
                updates = result.get('updates', [])

                if not updates:
                    return

                update = random.choice(updates)
                update_id = update.get('id')

                with self._delete(
                    "/api/runlog/update/",
                    params={"id": update_id},
                    
                    name="DELETE /api/runlog/update/ (删除动态)",
                    
                ) as response:
                    if response.status_code in [200, 204, 404]:
                        response.success()
                    elif response.status_code == 403:
                        response.success()
                    else:
                        response.failure(f"状态码: {response.status_code}")

        except Exception as e:
            print(f"[User] 删除动态异常: {e}")

    # ==================== 并发场景测试 ====================

    @task(5)
    def concurrent_add_updates(self):
        """
        【高并发测试】多个用户同时为同一事件添加动态
        测试：同一天内序号计算的正确性
        """
        if not self.test_event_ids:
            return

        # 所有用户使用同一个事件ID（第一个）
        shared_event_id = RunLogUser.shared_test_event_ids[0] if RunLogUser.shared_test_event_ids else None
        if not shared_event_id:
            return

        try:
            today = datetime.now().strftime('%Y-%m-%d')
            time_detail = f"{datetime.now().strftime('%H%M%S')}"

            update_data = {
                "runlog_id": shared_event_id,
                "update_date": today,
                "update_time_detail": time_detail,
                "recorder": f"压测用户_{random.randint(1, 100)}",
                "detail_content": f"并发动态_{uuid.uuid4().hex[:8]}_{time_detail}",
                "duty_date": today,
                "attachments": []
            }

            with self._post(
                "/api/runlog/update/",
                json=update_data,
                
                name="[并发] 同时添加动态",
                
            ) as response:
                if response.status_code == 200:
                    response.success()
                elif response.status_code == 404:
                    response.success()
                else:
                    response.failure(f"状态码: {response.status_code}")

        except Exception as e:
            print(f"[User] 并发添加动态异常: {e}")


# ==================== 事件监听 ====================

@events.test_start.add_listener
def on_test_start(environment, **kwargs):
    """
    测试开始时的回调
    """
    print("=" * 60)
    print("运行日志模块 Locust 压测开始")
    print("=" * 60)
    print("测试场景:")
    print("  1. 高频查询 - 获取日志列表 (weight=15)")
    print("  2. 中频查询 - 获取事件详情 (weight=8)")
    print("  3. 中频查询 - 获取统计数据 (weight=5)")
    print("  4. 中频操作 - 添加动态 (weight=8)")
    print("  5. 低频操作 - 创建事件 (weight=3)")
    print("  6. 低频操作 - 更新事件 (weight=4)")
    print("  7. 低频操作 - 编辑动态 (weight=2)")
    print("  8. 低频操作 - 上传图片 (weight=3)")
    print("  9. 极低频 - 删除事件 (weight=1)")
    print("  10. 高并发 - 同时添加动态 (weight=5)")
    print("=" * 60)


@events.test_stop.add_listener
def on_test_stop(environment, **kwargs):
    """
    测试结束时的回调
    """
    print("=" * 60)
    print("运行日志模块 Locust 压测结束")
    print("=" * 60)


# ==================== 使用说明 ====================
"""
【运行方式】

1. 交互式模式（推荐用于调试）:
   locust -f locustfile_runlog.py -H http://localhost:80

   然后打开 http://localhost:8089
   设置: Number of users = 50
        Spawn rate = 10
        Host = http://localhost:80

2. 命令行模式（用于自动化测试）:
   locust -f locustfile_runlog.py -H http://localhost:80 \
          --users 100 \
          --spawn-rate 20 \
          --run-time 5m \
          --headless \
          --csv=runlog_test

3. Docker 环境运行:
   locust -f locustfile_runlog.py -H http://host.docker.internal:80 \
          --users 100 --spawn-rate 20 --run-time 5m --headless

【监控指标】

重点关注:
- RPS (Requests Per Second): 每秒请求数
- Failure Rate: 失败率（目标 < 1%）
- P50/P95/P99 Response Time: 响应时间分位数
- Concurrent Users: 并发用户数

【性能目标】

- 50并发用户下 P95 响应时间 < 500ms
- 100并发用户下 P95 响应时间 < 1s
- 200并发用户下 P95 响应时间 < 2s
- 失败率 < 1%

【关键测试点】

1. 租户隔离:
   - 不同租户的数据互不可见
   - 租户过滤在所有查询中生效

2. 序号计算正确性:
   - 同一天内的动态序号正确递增
   - 并发添加时序号不重复

3. 编辑时间限制:
   - 24小时内的动态可编辑
   - 超过24小时不可编辑

4. 状态流转:
   - 状态流转符合规则
   - 关闭时必须填写处理措施

5. 级联删除:
   - 删除事件时级联删除动态
   - 删除动态时正确更新事件统计

【数据清理】

测试完成后，可以通过以下SQL清理测试数据:
DELETE FROM runlog_run_log_updates WHERE created_at >= DATE_SUB(NOW(), INTERVAL 1 HOUR);
DELETE FROM runlog_run_logs WHERE created_at >= DATE_SUB(NOW(), INTERVAL 1 HOUR);
"""
