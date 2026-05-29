#!/usr/bin/env python
# -*- coding: utf-8 -*-
import os
import subprocess
import sys

# Set UTF-8 encoding for Windows console
if sys.platform == 'win32':
    sys.stdout.reconfigure(encoding='utf-8')

# Files to copy to Docker container
files_to_copy = [
    ('spug_api/apps/notify/views.py', '/data/spug/spug_api/apps/notify/views.py'),
    ('spug_api/apps/document/views.py', '/data/spug/spug_api/apps/document/views.py'),
    ('spug_api/apps/app/views.py', '/data/spug/spug_api/apps/app/views.py'),
    ('spug_api/apps/app/utils.py', '/data/spug/spug_api/apps/app/utils.py'),
]

# Check if files exist
print("Checking files...")
for src, dst in files_to_copy:
    if os.path.exists(src):
        print(f"  [OK] {src}")
    else:
        print(f"  [MISSING] {src} NOT FOUND")

# Copy files
print("\nCopying files to Docker container...")
for src, dst in files_to_copy:
    if os.path.exists(src):
        cmd = f'docker cp "{os.path.abspath(src)}" spug:"{dst}"'
        print(f"  Running: {cmd}")
        result = subprocess.run(cmd, shell=True, capture_output=True, text=True)
        if result.returncode == 0:
            print(f"  [OK] Copied {src}")
        else:
            print(f"  [FAILED] Failed to copy {src}")
            print(f"    Error: {result.stderr}")
    else:
        print(f"  [SKIPPED] Skipping {src} (not found)")

print("\nDone! Restarting spug container...")
result = subprocess.run('docker restart spug', shell=True, capture_output=True, text=True)
if result.returncode == 0:
    print("  [OK] Container restarted")
else:
    print(f"  [FAILED] Failed to restart: {result.stderr}")
