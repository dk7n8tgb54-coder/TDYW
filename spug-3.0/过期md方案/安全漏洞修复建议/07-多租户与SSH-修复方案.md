# 🟡 P2-修复方案：多租户隔离与SSH安全

> 对应漏洞：`安全漏洞分析/07-多租户隔离风险.md` (#13)、`安全漏洞分析/08-远程执行安全.md` (#14)

---

## 修复项 #13：完善多租户自动过滤

### 涉及文件
- `spug_api/libs/tenant_middleware.py`

### 修改方案

将空实现的 `TenantQuerySet` 替换为可用的 `TenantManager`：

**修改前（第63-85行 TenantQuerySet 空实现）：**
```python
class TenantQuerySet:
    def __init__(self, model=None, query=None, using=None, hints=None):
        from django.db.models import QuerySet
        self.queryset = QuerySet(model=model, query=query, using=using, hints=hints)

    def __getattr__(self, name):
        attr = getattr(self.queryset, name)
        if callable(attr):
            def wrapper(*args, **kwargs):
                current_tenant = get_current_tenant()
                if current_tenant:
                    if name in ['filter', 'get', 'all', 'first', 'last', 'exclude']:
                        if 'tenant_id' not in kwargs and hasattr(args[0] if args else None, '__contains__'):
                            pass  # 空实现
                return attr(*args, **kwargs)
            return wrapper
        return attr
```

**修改后（替换为 TenantManager）：**
```python
from django.db import models


class TenantManager(models.Manager):
    """
    Custom Manager that automatically applies tenant filtering.
    
    Usage in models:
        class MyModel(models.Model):
            tenant_id = models.CharField(max_length=50, db_index=True)
            objects = TenantManager()           # Auto-filtered by tenant
            all_objects = models.Manager()      # No filtering (admin use)
    """

    def get_queryset(self):
        qs = super().get_queryset()
        tenant_id = get_current_tenant()
        if tenant_id and hasattr(self.model, 'tenant_id'):
            return qs.filter(tenant_id=tenant_id)
        return qs


class TenantModel(models.Model):
    """
    Abstract base model with tenant isolation.
    Inherit from this for automatic tenant filtering.
    """
    tenant_id = models.CharField(max_length=50, db_index=True, default='default')

    objects = TenantManager()
    all_objects = models.Manager()  # Unfiltered for admin operations

    class Meta:
        abstract = True

    def save(self, *args, **kwargs):
        if not self.tenant_id:
            current_tenant = get_current_tenant()
            if current_tenant:
                self.tenant_id = current_tenant
        super().save(*args, **kwargs)
```

### 使用方式

现有模型可逐步迁移：
```python
from libs.tenant_middleware import TenantManager

class DocumentFilePrivate(models.Model):
    tenant_id = models.CharField(max_length=50, db_index=True)
    # ... other fields ...
    
    objects = TenantManager()           # Auto-filtered
    all_objects = models.Manager()      # For admin/migration
```

---

## 修复项 #14：SSH改用WarningPolicy

### 涉及文件
- `spug_api/libs/ssh.py`

### 修改方案

**修改前（第83-89行）：**
```python
def get_client(self):
    if self.client is not None:
        return self.client
    self.client = SSHClient()
    self.client.set_missing_host_key_policy(AutoAddPolicy)
    self.client.connect(**self.arguments)
    return self.client
```

**修改后：**
```python
import os
import logging

logger = logging.getLogger(__name__)

class SSH:
    # Known hosts file for Trust On First Use (TOFU)
    KNOWN_HOSTS_FILE = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        'storage', 'known_hosts'
    )

    # ... existing __init__ ...

    def get_client(self):
        if self.client is not None:
            return self.client
        self.client = SSHClient()

        # Load known hosts if available (TOFU pattern)
        if os.path.exists(self.KNOWN_HOSTS_FILE):
            try:
                self.client.load_host_keys(self.KNOWN_HOSTS_FILE)
            except Exception as e:
                logger.warning(f'[SSH] Failed to load known_hosts: {e}')

        # WarningPolicy: logs warning for unknown hosts but still connects
        # Better than AutoAddPolicy (silent) but less strict than RejectPolicy
        from paramiko.client import WarningPolicy
        self.client.set_missing_host_key_policy(WarningPolicy)

        self.client.connect(**self.arguments)

        # Save host key after successful connection
        try:
            os.makedirs(os.path.dirname(self.KNOWN_HOSTS_FILE), exist_ok=True)
            self.client.save_host_keys(self.KNOWN_HOSTS_FILE)
        except Exception as e:
            logger.warning(f'[SSH] Failed to save known_hosts: {e}')

        return self.client
```

### 需要在文件顶部添加导入

```python
import os
import logging

logger = logging.getLogger(__name__)
```

---

## 验证修复

```bash
# 1. Verify TenantManager works
python -c "
import os, sys
sys.path.insert(0, 'spug_api')
os.environ['DJANGO_SETTINGS_MODULE'] = 'spug.settings'
import django; django.setup()
from libs.tenant_middleware import TenantManager, set_current_tenant
set_current_tenant('test')
print('TenantManager available:', TenantManager is not None)
"

# 2. Verify SSH uses WarningPolicy
grep -n "AutoAddPolicy\|WarningPolicy" spug_api/libs/ssh.py
# Expected: WarningPolicy only
```
