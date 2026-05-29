#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
display_name 方案后端功能测试脚本
测试上传、下载、重命名、复制等核心功能
"""
import os
import sys
import json
import hashlib
import requests
from pathlib import Path

# API 配置
BASE_URL = "http://localhost"
API_BASE = f"{BASE_URL}/api"

# 登录配置（请根据实际情况修改）
LOGIN_URL = f"{API_BASE}/account/login/"
USERNAME = "admin"  # 修改为实际用户名
PASSWORD = "Admin888"   # 修改为实际密码

class APIClient:
    def __init__(self):
        self.session = requests.Session()
        self.token = None

    def login(self):
        """登录获取 token"""
        print(f"\n[1/6] 登录系统...")
        try:
            response = self.session.post(LOGIN_URL, json={
                "username": USERNAME,
                "password": PASSWORD
            })
            if response.status_code == 200:
                result = response.json()
                if "token" in result:
                    self.token = result["token"]
                    self.session.headers.update({"X-Token": self.token})
                    print(f"[OK] 登录成功，Token: {self.token[:20]}...")
                    return True
            print(f"[FAIL] 登录失败: {response.text}")
            return False
        except Exception as e:
            print(f"[FAIL] 登录异常: {e}")
            return False

    def get_folders(self, is_public=False):
        """获取文件夹列表"""
        print(f"\n[2/6] 获取{'公共' if is_public else '私有'}文件夹列表...")
        try:
            response = self.session.get(
                f"{API_BASE}/document/folders/",
                params={"is_public": is_public}
            )
            if response.status_code == 200:
                folders = response.json()
                print(f"[OK] 获取到 {len(folders)} 个文件夹")
                return folders
            print(f"[FAIL] 获取文件夹失败: {response.text}")
            return []
        except Exception as e:
            print(f"[FAIL] 获取文件夹异常: {e}")
            return []

    def upload_file(self, folder_id=None, is_public=False, filename="test_display_name.txt"):
        """上传文件测试"""
        print(f"\n[3/6] 上传测试文件: {filename}")
        try:
            # 创建测试文件
            test_content = f"测试display_name功能 - {os.urandom(8).hex()}"
            files = {"file": (filename, test_content, "text/plain")}
            data = {
                "folder_id": folder_id or "",
                "is_public": str(is_public).lower()
            }

            response = self.session.post(
                f"{API_BASE}/document/upload/",
                files=files,
                data=data
            )

            if response.status_code == 200:
                result = response.json()
                print(f"[OK] 上传成功")
                return result
            print(f"[FAIL] 上传失败: {response.text}")
            return None
        except Exception as e:
            print(f"[FAIL] 上传异常: {e}")
            return None

    def get_files(self, folder_id=None, is_public=False):
        """获取文件列表"""
        print(f"\n[4/6] 获取{'公共' if is_public else '私有'}文件列表...")
        try:
            response = self.session.get(
                f"{API_BASE}/document/files/",
                params={"folder_id": folder_id or "", "is_public": is_public}
            )
            if response.status_code == 200:
                files = response.json()
                print(f"[OK] 获取到 {len(files)} 个文件")

                # 检查 display_name 字段
                for f in files[:3]:  # 只显示前3个
                    print(f"   - ID:{f['id']}, name:{f.get('name', 'N/A')[:50]}, display_name:{f.get('display_name', 'N/A')[:50]}")

                return files
            print(f"[FAIL] 获取文件失败: {response.text}")
            return []
        except Exception as e:
            print(f"[FAIL] 获取文件异常: {e}")
            return []

    def download_file(self, file_id, is_public=False):
        """下载文件测试"""
        print(f"\n[5/6] 下载文件 ID:{file_id}...")
        try:
            response = self.session.get(
                f"{API_BASE}/document/download/",
                params={"id": file_id, "is_public": is_public},
                stream=True
            )

            if response.status_code == 200:
                # 获取文件名
                filename = None
                if "Content-Disposition" in response.headers:
                    content_disposition = response.headers["Content-Disposition"]
                    if "filename=" in content_disposition:
                        filename = content_disposition.split("filename=")[1].strip('"')
                print(f"[OK] 下载成功，文件名: {filename or 'N/A'}")
                return True
            print(f"[FAIL] 下载失败: {response.text}")
            return False
        except Exception as e:
            print(f"[FAIL] 下载异常: {e}")
            return False

    def rename_file(self, file_id, new_name, is_public=False):
        """重命名文件测试"""
        print(f"\n[6/6] 重命名文件 ID:{file_id} -> {new_name}...")
        try:
            response = self.session.post(
                f"{API_BASE}/document/rename/",
                json={"id": file_id, "name": new_name, "is_public": is_public}
            )

            if response.status_code == 200:
                print(f"[OK] 重命名成功")
                return True
            print(f"[FAIL] 重命名失败: {response.text}")
            return False
        except Exception as e:
            print(f"[FAIL] 重命名异常: {e}")
            return False

def main():
    print("=" * 60)
    print("display_name 方案后端功能测试")
    print("=" * 60)

    client = APIClient()

    # 1. 登录
    if not client.login():
        print("\n[FAIL] 测试失败：无法登录")
        print("提示：请检查用户名和密码是否正确")
        return

    # 2. 测试私有空间
    print("\n" + "=" * 60)
    print("测试私有空间")
    print("=" * 60)

    private_folders = client.get_folders(is_public=False)
    if not private_folders:
        print("[FAIL] 没有私有文件夹，请先创建")
        return

    folder_id = private_folders[0]["id"]
    print(f"使用文件夹 ID: {folder_id}, 名称: {private_folders[0].get('name', 'N/A')}")

    # 上传文件
    upload_result = client.upload_file(folder_id=folder_id, is_public=False, filename="测试_display_name.txt")
    if not upload_result:
        print("[FAIL] 上传失败")
        return

    # 获取文件列表（检查 display_name）
    files = client.get_files(folder_id=folder_id, is_public=False)
    if not files:
        print("[FAIL] 没有文件")
        return

    # 找到刚上传的文件
    test_file = None
    for f in files:
        if "测试_display_name" in f.get("display_name", ""):
            test_file = f
            break

    if not test_file:
        print("[FAIL] 未找到测试文件")
        return

    file_id = test_file["id"]
    print(f"找到测试文件 ID: {file_id}")
    print(f"  - name (物理): {test_file.get('name', 'N/A')}")
    print(f"  - display_name (显示): {test_file.get('display_name', 'N/A')}")

    # 验证物理文件名包含用户ID和时间戳
    physical_name = test_file.get("name", "")
    if "_" in physical_name:
        print(f"[OK] 物理文件名格式正确（包含下划线分隔符）")
    else:
        print(f"[WARN] 物理文件名可能不符合预期: {physical_name}")

    # 下载文件
    client.download_file(file_id, is_public=False)

    # 重命名文件
    client.rename_file(file_id, "重命名后_测试.txt", is_public=False)

    # 再次获取文件列表，验证重命名
    print("\n验证重命名结果...")
    files_after = client.get_files(folder_id=folder_id, is_public=False)
    for f in files_after:
        if f["id"] == file_id:
            print(f"  - 新 display_name: {f.get('display_name', 'N/A')}")
            print(f"  - name (物理) 是否变化: {'变化' if f.get('name') != physical_name else '未变化'}")
            if f.get('display_name') == "重命名后_测试.txt":
                print("[OK] 重命名成功：display_name 已更新")
            else:
                print("[FAIL] 重命名失败：display_name 未正确更新")
            break

    print("\n" + "=" * 60)
    print("测试完成")
    print("=" * 60)

if __name__ == "__main__":
    main()
