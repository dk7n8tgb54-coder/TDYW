# 项目记忆

## 项目规范

### 数据库迁移 ⚠️ 重要
**修改 Django 模型后必须执行迁移**：
```bash
# 1. 生成迁移文件
docker exec tdyw python /data/spug/spug_api/manage.py makemigrations document --name xxx

# 2. 执行迁移
docker exec tdyw python /data/spug/spug_api/manage.py migrate document
```

### Docker 路径
- 容器内项目路径: `/data/spug/spug_api/`
- manage.py 位置: `/data/spug/spug_api/manage.py`

### 代码验证流程（post-write-verification skill）
1. Lint 检查: `read_lints(paths=[...])`
2. 语法检查: `docker exec tdyw python -m py_compile <path>`
3. 代码变更确认: `git diff`
4. 针对性测试脚本验证

### 核心教训
- 遇到问题第一反应是回查 skill 文档，而非凭直觉绕过
- skill 是经过验证的标准流程，比个人直觉更可靠
- Windows 本地环境存在编码、缺少依赖等问题，不适合直接运行 Python 测试
- **antd 版本差异**：antd 4.x 使用 `visible` 属性控制 Modal 显示，antd 5.x 使用 `open` 属性。本项目使用 antd 4.21.5，必须用 `visible`

### 技术细节
- spug_web 使用 antd 4.21.5
- spug_api 使用 Django + MySQL
- 租户隔离使用 TenantModelMixin

### 运行日志 (runlog) 模块
- `RunLog.update_count` 是缓存字段，存储动态记录数量
- 存在数据不一致问题：检查发现 `ID=7` (stored=3, actual=1) 和 `ID=6` (stored=8, actual=1) 不一致
- 已添加修复接口：`POST /api/runlog/repair/`
- 已有检查脚本：`/data/spug/spug_api/check_runlog_update_count.py`
