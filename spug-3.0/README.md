<h1 align="center">TDYW 通导运维平台</h1>

<div align="center">

面向通信导航领域的运维管理平台，基于 Spug v3.3.3 进行深度定制开发，新增排班管理、设备履历、故障管理、值班日志、运行日志、干扰管理、日检查单、系统升级等专业模块。

</div>

---

## 模块概览

### 核心运维模块

| 模块 | 功能说明 |
|------|---------|
| **设备履历** | 设备全生命周期管理（安装→启用→故障→维修→更新→停用→报废），含经纬度定位、负责人管理、5种设备状态 |
| **故障管理** | 故障处置记录（系统/设备/等级/现象/处理过程）、故障件管理（送修/测试/归档） |
| **运行日志** | 事件闭环管理（P0/P1/P2级别），含处理中/已解决状态，24小时内可编辑，支持附件图片 |
| **干扰管理** | 无线电干扰记录（频率/坐标/干扰类型/现象/航班信息），含干扰统计分析 |
| **部门值班日检查单** | 检查表模板管理、每日检查记录（正常/异常/未检查）、每日汇总、PDF导出 |
| **值班日志** | 值班人员、填报人、所属科室、值班情况记录 |
| **排班管理** | 上X休Y或自定义班次、值班日历、换班审批、替班审批 |

### 资料库模块

> 基于 Spug 资料库深度改造

- **公共空间 + 私有空间**（多租户隔离）
- **分片上传**（支持大文件，10GB限制）
- **回收站**（软删除，30天保留期，批量恢复/彻底删除）
- **Office文档在线预览**（集成 kkFileView）
- 秒传检查、文件夹递归操作、路径遍历防护
- Celery 异步任务（文件合并、批量操作、清理）

### 系统管理

| 模块 | 功能说明 |
|------|---------|
| **系统升级管理** | 升级表单管理、升级模板/步骤清单、步骤执行跟踪 |
| **审计日志** | 中间件自动记录所有写操作（创建/更新/删除/登录等），含IP、租户、操作详情 |
| **账户管理** | 用户、角色、权限管理 |
| **系统设置** | 系统配置项 |

---

## 技术栈

| 层级 | 技术 |
|------|------|
| **后端** | Python 3.10+ / Django 2.2 / Django REST Framework |
| **前端** | React 16 / Ant Design 4 / MobX |
| **数据库** | MySQL / MariaDB |
| **缓存** | Redis |
| **任务队列** | Celery + Celery Beat |
| **文件预览** | kkFileView 4.1.0 |
| **部署** | Docker / Docker Compose |

---

## 架构特性

- **多租户隔离**：所有业务模型通过 `tenant_id` 字段实现数据隔离，超级管理员可跨租户查看
- **审计追溯**：AuditLogMiddleware 自动记录所有非GET请求的操作日志
- **代码门禁**：Git pre-commit 钩子自动检查代码质量（ESLint + Flake8 + 行数/复杂度校验）

---

## 快速开始

### Docker 部署

```bash
# 进入部署目录
cd docker

# 复制环境变量配置
cp .env.example .env
# 编辑 .env 配置数据库密码等参数

# 启动服务
docker-compose up -d

# 初始化数据库
docker exec tdyw python spug_api/manage.py migrate
docker exec tdyw python spug_api/manage.py init_data

# 访问 http://localhost
```

### 开发环境

```bash
# 后端
cd spug_api
pip install -r requirements.txt
python manage.py runserver 0.0.0.0:9001

# 前端
cd spug_web
npm install
npm start
```

---

## Docker 服务架构

```
Nginx (80/443)
  └── Django API (Gunicorn, 4 workers × 16 threads)
       ├── MariaDB (tdyw-db:3306, 8GB)
       ├── Redis (127.0.0.1:6379)
       └── kkFileView (kkfileview:8012, Office预览)
```

| 服务 | 资源限制 |
|------|---------|
| tdyw（主应用） | 4 CPU / 4GB 内存 |
| tdyw-db（数据库） | 2 CPU / 8GB 内存 |
| kkfileview（文件预览） | 2 CPU / 4GB 内存 |

---

## 数据库表命名

自定义模块表名统一使用 `tdyw_` 前缀：
- `tdyw_device_resume`, `tdyw_device_event`
- `tdyw_fault_records`, `tdyw_fault_parts`
- `tdyw_duty_records`
- `tdyw_interferences`
- `tdyw_schedule_*`
- `tdyw_upgrade_*`
- `checksheet_*`
- `audit_logs`
- `runlog_run_logs`, `runlog_run_log_updates`
- `tdyw_document_*`

---

## License

基于 [AGPL-3.0](https://opensource.org/licenses/AGPL-3.0) 开源协议发布。

基于 [Spug](https://github.com/openspug/spug) 进行定制开发。
