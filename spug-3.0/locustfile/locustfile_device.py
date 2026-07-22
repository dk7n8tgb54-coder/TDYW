"""
设备履历模块 Locust 压测脚本

使用说明:
1. 安装依赖: pip install locust
2. 运行测试: locust -f locustfile_device.py -H http://localhost:80
3. 打开浏览器访问: http://localhost:8089
4. 设置并发用户数和 spawn rate，开始测试
5.python -m locust -f locustfile/locustfile_device.py -H http://localhost:80 --users 50 --spawn-rate 10 --run-time 5m --headless --csv device_test

或者命令行直接运行:
locust -f locustfile_device.py -H http://localhost:80 --users 100 --spawn-rate 20 --run-time 5m --headless
"""

import random
import uuid
import logging
import threading
import time
from datetime import datetime, timedelta
from locust import task, between

from _common import TokenSharedHttpUser

logger = logging.getLogger(__name__)


class DeviceUser(TokenSharedHttpUser):
    """
    设备履历功能压测用户类
    模拟真实用户操作：查看设备列表、创建设备、编辑设备、查看履历事件、添加履历事件等

    认证：继承 TokenSharedHttpUser，on_start 时通过 login_shared() 从 _common.py 的
    DEFAULT_ACCOUNTS(st_press_01~05) 中轮询取一个账号登录，token 全局共享(避免同账号
    多并发互相覆盖导致 401 风暴/账号锁定)。401 时基类自动 refresh_token()。
    """

    # 请求间隔：0.5-1秒（平衡压力与性能测试）
    wait_time = between(0.5, 1)

    # 类变量：共享测试数据（所有用户共享）
    shared_test_device_ids = []
    test_data_prepared = False
    _lock = threading.Lock()

    def __init__(self, parent):
        super().__init__(parent)
        self.test_device_ids = []  # 当前用户创建的设备ID列表
        self.test_event_ids = []  # 当前用户的履历事件ID列表

    def on_start(self):
        """
        用户启动时执行：登录(基类 login_shared→self.token)并准备测试数据
        """
        super().on_start()
        self.prepare_test_data()

    def prepare_test_data(self):
        """
        准备测试数据：每个用户创建一些测试设备
        """
        try:
            with DeviceUser._lock:
                if DeviceUser.test_data_prepared:
                    print(f"[User] 使用已有测试数据，跳过创建")
                    self.load_existing_devices()
                    return

                print(f"[User] 我是第一个用户，开始创建测试数据...")
                DeviceUser.test_data_prepared = True

            # 创建10个测试设备
            for i in range(10):
                self._create_test_device()
                time.sleep(0.1)  # 避免创建过快

            print(f"[User] 测试数据准备完成，创建了 {len(self.test_device_ids)} 个设备")

            # 分享给其他用户
            with DeviceUser._lock:
                DeviceUser.shared_test_device_ids.extend(self.test_device_ids)

            # 为所有设备添加履历事件（每个设备20-40个随机事件）
            for device_id in self.test_device_ids:
                num_events = random.randint(20, 40)  # 每个设备20-40个事件
                for j in range(num_events):
                    self._create_test_event(device_id)
                    time.sleep(0.05)  # 减少延迟

            # 等待数据库写入完成
            time.sleep(1.0)
            self.load_existing_devices()

        except Exception as e:
            print(f"[User] 准备测试数据失败: {e}")

    def load_existing_devices(self):
        """加载现有的设备列表"""
        try:
            # 添加分页参数，确保返回格式一致
            params = {'page': 1, 'page_size': 100}
            with self._get(
                "/api/device/device-resume/",
                params=params,
                name="[准备] 获取设备列表",
            ) as response:
                if response.status_code == 200:
                    result = response.json()
                    # 后端返回结构兼容:
                    #   {"data": [...设备dict...], "total": N, ...}
                    #   {"data": {"records": [...], "total": N}}  (部分部署版本)
                    #   {"data": {"data": [...], ...}}            (双重包裹)
                    data = result.get('data') if isinstance(result, dict) else result
                    if isinstance(data, dict):
                        data = data.get('data') or data.get('records') or []
                    if not isinstance(data, list):
                        data = []
                    for device in data:
                        if not isinstance(device, dict):
                            continue
                        device_id = device.get('id')
                        if device_id and device_id not in self.test_device_ids:
                            self.test_device_ids.append(device_id)
                    print(f"[User] 加载到 {len(self.test_device_ids)} 个设备")
                    response.success()
                else:
                    print(f"[User] 加载设备列表失败: {response.status_code}")
                    response.failure(f"HTTP {response.status_code}")

        except Exception as e:
            print(f"[User] 加载设备列表失败: {e}")

    def _create_test_device(self):
        """创建一个测试设备"""
        try:
            install_time = (datetime.now() - timedelta(days=random.randint(365, 730))).strftime('%Y-%m-%d')
            enable_time = (datetime.now() - timedelta(days=random.randint(180, 365))).strftime('%Y-%m-%d')

            device_data = {
                "device_sn": f"TEST-{uuid.uuid4().hex[:10].upper()}",
                "device_name": f"测试设备_{random.randint(1, 1000)}",
                "device_model": random.choice(["Model-A", "Model-B", "Model-C", "Pro-X", "Ultra-Z"]),
                "frequency": f"{random.randint(118, 138)} MHz",
                "call_sign": f"TEST-{random.randint(1, 999)}",
                "install_location": random.choice(["机房A", "机房B", "通信站", "基站"]),
                "geo_coordinate": f"{random.uniform(116, 120):.4f},{random.uniform(30, 40):.4f}",
                "device_purpose": random.choice(["通信", "导航", "监控", "备份"]),
                "manufacturer": random.choice(["华为", "中兴", "诺基亚", "爱立信"]),
                "install_unit": "通信科",
                "use_unit": random.choice(["通信科", "自动化科", "导航科", "电话科"]),
                "install_time": install_time,
                "enable_time": enable_time,
                "current_status": random.choice(["1", "2", "3", "4", "5"]),  # 1=正常,2=故障,3=维修中,4=停用,5=报废
                "responsible_user_id": "测试责任人",
                "remark": "压力测试自动生成"
            }

            with self._post(
                "/api/device/device-resume/",
                json=device_data,
                name="[准备] 创建测试设备"
            ) as response:
                if response.status_code == 200:
                    try:
                        result = response.json()
                        device_id = (result.get('data') or {}).get('id')
                        if device_id:
                            self.test_device_ids.append(device_id)
                            print(f"[User] 测试设备创建成功，ID: {device_id}")
                        else:
                            print(f"[User] 测试设备创建成功，但响应中没有ID: {result}")
                    except:
                        print(f"[User] 测试设备创建成功，需要通过列表查询ID")
                    response.success()
                else:
                    print(f"[User] 创建测试设备失败: {response.status_code} - {response.text[:200]}")
                    response.failure(f"HTTP {response.status_code}")
                return response.status_code == 200

        except Exception as e:
            print(f"[User] 创建测试设备异常: {e}")
            return False

    def _create_test_event(self, device_id):
        """创建一个测试履历事件"""
        try:
            event_time = (datetime.now() - timedelta(days=random.randint(0, 365))).strftime('%Y-%m-%d %H:%M')

            # 随机选择事件类型：1=重大故障维修，2=设备更新，3=设备检修
            event_type = random.choice([1, 2, 3])
            event_titles = {
                1: ["重大故障维修", "紧急抢修", "硬件更换", "系统故障"],
                2: ["设备升级", "配置变更", "系统更新", "软件补丁"],
                3: ["定期巡检", "性能测试", "设备维护", "状态检查"]
            }
            event_title = random.choice(event_titles[event_type])

            event_data = {
                "device_resume_id": device_id,
                "event_type": event_type,
                "event_time": event_time,
                "event_title": event_title,
                "related_user_id": f"测试人员{random.randint(1, 10)}"
            }

            # 设备检修（type=3）需要额外字段
            if event_type == 3:
                event_data.update({
                    "fault_part": random.choice(["主板", "电源", "天线", "线缆", "模块", "显示屏"]),
                    "fault_phenomenon_cause": random.choice(["信号中断", "性能下降", "过热", "异响", "连接不稳定"]),
                    "maintenance_measures": random.choice(["更换部件", "调试参数", "重启设备", "清洁维护", "软件升级"]),
                    "repair_time": (datetime.now() - timedelta(days=random.randint(0, 30))).strftime('%Y-%m-%d %H:%M')
                })

            with self._post(
                "/api/device/device-event/",
                json=event_data,
                name="[准备] 创建测试事件"
            ) as response:
                if response.status_code == 200:
                    try:
                        result = response.json()
                        event_id = (result.get('data') or {}).get('id')
                        if event_id:
                            self.test_event_ids.append(event_id)
                            print(f"[User] 测试事件创建成功，ID: {event_id}")
                        else:
                            print(f"[User] 测试事件创建成功，但响应中没有ID: {result}")
                    except:
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

    @task(20)
    def get_device_list(self):
        """
        【高频】获取设备履历列表 - 最频繁的操作
        """
        params = {
            'page': random.randint(1, 10),
            'page_size': 20
        }

        # 随机添加筛选条件
        if random.random() < 0.4:
            params['current_status'] = random.choice([["1", "2"], ["3"], ["1"]])  # 1=正常,2=故障,3=维修中
        if random.random() < 0.3:
            params['use_unit'] = random.choice(["通信科", "自动化科", "导航科", "电话科"])
        if random.random() < 0.3:
            params['manufacturer'] = random.choice(["华为", "中兴", "诺基亚"])

        with self._get(
            "/api/device/device-resume/",
            params=params,
            name="GET /api/device/device-resume/ (设备列表)",
        ) as response:
            if response.status_code == 200:
                response.success()
            else:
                response.failure(f"状态码: {response.status_code}")

    @task(10)
    def get_device_detail(self):
        """
        【中频】获取设备详情
        """
        if not self.test_device_ids:
            return

        device_id = random.choice(self.test_device_ids)

        with self._get(
            "/api/device/device-resume/",
            params={"id": device_id},
            name="GET /api/device/device-resume/ (设备详情)",
        ) as response:
            if response.status_code == 200:
                response.success()
            elif response.status_code == 404:
                # 设备可能已被删除，移除ID
                if device_id in self.test_device_ids:
                    self.test_device_ids.remove(device_id)
                response.success()
            else:
                response.failure(f"状态码: {response.status_code}")

    @task(8)
    def get_event_list(self):
        """
        【中频】获取履历事件列表
        """
        if not self.test_device_ids:
            return

        device_id = random.choice(self.test_device_ids)

        params = {
            'device_resume_id': device_id,
            'page': random.randint(1, 5),
            'page_size': 20
        }

        # 随机添加事件类型筛选
        if random.random() < 0.3:
            params['event_type'] = random.choice([1, 2, 3])  # 1=重大故障维修,2=设备更新,3=设备检修

        with self._get(
            "/api/device/device-event/",
            params=params,
            name="GET /api/device/device-event/ (履历事件列表)",
        ) as response:
            if response.status_code == 200:
                response.success()
            else:
                response.failure(f"状态码: {response.status_code}")

    @task(5)
    def get_use_units(self):
        """
        【低频】获取使用单位列表（用于筛选）
        """
        with self._get(
            "/api/device/device-resume/",
            params={"use_units": "true"},
            name="GET /api/device/device-resume/ (使用单位列表)",
        ) as response:
            if response.status_code == 200:
                response.success()
            else:
                response.failure(f"状态码: {response.status_code}")

    @task(3)
    def get_device_models(self):
        """
        【低频】获取设备型号列表（用于筛选）
        """
        with self._get(
            "/api/device/device-resume/",
            params={"device_models": "true"},
            name="GET /api/device/device-resume/ (设备型号列表)",
        ) as response:
            if response.status_code == 200:
                response.success()
            else:
                response.failure(f"状态码: {response.status_code}")

    # ==================== 写入任务 ====================

    @task(3)
    def create_device(self):
        """
        【低频】创建设备
        """
        install_time = (datetime.now() - timedelta(days=random.randint(365, 730))).strftime('%Y-%m-%d')
        enable_time = (datetime.now() - timedelta(days=random.randint(180, 365))).strftime('%Y-%m-%d')

        device_data = {
            "device_sn": f"TEST-{uuid.uuid4().hex[:10].upper()}",
            "device_name": f"压测设备_{random.randint(1, 10000)}",
            "device_model": random.choice(["Model-A", "Model-B", "Model-C", "Pro-X", "Ultra-Z"]),
            "frequency": f"{random.randint(118, 138)} MHz",
            "call_sign": f"TEST-{random.randint(1, 999)}",
            "install_location": random.choice(["机房A", "机房B", "通信站", "基站"]),
            "geo_coordinate": f"{random.uniform(116, 120):.4f},{random.uniform(30, 40):.4f}",
            "device_purpose": random.choice(["通信", "导航", "监控", "备份"]),
            "manufacturer": random.choice(["华为", "中兴", "诺基亚", "爱立信"]),
            "install_unit": "通信科",
            "use_unit": random.choice(["通信科", "自动化科", "导航科", "电话科"]),
            "install_time": install_time,
            "enable_time": enable_time,
            "current_status": random.choice(["1", "2", "3", "4", "5"]),  # 1=正常,2=故障,3=维修中,4=停用,5=报废
            "responsible_user_id": "压测责任人",
            "remark": "压测自动生成"
        }

        with self._post(
            "/api/device/device-resume/",
            json=device_data,
            name="POST /api/device/device-resume/ (创建设备)",
        ) as response:
            if response.status_code == 200:
                try:
                    result = response.json()
                    device_id = (result.get('data') or {}).get('id')
                    if device_id:
                        self.test_device_ids.append(device_id)
                except:
                    pass
                response.success()
            else:
                response.failure(f"状态码: {response.status_code}")

    @task(5)
    def create_event(self):
        """
        【中频】创建履历事件
        """
        if not self.test_device_ids:
            return

        device_id = random.choice(self.test_device_ids)
        event_time = (datetime.now() - timedelta(days=random.randint(0, 365))).strftime('%Y-%m-%d %H:%M')

        # 随机选择事件类型：1=重大故障维修，2=设备更新，3=设备检修
        event_type = random.choice([1, 2, 3])
        event_titles = {
            1: ["重大故障维修", "紧急抢修", "硬件更换", "系统故障"],
            2: ["设备升级", "配置变更", "系统更新", "软件补丁"],
            3: ["定期巡检", "性能测试", "设备维护", "状态检查"]
        }
        event_title = random.choice(event_titles[event_type])

        event_data = {
            "device_resume_id": device_id,
            "event_type": event_type,
            "event_time": event_time,
            "event_title": event_title,
            "related_user_id": f"压测人员{random.randint(1, 10)}"
        }

        # 设备维修（type=3）需要额外字段
        if event_type == 3:
            event_data.update({
                "fault_part": random.choice(["主板", "电源", "天线", "线缆", "模块"]),
                "fault_phenomenon_cause": random.choice(["信号中断", "性能下降", "过热", "异响"]),
                "maintenance_measures": random.choice(["更换部件", "调试参数", "重启设备", "清洁维护"]),
                "repair_time": (datetime.now() - timedelta(days=random.randint(0, 30))).strftime('%Y-%m-%d %H:%M')
            })

        with self._post(
            "/api/device/device-event/",
            json=event_data,
            name="POST /api/device/device-event/ (创建履历事件)",
        ) as response:
            if response.status_code == 200:
                try:
                    result = response.json()
                    event_id = (result.get('data') or {}).get('id')
                    if event_id:
                        self.test_event_ids.append(event_id)
                except:
                    pass
                response.success()
            else:
                # 设备编号重复是预期内的，不算失败
                if response.status_code == 400 and "设备资产编号已存在" in response.text:
                    response.success()
                else:
                    response.failure(f"状态码: {response.status_code}")

    @task(2)
    def update_device(self):
        """
        【低频】更新设备信息
        """
        if not self.test_device_ids:
            return

        device_id = random.choice(self.test_device_ids)

        device_data = {
            "id": device_id,
            "device_name": f"更新设备_{random.randint(1, 10000)}",
            "device_model": random.choice(["Model-A", "Model-B", "Model-C", "Pro-X", "Ultra-Z"]),
            "install_location": random.choice(["机房A", "机房B", "通信站", "基站"]),
            "manufacturer": random.choice(["华为", "中兴", "诺基亚", "爱立信"]),
            "install_unit": "通信科",
            "use_unit": random.choice(["通信科", "自动化科", "导航科", "电话科"]),
            "install_time": (datetime.now() - timedelta(days=random.randint(365, 730))).strftime('%Y-%m-%d'),
            "enable_time": (datetime.now() - timedelta(days=random.randint(180, 365))).strftime('%Y-%m-%d'),
            "current_status": random.choice(["1", "2", "3", "4", "5"]),  # 1=正常,2=故障,3=维修中,4=停用,5=报废
            "responsible_user_id": f"更新责任人{random.randint(1, 10)}"
        }

        with self._put(
            "/api/device/device-resume/",
            json=device_data,
            name="PUT /api/device/device-resume/ (更新设备)",
        ) as response:
            if response.status_code in [200, 404]:
                # 404表示设备可能已被删除，也算成功
                response.success()
            else:
                response.failure(f"状态码: {response.status_code}")

    @task(1)
    def delete_device(self):
        """
        【低频】删除设备（测试删除性能）
        """
        if not self.test_device_ids or len(self.test_device_ids) < 5:
            # 保留至少5个设备用于其他操作
            return

        # 随机选择一个设备ID删除
        device_id = random.choice(self.test_device_ids[:10])  # 优先删除旧的设备

        with self._delete(
            "/api/device/device-resume/",
            params={"id": device_id},
            name="DELETE /api/device/device-resume/ (删除设备)",
        ) as response:
            if response.status_code in [200, 404]:
                # 成功或设备不存在（可能已被其他用户删除）
                if device_id in self.test_device_ids:
                    self.test_device_ids.remove(device_id)
                response.success()
            else:
                response.failure(f"状态码: {response.status_code}")
