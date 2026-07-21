#!/usr/bin/env python
"""清除登录失败计数,解锁压测账号"""
from django.core.cache import cache

users = [f"st_press_0{n}" for n in range(1, 6)] + ["admin"]
cleared = 0
for u in users:
    key = f"login_fail:user:{u}"
    if cache.get(key) is not None:
        cache.delete(key)
        print(f"  cleared: {key}")
        cleared += 1
    else:
        print(f"  ok (no lock): {key}")

# 同时清 IP 级限流(localhost)
ip_key = "login_fail:ip:127.0.0.1"
if cache.get(ip_key) is not None:
    cache.delete(ip_key)
    print(f"  cleared: {ip_key}")
    cleared += 1

print(f"\nDone. {cleared} keys cleared. All accounts unlocked.")
