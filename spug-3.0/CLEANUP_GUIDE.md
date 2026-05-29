# 回收站清理工具使用指南

## 🎯 快速选择

| 场景 | 推荐脚本 | 预计耗时 | 安全性 |
|------|---------|---------|--------|
| **1900个文件夹批量清理** | `cleanup_recycle_bin.py` | 5-10分钟 | ⭐⭐⭐ |
| **一键紧急清空** | `empty_recycle_bin_now.py` | 10秒 | ⭐⭐ |
| **保留部分数据** | `cleanup_recycle_bin.py --keep-recent 7` | 5-10分钟 | ⭐⭐⭐ |
| **只清理文件夹** | `cleanup_recycle_bin_folders.py` | 5-10分钟 | ⭐⭐⭐ |
| **极速清理（有风险）** | `cleanup_recycle_bin.py --mode force` | 5秒 | ⭐ |

---

## 🚀 推荐方案：万能清理工具

### 基本使用

```bash
# 查看当前回收站状态（试运行）
python cleanup_recycle_bin.py --dry-run

# 批量清理（每批50个，最安全）
python cleanup_recycle_bin.py

# 清空整个回收站
python cleanup_recycle_bin.py --mode empty --yes

# 只清理私有空间
python cleanup_recycle_bin.py --space private --yes

# 只清理公共空间
python cleanup_recycle_bin.py --space public --yes
```

### 高级用法

```bash
# 调整批次大小（默认50）
python cleanup_recycle_bin.py --batch-size 100

# 保留最近7天的数据
python cleanup_recycle_bin.py --keep-recent 7

# 极速模式（直接SQL，10秒完成，但跳过业务逻辑）
python cleanup_recycle_bin.py --mode force --yes
```

---

## ⚡ 紧急清空方案

如果只需要**快速清空**，不关心过程：

```bash
# 最简单的一键清空（10秒完成）
python empty_recycle_bin_now.py
```

然后输入"清空"确认即可。

---

## 📊 方案对比

### 方案1: 万能清理工具 (`cleanup_recycle_bin.py`)

**适用场景**: 1900个文件夹常规清理

**优点**:
- ✅ 支持多种清理模式
- ✅ 分批处理，不会阻塞系统
- ✅ 显示详细进度
- ✅ 支持试运行
- ✅ 可保留部分数据

**缺点**:
- 相对较慢（5-10分钟）

**使用示例**:
```bash
# 清理1900个文件夹（分38批，每批50个）
python cleanup_recycle_bin.py --batch-size 50 --yes

# 输出示例:
# 批次 1/38 (50 个)...
#   私有: 删除 25, 失败 0
#   公共: 删除 25, 失败 0
# 批次 2/38 (50 个)...
# ...
# ✅ 批量清理完成: 成功 1900, 失败 0
```

---

### 方案2: 一键清空 (`empty_recycle_bin_now.py`)

**适用场景**: 紧急清空，测试数据无需保留

**优点**:
- ✅ 最快（10秒）
- ✅ 最简单
- ✅ 一键执行

**缺点**:
- ⚠️ 不能选择保留部分数据
- ⚠️ 没有分批进度显示

**使用示例**:
```bash
python empty_recycle_bin_now.py

# 输出:
# 🗑️  一键清空回收站
# 发现数据:
#   私有文件夹: 950
#   公共文件夹: 950
#   私有文件: 0
#   公共文件: 0
#   总计: 1900
# ⚠️  确定要全部清空吗？输入 '清空' 继续: 清空
# 正在清空...
# ✅ 已清空 1900 项数据
```

---

### 方案3: 极速模式 (`--mode force`)

**适用场景**: 数据库层面极速清理

**优点**:
- ✅ 最快（5秒）
- ✅ 使用原始SQL
- ✅ 适合大批量数据

**缺点**:
- ⚠️ 跳过Django ORM
- ⚠️ 不触发信号
- ⚠️ 不删除物理文件
- ⚠️ 有一定风险

**使用示例**:
```bash
python cleanup_recycle_bin.py --mode force --yes

# 输出:
# ⚡ 强制清理模式（使用原始SQL）
# 执行强制清理...
#   删除私有文件: 0 个
#   删除私有文件夹: 950 个
#   删除公共文件: 0 个
#   删除公共文件夹: 950 个
# ✅ 强制清理完成
```

