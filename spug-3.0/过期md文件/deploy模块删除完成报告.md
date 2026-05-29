# deploy模块删除完成报告

**删除时间**: 2026-03-11  
**操作类型**: 完全删除deploy模块及其相关依赖

---

## 一、已删除的模块和文件

### 1.1 deploy模块（完全删除）
```
e:/TDYW/spug-3.0/spug_api/apps/deploy/
├── __init__.py
├── models.py          # DeployRequest, DeployExtend1, DeployExtend2模型
├── views.py          # 发布申请、审批、执行相关视图
├── urls.py           # deploy相关路由
├── helper.py         # 辅助工具类（通知、日志、SSH执行）
└── utils.py          # 核心部署逻辑（dispatch函数）
```

### 1.2 repository模块（完全删除）
```
e:/TDYW/spug-3.0/spug_api/apps/repository/
├── __init__.py
├── models.py         # Repository模型
├── views.py         # 构建仓库相关视图
├── urls.py          # repository相关路由
└── utils.py         # 构建工具函数
```

### 1.3 其他删除文件
- `spug_api/apps/apis/deploy.py` - 自动部署Webhook处理
- `spug_api/apps/apis/urls.py` - 删除deploy路由
- `spug_api/apps/account/management/commands/clean_deploy.py` - 清理deploy权限命令
- `spug_api/apps/account/management/commands/check_deploy.py` - 检查deploy权限命令

---

## 二、已修改的文件

### 2.1 配置文件

#### spug_api/spug/settings.py
**删除内容**:
- `'apps.deploy'` - 从INSTALLED_APPS中移除
- `'apps.repository'` - 从INSTALLED_APPS中移除
- `REQUEST_KEY = 'spug:request'` - 发布请求Redis key
- `BUILD_KEY = 'spug:build'` - 构建Redis key
- `REPOS_DIR = ...` - 仓库目录路径
- `BUILD_DIR = ...` - 构建目录路径

#### spug_api/spug/urls.py
**删除内容**:
- `path('deploy/', include('apps.deploy.urls'))`
- `path('repository/', include('apps.repository.urls'))`

### 2.2 app模块

#### spug_api/apps/app/models.py
**删除内容**:
- `Deploy` 模型（包括EXTENDS选择、app、env、host_ids等字段）
- `DeployExtend1` 模型（常规发布扩展）
- `DeployExtend2` 模型（自定义发布扩展）

**保留内容**:
- `App` 模型（应用基础信息）

#### spug_api/apps/app/views.py
**删除内容**:
- `DeployView` 类及其所有方法（get、post、delete）
- `get_versions` 函数
- `kit_key` 函数
- 所有`@auth('deploy.*')`权限装饰器
- `DeployExtend1`, `DeployExtend2` 的导入
- `fetch_versions`, `remove_repo` 的导入
- `F` from django.db.models 的导入

**修改内容**:
- `AppView.get()` - 移除deploy_perms权限检查
- `AppView.post()` - 修改权限装饰器从`deploy.app.add|deploy.app.edit|config.app.add|config.app.edit`到`config.app.add|config.app.edit`
- `AppView.patch()` - 修改权限装饰器从`deploy.app.edit|config.app.edit_config`到`config.app.edit_config`
- `AppView.delete()` - 移除Deploy关联检查，修改权限从`deploy.app.del|config.app.del`到`config.app.del`

#### spug_api/apps/app/urls.py
**删除内容**:
- `path('kit/key/', kit_key)`
- `path('deploy/', DeployView.as_view())`
- `path('deploy/<int:d_id>/versions/', get_versions)`

### 2.3 account模块

#### spug_api/apps/account/models.py
**删除内容**:
- `deploy_perms` 属性方法（返回apps和envs权限集）

**影响**:
- User模型不再包含deploy_perms权限检查
- 权限系统简化，只保留page_perms和group_perms

#### spug_api/apps/account/models.py (Role模型)
**保留内容**:
- `page_perms` 字段
- `deploy_perms` 字段（保留用于向后兼容，但不再使用）
- `group_perms` 字段

### 2.4 schedule模块

#### spug_api/apps/schedule/builtin.py
**删除内容**:
- `DeployRequest` 导入
- `DeployExtend1` 导入
- `Repository` 导入
- `dispatch` 导入
- `parse_time` 导入
- `human_datetime` 导入
- `Thread` 导入
- `auto_run_by_day()` 中的DeployExtend1和DeployRequest清理逻辑
- `auto_run_by_minute()` 中的DeployRequest和Repository超时检查逻辑

**保留内容**:
- `History` 清理（30天前）
- `Notify` 清理（7天前未读）
- `ExecHistory` 清理（保留最近10条）
- `Transfer` 清理（保留最近10条）
- `TaskHistory` 清理（保留最近50条）
- `TRANSFER_DIR` 清理（2小时未访问）

