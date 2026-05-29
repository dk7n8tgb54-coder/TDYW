#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
干扰管理模块压力测试脚本
测试接口：
1. GET /api/interference/ - 获取干扰记录列表
2. POST /api/interference/ - 创建/更新干扰记录
3. DELETE /api/interference/ - 删除干扰记录
4. GET /api/interference/statistics/ - 获取统计数据
python -m locust -f locustfile/locustfile_interference.py -H http://localhost:80 --users 50 --spawn-rate 10 --run-time 5m --headless --csv interference_test

"""

from locust import HttpUser, task, between
import random
import time
from datetime import datetime, timedelta


class InterferenceUser(HttpUser):
    """干扰管理模块压力测试用户"""

    # 等待时间：1-3秒
    wait_time = between(1, 3)

    # 登录凭证（使用现有测试账号）
    username = "tongxinke"
    password = "Dt@6299093"
    user_type = "default"

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

    def on_start(self):
        """用户启动时执行：登录获取token"""
        self.client.verify = False  # 禁用SSL验证
        self.token = None
        login_success = self.login()
        print(f"[User] Login result: {login_success}, Token: {self.token[:10] if self.token else 'None'}...")
        # 不再使用created_ids缓存，每次操作前查询

    def login(self):
        """登录系统"""
        url = "/api/account/login/"
        data = {
            "username": self.username,
            "password": self.password,
            "type": self.user_type
        }
        headers = {
            "Content-Type": "application/json",
            "X-Requested-With": "XMLHttpRequest"
        }
        response = self.client.post(url, json=data, headers=headers, name="[准备] 登录")
        if response.status_code == 200:
            try:
                result = response.json()
                if isinstance(result, dict):
                    # 从data中获取access_token
                    token = result.get('data', {}).get('access_token')
                    if token:
                        self.token = token
                        self.client.headers.update({
                            'x-token': token,  # 使用x-token头部而不是Authorization: Bearer
                            'Content-Type': 'application/json'
                        })
                        print(f"[Login] 成功获取token: {token[:10]}...")
                        return True
                    else:
                        # 打印实际响应用于调试
                        print(f"[Login] 响应中没有access_token: {result}")
            except Exception as e:
                print(f"[Login] 解析响应失败: {e}")
        else:
            print(f"[Login] 登录失败: {response.status_code}, {response.text[:200]}")
        return False

    def check_and_relogin(self):
        """检查token是否有效，如果401则重新登录"""
        if not self.token:
            print(f"[Relogin] Token为空，重新登录")
            return self.login()
        return True

    @task(3)
    def get_interference_list(self):
        """获取干扰记录列表 (权重: 3)"""
        # 检查token有效性
        if not self.check_and_relogin():
            return

        url = "/api/interference/"
        with self.client.get(url, name="GET /api/interference/ (干扰记录列表)", catch_response=True) as response:
            try:
                if response.status_code == 200:
                    result = response.json()
                    error = result.get('error')
                    if error is None or error == '':
                        records = result.get('data', {}).get('records', [])
                        response.success()
                    else:
                        response.failure(f"业务错误: {error}")
                elif response.status_code == 401:
                    print(f"[List] 401未授权，尝试重新登录")
                    if self.login():
                        # 重新请求一次
                        retry_response = self.client.get(url, catch_response=True)
                        if retry_response.status_code == 200:
                            response.success()
                        else:
                            response.failure(f"重试后仍失败: {retry_response.status_code}")
                    else:
                        response.failure("重新登录失败")
                else:
                    response.failure(f"HTTP错误: {response.status_code}")
            except Exception as e:
                print(f"[List Exception] {e}")
                response.failure(f"异常: {str(e)}")

    @task(2)
    def create_interference(self):
        """创建干扰记录 (权重: 2)"""
        # 检查token有效性
        if not self.check_and_relogin():
            return

        url = "/api/interference/"

        # 生成随机数据（过去5年内均匀分配）
        now = datetime.now()
        total_days = 365 * 5  # 5年
        random_days = random.randint(0, total_days)
        random_hours = random.randint(0, 23)
        random_minutes = random.randint(0, 59)
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

        with self.client.post(url, json=data, name="POST /api/interference/ (创建干扰记录)", catch_response=True) as response:
            try:
                if response.status_code == 200:
                    result = response.json()
                    error = result.get('error')
                    if error is None or error == '':
                        # 尝试从响应中获取记录ID
                        created_data = result.get('data', {})
                        if isinstance(created_data, dict):
                            record_id = created_data.get('id')
                            if record_id and record_id not in self.created_ids:
                                self.created_ids.append(record_id)
                                print(f"[Create ID] 获取到ID: {record_id}, 当前ID数量: {len(self.created_ids)}")
                        elif isinstance(created_data, list) and created_data:
                            record_id = created_data[0].get('id')
                            if record_id and record_id not in self.created_ids:
                                self.created_ids.append(record_id)
                                print(f"[Create ID List] 获取到ID: {record_id}, 当前ID数量: {len(self.created_ids)}")
                        else:
                            print(f"[Create Debug] data字段类型: {type(created_data)}, 值: {created_data}")
                        response.success()
                    else:
                        print(f"[Create Error] error={error}, response={result}")
                        response.failure(f"业务错误: {error}")
                else:
                    print(f"[Create HTTP Error] status={response.status_code}")
                    response.failure(f"HTTP错误: {response.status_code}")
            except Exception as e:
                print(f"[Create Exception] {e}")
                response.failure(f"异常: {str(e)}")

    def get_random_record_id(self):
        """从列表中随机获取一个记录ID"""
        url = "/api/interference/"
        response = self.client.get(url)
        if response.status_code == 200:
            result = response.json()
            error = result.get('error')
            if error is None or error == '':
                records = result.get('data', {}).get('records', [])
                if records:
                    return random.choice(records).get('id')
        elif response.status_code == 401:
            print(f"[GetID] 401未授权，尝试重新登录")
            self.login()
        return None

    @task(1)
    def update_interference(self):
        """更新干扰记录 (权重: 1)"""
        # 检查token有效性
        if not self.check_and_relogin():
            return

        record_id = self.get_random_record_id()
        if not record_id:
            return

        url = "/api/interference/"
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

        with self.client.post(url, json=data, name="POST /api/interference/ (更新干扰记录)", catch_response=True) as response:
            try:
                if response.status_code == 200:
                    result = response.json()
                    error = result.get('error')
                    if error is None or error == '':
                        response.success()
                    else:
                        response.failure(f"业务错误: {error}")
                elif response.status_code == 401:
                    print(f"[Update] 401未授权，尝试重新登录")
                    if self.login():
                        # 重新请求一次
                        retry_response = self.client.post(url, json=data, catch_response=True)
                        if retry_response.status_code == 200:
                            response.success()
                        else:
                            response.failure(f"重试后仍失败: {retry_response.status_code}")
                    else:
                        response.failure("重新登录失败")
                else:
                    response.failure(f"HTTP错误: {response.status_code}")
            except Exception as e:
                response.failure(f"异常: {str(e)}")

    @task(1)
    def delete_interference(self):
        """删除干扰记录 (权重: 1)"""
        # 检查token有效性
        if not self.check_and_relogin():
            return

        record_id = self.get_random_record_id()
        if not record_id:
            return

        url = f"/api/interference/?id={record_id}"
        with self.client.delete(url, name="DELETE /api/interference/ (删除干扰记录)", catch_response=True) as response:
            try:
                if response.status_code == 200:
                    result = response.json()
                    error = result.get('error')
                    if error is None or error == '':
                        response.success()
                    else:
                        response.failure(f"业务错误: {error}")
                elif response.status_code == 401:
                    print(f"[Delete] 401未授权，尝试重新登录")
                    if self.login():
                        # 重新请求一次
                        retry_response = self.client.delete(url, catch_response=True)
                        if retry_response.status_code == 200:
                            response.success()
                        else:
                            response.failure(f"重试后仍失败: {retry_response.status_code}")
                    else:
                        response.failure("重新登录失败")
                else:
                    response.failure(f"HTTP错误: {response.status_code}")
            except Exception as e:
                response.failure(f"异常: {str(e)}")

    @task(1)
    def get_statistics(self):
        """获取统计数据 (权重: 1)"""
        # 检查token有效性
        if not self.check_and_relogin():
            return

        url = "/api/interference/statistics/"

        # 随机选择查询时间范围
        if random.random() < 0.3:
            # 30%概率使用自定义时间范围
            now = datetime.now()
            start_date = (now - timedelta(days=random.randint(30, 180))).strftime('%Y-%m-%d')
            end_date = (now - timedelta(days=random.randint(1, 29))).strftime('%Y-%m-%d')
            url = f"/api/interference/statistics/?start_date={start_date}&end_date={end_date}"

        with self.client.get(url, name="GET /api/interference/statistics/ (统计数据)", catch_response=True) as response:
            try:
                if response.status_code == 200:
                    result = response.json()
                    error = result.get('error')
                    if error is None or error == '':
                        response.success()
                    else:
                        print(f"[Stats Error] error={error}, response={result}")
                        response.failure(f"业务错误: {error}")
                elif response.status_code == 401:
                    print(f"[Stats] 401未授权，尝试重新登录")
                    if self.login():
                        # 重新请求一次
                        retry_response = self.client.get(url, catch_response=True)
                        if retry_response.status_code == 200:
                            response.success()
                        else:
                            response.failure(f"重试后仍失败: {retry_response.status_code}")
                    else:
                        response.failure("重新登录失败")
                else:
                    print(f"[Stats HTTP Error] status={response.status_code}")
                    response.failure(f"HTTP错误: {response.status_code}")
            except Exception as e:
                print(f"[Stats Exception] {e}")
                response.failure(f"异常: {str(e)}")
