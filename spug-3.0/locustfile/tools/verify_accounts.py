#!/usr/bin/env python3
"""快速验证压测账号能否登录"""
import requests, json

for user in ["st_press_01", "st_press_02", "st_press_03", "st_press_04", "st_press_05"]:
    r = requests.post("http://localhost/api/account/login/", json={
        "username": user, "password": "Stress@2026", "type": "default"
    })
    d = r.json()
    if d.get("error"):
        print(f"{user}: ERROR - {d['error']}")
    else:
        token = d["data"]["access_token"]
        print(f"{user}: OK (token={token[:16]}...)")