### 2.5 config模块

#### spug_api/apps/config/views.py
**删除内容**:
- `Deploy` 导入
- `Repository` 导入
- `EnvironmentView.get()` 中的deploy_perms权限检查
- `EnvironmentView.delete()` 中的Deploy和Repository关联检查

**修改内容**:
- `EnvironmentView.get()` - 移除deploy_perms权限过滤，所有用户都可查看环境

### 2.6 apis模块

#### spug_api/apps/apis/urls.py
**删除内容**:
- `from apps.apis import deploy`
- `path('deploy/<int:deploy_id>/<str:kind>/', deploy.auto_deploy)`

---

## 三、功能影响分析

### 3.1 已删除的功能
1. **应用发布系统** - 完整的CI/CD发布功能
2. **发布申请管理** - 申请、审批、执行、回滚
3. **Git仓库集成** - 自动拉取、构建、部署
4. **自定义脚本发布** - 服务器端和主机端动作
5. **构建仓库管理** - 版本管理和存储
6. **自动部署Webhook** - GitLab/GitHub/Gitee等触发器
7. **发布权限系统** - 基于apps和envs的细粒度权限

### 3.2 保留的功能
1. **应用管理** - App模型的基础信息管理
2. **环境管理** - Environment模型的环境配置
3. **配置中心** - Config和Service的配置管理
4. **服务管理** - Service模型的服务配置

### 3.3 受影响的模块
1. **app模块** - 只保留应用基础管理，移除发布相关功能
2. **config模块** - 环境不再受deploy权限限制
3. **account模块** - 权限系统简化
4. **schedule模块** - 定时任务中不再包含deploy相关逻辑

---

## 四、数据库表说明

### 4.1 相关数据库表（需手动清理）
以下表与deploy模块相关，可能需要清理：
- `deploy_requests` - 发布申请记录
- `deploy_extend1` - 常规发布扩展配置
- `deploy_extend2` - 自定义发布扩展配置
- `deploys` - 发布配置
- `repositories` - 构建仓库记录

**建议**:
- 如果需要保留数据，可以备份这些表
- 如果不再需要，可以删除这些表
- Django的migrate不会自动删除表，需要手动处理

### 4.2 Role模型中的字段
- `deploy_perms` 字段保留但不再使用
- 建议运行清理脚本清空该字段的值

---

## 五、后续操作建议

### 5.1 数据库清理
```sql
-- 可选：删除deploy相关表
DROP TABLE IF EXISTS deploy_requests;
DROP TABLE IF EXISTS deploy_extend1;
DROP TABLE IF EXISTS deploy_extend2;
DROP TABLE IF EXISTS deploys;
DROP TABLE IF EXISTS repositories;

-- 或清空deploy_perms字段
UPDATE user_role_rel SET deploy_perms = NULL;
```

### 5.2 权限清理
```bash
# 使用之前提供的清理脚本
python manage.py clean_deploy
```

### 5.3 前端清理
前端的deploy相关页面需要删除：
- `spug_web/src/pages/deploy/` - 如果存在

### 5.4 路由清理
检查`spug_web/src/routes.js`中是否有deploy相关路由，如有需要删除。

---

## 六、验证清单

- [x] deploy模块目录已删除
- [x] repository模块目录已删除
- [x] settings.py中的INSTALLED_APPS已更新
- [x] settings.py中的deploy相关配置已删除
- [x] urls.py中的deploy路由已删除
- [x] app模块中的Deploy模型已删除
- [x] app模块中的DeployView已删除
- [x] app/urls.py中的deploy路由已删除
- [x] account模块中的deploy_perms属性已删除
- [x] schedule模块中的deploy相关逻辑已删除
- [x] config模块中的Deploy和Repository引用已删除
- [ ] 数据库表已清理（需手动执行）
- [ ] 前端路由已清理（需手动检查）
- [ ] 权限数据已清理（需手动执行）

---

## 七、总结

本次删除操作完全移除了deploy模块及其所有依赖：

1. **后端代码**: deploy、repository两个应用模块完全删除
2. **配置文件**: settings.py和urls.py中的所有相关配置已清理
3. **业务逻辑**: app、account、schedule、config模块中的相关代码已修改或删除
4. **依赖清理**: 移除了REQUEST_KEY、BUILD_KEY、REPOS_DIR、BUILD_DIR等配置

**注意事项**:
- 数据库表需要手动清理，Django不会自动删除
- 前端代码需要手动检查是否有deploy相关页面
- 如果用户角色中存储了deploy_perms权限，建议清空

**删除完成**
