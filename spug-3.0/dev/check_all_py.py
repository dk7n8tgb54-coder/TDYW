import py_compile, os

APPS = ['account', 'device', 'document', 'duty', 'evidence', 'interference',
        'logs', 'runlog', 'signature', 'setting', 'department_duty_log']

base = '/data/spug/spug_api/apps'
for app in APPS:
    app_dir = os.path.join(base, app)
    errors = []
    for root, dirs, files in os.walk(app_dir):
        for f in files:
            if f.endswith('.py'):
                path = os.path.join(root, f)
                try:
                    py_compile.compile(path, doraise=True)
                except py_compile.PyCompileError as e:
                    errors.append(f'{path}: {e}')
    if errors:
        for e in errors:
            print(f'FAIL: {e}')
    else:
        print(f'{app}: OK')
