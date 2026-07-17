# -*- coding: utf-8 -*-
"""
创建资料库压测专用账号（Django shell 脚本）

运行方式（在 tdyw 容器内执行，stdin 喂入本文件）：
    docker exec -i tdyw python /data/spug/spug_api/manage.py shell < locustfile/tools/create_stress_accounts.py

作用：
  1. 创建一个专用租户隔离标识 tenant_id='stress'（仅逻辑隔离，无需建 Tenant 表行）。
  2. 创建一个“压测专用角色”，授予 document.document.* 所需权限
     （view / create_folder / upload / delete / download / move / copy / rename）。
  3. 创建 5 个专用账号 st_press_01..05，密码 Stress@2026，归属该角色与租户。
  幂等：重复执行不会建重。

【注意】生产 tdyw 压测采用“复用现有账号”策略，通常不需要跑本脚本。
本脚本仅用于 tdyw-test 等需要新建独立测试账号的环境。

权限码格式（与 User.page_perms 解析一致）：
  {"document": {"document": [<action>, ...]}}  ->  code = "document.document.<action>"
"""

import uuid
import json

from apps.account.models import User, Role

STRESS_TENANT = "stress"
STRESS_PASSWORD = "Stress@2026"
STRESS_USERNAMES = [f"st_press_0{i}" for i in range(1, 6)]

# document_auth 用到的操作，对应 code: document.document.<op>
DOC_ACTIONS = ["view", "create_folder", "upload", "delete",
               "download", "move", "copy", "rename"]
DOC_PERMS = {"document": {"document": DOC_ACTIONS}}


def main():
    superuser = User.objects.filter(is_supper=True).order_by("id").first()
    if not superuser:
        raise SystemExit("未找到超级管理员账号，无法设置 created_by")

    role, role_created = Role.objects.get_or_create(
        name="压测专用角色",
        tenant_id=STRESS_TENANT,
        defaults={
            "page_perms": json.dumps(DOC_PERMS),
            "created_by": superuser,
            "desc": "压测专用，仅授予资料库基础权限",
        },
    )
    if not role.page_perms:
        role.page_perms = json.dumps(DOC_PERMS)
        role.created_by = superuser
        role.save()
        print("更新角色权限: 压测专用角色")
    elif role_created:
        print("已创建角色: 压测专用角色")

    created, reused = [], []
    for uname in STRESS_USERNAMES:
        user, was_created = User.objects.get_or_create(
            username=uname,
            type="default",
            defaults={
                "nickname": uname,
                "password_hash": User.make_password(STRESS_PASSWORD),
                "tenant_id": STRESS_TENANT,
                "is_active": True,
                "access_token": uuid.uuid4().hex,  # CharField max_length=32
                "created_by": superuser,
            },
        )
        if was_created:
            user.roles.add(role)
            created.append(uname)
        else:
            reused.append(uname)

    print(f"创建账号: {created}")
    print(f"已存在(复用): {reused}")
    print(f"租户隔离标识: {STRESS_TENANT}")
    print(f"密码: {STRESS_PASSWORD}")
    print("请在 locustfile 脚本与 README 中保持账号/密码一致。")


main()
