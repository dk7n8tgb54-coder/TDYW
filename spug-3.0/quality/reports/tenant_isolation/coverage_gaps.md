# 租户隔离测试覆盖缺口

## 因环境原因未验证的场景

### 1. Docker/Celery 行为测试未执行
- **原因**: Celery worker 未在 tdyw-test 容器内运行，无法直接触发异步任务
- **影响**: 以下 Celery 任务的租户上下文行为仅通过源码审查评估，未执行行为测试：
  - `check_license_expiry`（执照到期检查）
  - `check_contract_expiry`（合同到期检查）
  - `check_weekly_report_reminders`（提醒检查）
  - `retry_clean_pending_files`（文件清理重试）
  - `merge_chunks`（分片合并）
  - `archive_and_clean_audit_logs`（审计日志归档清理）
  - `check_disk_and_db`（磁盘/数据库监控）
  - `notice_expiry_sync`（公告过期同步）
- **建议**: 在有 Celery worker 的环境中补充行为测试

### 2. Redis 缓存行为测试未执行
- **原因**: 测试脚本使用 Django Test Client（直接调用视图），未经过 Redis 缓存层
- **影响**: 以下缓存的跨租户污染行为仅通过源码审查评估：
  - `data_analysis` Redis 缓存（缓存键含 tenant_id）
  - `User.page_perms` Redis 缓存（按 user_id 隔离）
- **建议**: 编写专门缓存行为测试

### 3. 文件/附件隔离测试未执行
- **原因**: 文件操作涉及物理文件系统，测试需创建临时文件且清理复杂
- **影响**: 以下文件功能的跨租户隔离仅通过源码审查评估：
  - document 模块的文件上传/下载/移动/删除
  - evidence 附件的多态绑定
  - regulation 独立 storage.py
  - kkFileView 预览回源
  - 分片上传任务隔离
- **建议**: 在有临时文件目录的环境中补充文件隔离测试

### 4. 以下模块仅源码审查未执行 HTTP 测试
- **原因**: 测试脚本聚焦于确认漏洞和验证核心模块隔离
- **影响**: 以下模块的 HTTP 跨租户测试未执行（源码审查显示使用了 apply_tenant_filter）：
  - radio_license（执照管理）
  - contract_agreement（合同协议）
  - interference（干扰管理）
  - device（设备台账/履历）
  - upgrade（系统升级）
  - department_duty_log（部门值班日志）
  - duty（值班日志）
  - document（文档管理）
  - evidence（附件系统）
  - logs（审计日志）
  - data_analysis（数据分析）
- **建议**: 将测试工厂扩展到这些模块并执行 HTTP 跨租户测试

### 5. 公共空间与系统空间测试未执行
- **原因**: DocumentSystemFolder 和公共空间的测试需要完整的文档模块设置
- **影响**: 以下场景未验证：
  - 党建资料与普通资料空间隔离
  - 公共空间是否仅对本租户公开
  - 伪造 system_scope 是否 fail-closed
- **建议**: 补充文档模块的公共空间测试

### 6. 跨租户关联测试未执行
- **原因**: 需要为每个外键关系创建跨租户对象并尝试关联
- **影响**: 以下关联场景仅源码审查：
  - 租户A故障关联租户B设备
  - 租户A附件绑定租户B业务对象
  - 租户A文档转存到租户B文件夹
- **建议**: 补充跨租户外键关联测试

### 7. 软删除与唯一性测试未执行
- **原因**: 需要创建同名对象并测试唯一约束行为
- **影响**: 以下场景未验证：
  - 租户A删除对象后租户B同名对象是否受影响
  - `__deleted_{id}` 重命名策略是否保持租户边界
  - 已删除对象能否通过原ID跨租户访问
- **建议**: 补充软删除跨租户测试

### 8. 全局数据边界测试部分执行
- **已验证**: Regulation, Setting, Alert, AlertRead, DocumentSystemFolder 均无 tenant_id（确认为全局数据）
- **未验证**: 全局管理员访问租户数据的边界
- **建议**: 补充全局数据修改权限测试

### 9. IDOR 枚举测试未执行
- **原因**: 需要枚举连续主键探测对象存在性
- **影响**: 404/403 响应差异未验证
- **建议**: 补充 IDOR 枚举测试

### 10. 预览 Token 跨租户测试未执行
- **原因**: 预览 token 有两套独立实现（document/libs vs evidence/attachment_preview_token）
- **建议**: 补充预览 token 跨租户访问测试