---

## ⚠️ 清理后的工作

### 1. 清理物理文件

数据库记录删除后，磁盘上的文件可能还在：

```bash
# 查看存储目录大小
du -sh spug_api/storage/documents

# 如果需要，手动清理（谨慎操作！）
# rm -rf spug_api/storage/documents/private/user-*/.deleted
```

### 2. 重启服务（可选）

如果清理了大量数据，建议重启服务释放内存：

```bash
# 重启Django服务
sudo supervisorctl restart spug-api

# 或者Docker
docker-compose restart api
```

### 3. 验证清理结果

```bash
# 查看回收站列表，确认已清空
curl -H "X-Token: YOUR_TOKEN" \
     http://localhost/api/document/recycle-bin/
```

---

## 🔧 故障排除

### 问题1: 删除很慢

**症状**: 每批50个需要几十秒

**解决**:
```bash
# 使用极速模式
python cleanup_recycle_bin.py --mode force --yes

# 或者直接SQL
cd spug_api
python manage.py dbshell
> DELETE FROM spug_document_folder_private WHERE is_deleted = 1;
> DELETE FROM spug_document_folder_public WHERE is_deleted = 1;
```

### 问题2: 内存不足

**症状**: Python内存溢出

**解决**:
```bash
# 减小批次大小
python cleanup_recycle_bin.py --batch-size 10
```

### 问题3: 权限错误

**症状**: "没有权限删除"

**解决**:
```bash
# 使用管理员用户执行
# 或者直接在数据库中执行SQL
```

### 问题4: 部分删除失败

**症状**: 显示有失败的删除

**原因**: 
- 外键约束
- 文件被锁定
- 权限问题

**解决**:
```bash
# 查看失败详情
python cleanup_recycle_bin.py --mode batch

# 重试失败的项目
# 或者使用强制模式绕过业务逻辑
python cleanup_recycle_bin.py --mode force
```

---

## 💡 最佳实践

### 压测前准备

```bash
# 1. 先清空回收站
python empty_recycle_bin_now.py

# 2. 确认清空
python cleanup_recycle_bin.py --dry-run

# 3. 开始压测
locust -f locustfile_recycle_bin.py ...
```

### 压测后清理

```bash
# 1. 查看压测产生了多少数据
python cleanup_recycle_bin.py --dry-run

# 2. 批量清理
python cleanup_recycle_bin.py --yes

# 3. 验证
python cleanup_recycle_bin.py --dry-run
# 应该显示: 回收站为空
```

### 定期维护

```bash
# 添加到crontab，每天凌晨清理7天前的数据
0 0 * * * cd /path/to/spug && python cleanup_recycle_bin.py --keep-recent 7 --yes
```

---

## 📈 性能参考

清理1900个文件夹的耗时对比：

| 方案 | 耗时 | 风险等级 | 适用场景 |
|------|------|---------|---------|
| batch模式 (50/批) | 8-10分钟 | 🟢 低 | 生产环境 |
| batch模式 (100/批) | 4-5分钟 | 🟢 低 | 生产环境 |
| empty模式 | 2-3分钟 | 🟡 中 | 测试环境 |
| force模式 | 5-10秒 | 🔴 高 | 紧急清理 |
| 一键清空 | 5-10秒 | 🔴 高 | 紧急清理 |

---

## 🔗 相关命令速查

```bash
# 查看回收站统计
curl http://localhost/api/document/recycle-bin/stats/

# 查看Celery任务队列
redis-cli LLEN celery

# 查看数据库表大小
mysql -e "SELECT table_name, round(((data_length + index_length) / 1024 / 1024), 2) AS 'Size (MB)' FROM information_schema.TABLES WHERE table_schema = 'spug';"

# 查看回收站文件数
mysql -e "SELECT 'Private Folders' as type, COUNT(*) FROM spug_document_folder_private WHERE is_deleted=1 UNION SELECT 'Public Folders', COUNT(*) FROM spug_document_folder_public WHERE is_deleted=1;"
```

---

**注意**: 所有清理操作都不可逆，请确保已备份重要数据！
