#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
设备管理模块高并发压力测试
使用Locust进行压测，验证并发安全性和性能
"""

from locust import HttpUser, task, between, events
import random
import json
import time


class DeviceUser(HttpUser):
    """
    设备操作用户
    模拟真实用户的高并发操作
    """

    # 等待时间：0.1-0.5秒
    wait_time = between(0.1, 0.5)

    def on_start(self):
        """
        用户启动时执行
        登录获取Token
        """
        self.token = ""
        self.device_sn_prefix = f"TEST_{int(time.time())}"

        try:
            response = self.client.post(
                "/api/account/login/",
                json={
                    "username": "test_user",
                    "password": "test_password"
                }
            )
            if response.status_code == 200:
                data = response.json()
                self.token = data.get("token", "")
                print(f"用户登录成功，Token: {self.token[:20]}...")
            else:
                print(f"用户登录失败: {response.status_code}")
        except Exception as e:
            print(f"用户登录异常: {e}")

    def get_headers(self):
        """获取请求头"""
        headers = {}
        if self.token:
            headers["Authorization"] = f"Token {self.token}"
        return headers

    @task(10)
    def create_device(self):
        """
        创建设备（高频操作）
        测试全局唯一约束的并发安全性
        """
        headers = self.get_headers()

        # 使用相同的编号测试并发冲突
        device_sn = f"{self.device_sn_prefix}_CONCURRENT"

        try:
            response = self.client.post(
                "/api/exec/device-resume/",
                json={
                    "device_sn": device_sn,
                    "device_name": f"TestDevice_{random.randint(1, 1000)}",
                    "device_model": f"Model-{random.randint(1, 10)}",
                    "install_location": "测试地点",
                    "manufacturer": "测试厂商",
                    "install_unit": "测试单位",
                    "use_unit": "测试单位",
                    "install_time": "2026-01-01 00:00",
                    "enable_time": "2026-01-01 00:00",
                    "current_status": "1",
                    "responsible_user_id": "测试负责人"
                },
                headers=headers
            )

            # 201表示创建成功
            if response.status_code == 201:
                self.environment.events.request_success.fire(
                    request_type="POST",
                    name="create_device",
                    response_time=response.elapsed.total_seconds() * 1000,
                    response_length=len(response.content)
                )

            # 400表示编号已存在（预期行为）
            elif response.status_code == 400:
                self.environment.events.request_success.fire(
                    request_type="POST",
                    name="create_device_duplicate",
                    response_time=response.elapsed.total_seconds() * 1000,
                    response_length=len(response.content)
                )

            # 其他状态码视为失败
            else:
                self.environment.events.request_failure.fire(
                    request_type="POST",
                    name="create_device",
                    response_time=response.elapsed.total_seconds() * 1000,
                    exception=Exception(f"Unexpected Code: {response.status_code}")
                )

        except Exception as e:
            self.environment.events.request_failure.fire(
                request_type="POST",
                name="create_device",
                response_time=0,
                exception=e
            )

    @task(3)
    def list_devices(self):
        """
        查询设备列表
        测试查询性能
        """
        headers = self.get_headers()

        try:
            response = self.client.get(
                "/api/exec/device-resume/?page=1&page_size=20",
                headers=headers
            )

            if response.status_code == 200:
                self.environment.events.request_success.fire(
                    request_type="GET",
                    name="list_devices",
                    response_time=response.elapsed.total_seconds() * 1000,
                    response_length=len(response.content)
                )
            else:
                self.environment.events.request_failure.fire(
                    request_type="GET",
                    name="list_devices",
                    response_time=response.elapsed.total_seconds() * 1000,
                    exception=Exception(f"Code: {response.status_code}")
                )

        except Exception as e:
            self.environment.events.request_failure.fire(
                request_type="GET",
                name="list_devices",
                response_time=0,
                exception=e
            )

    @task(1)
    def delete_device(self):
        """
        删除设备（低频操作）
        测试删除的事务安全性
        """
        headers = self.get_headers()

        # 随机选择一个设备ID（需要替换为真实的设备ID范围）
        device_id = random.randint(1, 1000)

        try:
            response = self.client.delete(
                f"/api/exec/device-resume/?id={device_id}",
                headers=headers
            )

            if response.status_code == 200:
                self.environment.events.request_success.fire(
                    request_type="DELETE",
                    name="delete_device",
                    response_time=response.elapsed.total_seconds() * 1000,
                    response_length=len(response.content)
                )

            # 400表示设备不存在或无权限（预期行为）
            elif response.status_code == 400:
                self.environment.events.request_success.fire(
                    request_type="DELETE",
                    name="delete_device_not_found",
                    response_time=response.elapsed.total_seconds() * 1000,
                    response_length=len(response.content)
                )

            else:
                self.environment.events.request_failure.fire(
                    request_type="DELETE",
                    name="delete_device",
                    response_time=response.elapsed.total_seconds() * 1000,
                    exception=Exception(f"Code: {response.status_code}")
                )

        except Exception as e:
            self.environment.events.request_failure.fire(
                request_type="DELETE",
                name="delete_device",
                response_time=0,
                exception=e
            )


@events.test_stop.add_listener
def on_test_stop(environment, **kwargs):
    """
    测试结束后输出统计信息
    """
    print("\n" + "=" * 60)
    print("高并发测试完成")
    print("=" * 60)

    # 输出关键指标
    stats = environment.stats.total
    print(f"总请求数: {stats.num_requests}")
    print(f"失败请求数: {stats.num_failures}")
    print(f"成功率: {(1 - stats.num_failures / stats.num_requests) * 100:.2f}%")
    print(f"平均响应时间: {stats.avg_response_time:.2f}ms")
    print(f"中位数响应时间: {stats.median_response_time:.2f}ms")
    print(f"95分位响应时间: {stats.get_response_time_percentile(0.95):.2f}ms")


if __name__ == '__main__':
    # 使用说明
    print("""
    设备管理模块高并发压力测试
    ===========================

    使用方法:
    1. 安装Locust: pip install locust
    2. 运行测试: locust -f device_stress_test.py --host=http://your-api-server
    3. 访问Web界面: http://localhost:8089
    4. 设置参数:
       - 用户数: 100
       - 每秒启动用户: 10
       - 运行时间: 5分钟

    预期结果:
    - 创建设备同一编号时，只有1个成功，其余返回"编号已存在"
    - 所有请求成功率应>95%
    - 平均响应时间<100ms
    """)
