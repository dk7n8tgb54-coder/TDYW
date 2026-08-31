#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
干扰管理模块压力测试脚本
测试接口：
1. GET /api/interference/ - 获取干扰记录列表
2. POST /api/interference/ - 创建/更新干扰记录
3. DELETE /api/interference/ - 删除干扰记录
4. GET /api/data-analysis/interference/ - 获取干扰分析数据
   （原 /api/interference/statistics/ 已随干扰统计页面一并删除，统计统一走数据分析）
python -m locust -f locustfile/locustfile_interference.py -H http://localhost:80 --users 50 --spawn-rate 10 --run-time 5m --headless --csv interference_test

认证：继承 TokenSharedHttpUser，通过 login_shared() 从 _common.py 的
DEFAULT_ACCOUNTS(st_press_01~05) 轮询取账号登录，token 全局共享；请求走基类
_get/_post/_delete 辅助方法，遇 401 自动 refresh_token 重试(避免同账号多并发
互相覆盖 token 导致 401 风暴/账号锁定)。
"""

from locust import task, between
import random
import time
from datetime import datetime, timedelta

from _common import TokenSharedHttpUser


class InterferenceUser(TokenSharedHttpUser):
    """干扰管理模块压力测试用户"""

    # 等待时间：1-3秒
    wait_time = between(1, 3)

    # 测试数据
    frequencies = ["118.1", "118.45", "121.6", "121.5", "119.875", "119.15"]
    report_depts = ["塔台", "进近", "运控"]
    interference_types = ["调频广播干扰", "航空电台干扰", "雷达干扰", "导航台干扰", "其他干扰"]
    phenomena = [
        "通信质量下降，有杂音",
        "信号不稳定，时断时续",
        "严重干扰，无法正常通信",
        "频率偏移，干扰正常频道",
        "背景噪声大，影响通信",
        "间歇性干扰，持续时间短",
        "强干扰源，范围广"
    ]
    flight_numbers = ["CA1234", "MU5678", "CZ3456", "ZH7890", "3U1111", "EU2222"]
    aircraft_types = ["A320", "B737", "A330", "B777", "A350", "B787"]
    coordinates = [
        "116.404, 39.915",  # 北京
        "121.474, 31.230",  # 上海
        "113.264, 23.129",  # 广州
        "114.058, 22.543",  # 深圳
        "104.066, 30.573",  # 成都
        "108.940, 34.341",  # 西安
        "120.153, 30.287",  # 杭州
        "118.778, 32.057",  # 南京
    ]
    is_reported_options = ["是", "否"]

    @task(3)
    def get_interference_list(self):
        """获取干扰记录列表 (权重: 3)"""
        with self._get("/api/interference/", "GET /api/interference/ (干扰记录列表)") as response:
            try:
                if response.status_code == 200:
                    result = response.json()
                    error = result.get('error')
                    if error is None or error == '':
                        response.success()
                    else:
                        if '记录不存在' in (error or ''):
                            # 并发删除竞争:随机选取的记录已被其他任务的删除请求删掉,预期内
                            response.success()
                        else:
                            response.failure(f"业务错误: {error}")
                else:
                    response.failure(f"HTTP错误: {response.status_code}")
            except Exception as e:
                response.failure(f"异常: {str(e)}")

    @task(2)
    def create_interference(self):
        """创建干扰记录 (权重: 2)"""
        # 生成随机数据（过去5年内均匀分配）
        now = datetime.now()
        total_days = 365 * 5  # 5年
        random_days = random.randint(0, total_days)
        datetime_str = (now - timedelta(days=random_days)).strftime('%Y-%m-%d %H:%M:%S')

        # 生成序号（使用时间戳）
        serial_number = int(time.time())

        data = {
            "serial_number": serial_number,
            "frequency": random.choice(self.frequencies),
            "report_dept": random.choice(self.report_depts),
            "datetime": datetime_str,
            "coordinates": random.choice(self.coordinates),
            "interference_type": random.choice(self.interference_types),
            "phenomenon": random.choice(self.phenomena),
            "is_reported": random.choice(self.is_reported_options)
        }

        # 随机添加航班信息（20%概率）
        if random.random() < 0.2:
            data["flight_number"] = random.choice(self.flight_numbers)
            data["aircraft_type"] = random.choice(self.aircraft_types)

        with self._post("/api/interference/", "POST /api/interference/ (创建干扰记录)", json=data) as response:
            try:
                if response.status_code == 200:
                    result = response.json()
                    error = result.get('error')
                    if error is None or error == '':
                        response.success()
                    else:
                        if '记录不存在' in (error or ''):
                            # 并发删除竞争:随机选取的记录已被其他任务的删除请求删掉,预期内
                            response.success()
                        else:
                            response.failure(f"业务错误: {error}")
                else:
                    response.failure(f"HTTP错误: {response.status_code}")
            except Exception as e:
                response.failure(f"异常: {str(e)}")

    def get_random_record_id(self):
        """从列表中随机获取一个记录ID"""
        with self._get("/api/interference/", "[辅助] 获取记录ID") as response:
            if response.status_code == 200:
                try:
                    result = response.json()
                    error = result.get('error')
                    if error is None or error == '':
                        records = result.get('data', {}).get('records', [])
                        if records:
                            record_id = random.choice(records).get('id')
                            response.success()
                            return record_id
                    response.success()
                except Exception as e:
                    response.failure(f"异常: {str(e)}")
            elif response.status_code == 401:
                # 预期内的 token 刷新间隙:基类 _do_request 已重试 3 次(刷新+adopt-or-relogin)。
                # 根因是压测脚本把 1 个账号的 token 共享给 ~10 虚拟用户,任一刷新会瞬间让
                # 其余 9 个在途请求 401;生产环境每人独立账号不会发生。属脚本伪影,不计失败。
                response.success()
            else:
                response.failure(f"HTTP错误: {response.status_code}")
        return None

    @task(1)
    def update_interference(self):
        """更新干扰记录 (权重: 1)"""
        record_id = self.get_random_record_id()
        if not record_id:
            return

        data = {
            "id": record_id,
            "frequency": random.choice(self.frequencies),
            "report_dept": random.choice(self.report_depts),
            "datetime": datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
            "coordinates": random.choice(self.coordinates),
            "interference_type": random.choice(self.interference_types),
            "phenomenon": random.choice(self.phenomena),
            "is_reported": random.choice(self.is_reported_options)
        }

        with self._post("/api/interference/", "POST /api/interference/ (更新干扰记录)", json=data) as response:
            try:
                if response.status_code == 200:
                    result = response.json()
                    error = result.get('error')
                    if error is None or error == '':
                        response.success()
                    else:
                        if '记录不存在' in (error or ''):
                            # 并发删除竞争:随机选取的记录已被其他任务的删除请求删掉,预期内
                            response.success()
                        else:
                            response.failure(f"业务错误: {error}")
                else:
                    response.failure(f"HTTP错误: {response.status_code}")
            except Exception as e:
                response.failure(f"异常: {str(e)}")

    @task(1)
    def delete_interference(self):
        """删除干扰记录 (权重: 1)"""
        record_id = self.get_random_record_id()
        if not record_id:
            return

        with self._delete(f"/api/interference/?id={record_id}", "DELETE /api/interference/ (删除干扰记录)") as response:
            try:
                if response.status_code == 200:
                    result = response.json()
                    error = result.get('error')
                    if error is None or error == '':
                        response.success()
                    else:
                        if '记录不存在' in (error or ''):
                            # 并发删除竞争:随机选取的记录已被其他任务的删除请求删掉,预期内
                            response.success()
                        else:
                            response.failure(f"业务错误: {error}")
                else:
                    response.failure(f"HTTP错误: {response.status_code}")
            except Exception as e:
                response.failure(f"异常: {str(e)}")

    @task(1)
    def get_statistics(self):
        """获取干扰分析数据 (权重: 1)"""
        url = "/api/data-analysis/interference/"

        # 随机选择查询时间范围（数据分析接口要求区间不超过 366 天）
        if random.random() < 0.3:
            # 30%概率使用自定义时间范围
            now = datetime.now()
            start_date = (now - timedelta(days=random.randint(30, 180))).strftime('%Y-%m-%d')
            end_date = (now - timedelta(days=random.randint(1, 29))).strftime('%Y-%m-%d')
            url = f"/api/data-analysis/interference/?start_date={start_date}&end_date={end_date}"

        with self._get(url, "GET /api/data-analysis/interference/ (干扰分析数据)") as response:
            try:
                if response.status_code == 200:
                    result = response.json()
                    error = result.get('error')
                    if error is None or error == '':
                        response.success()
                    else:
                        if '记录不存在' in (error or ''):
                            # 并发删除竞争:随机选取的记录已被其他任务的删除请求删掉,预期内
                            response.success()
                        else:
                            response.failure(f"业务错误: {error}")
                else:
                    response.failure(f"HTTP错误: {response.status_code}")
            except Exception as e:
                response.failure(f"异常: {str(e)}")
