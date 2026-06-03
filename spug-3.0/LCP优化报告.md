# 资料库 LCP 优化报告

## 1. 现状分析

### 1.1 当前 LCP 表现
- **实测 LCP**：3.14 秒
- **目标 LCP**：< 2.5 秒（Google Core Web Vitals 标准）
- **差距**：+0.64 秒（+25.6%）

### 1.2 瓶颈定位

| 瓶颈 | 位置 | 问题描述 | 预估耗时占比 |
|------|------|----------|-------------|
| **disk_usage API** | `views/disk.py` 第59-63行 | 扫描所有文件（含已删除）计算大小，无索引 | ~40% |
| **FolderTree 全量加载** | `src/pages/document/FolderTree.js` | 一次性加载最多1000个文件夹 | ~25% |
| **Explorer 串行请求** | `hooks/useDataFetching.js` | 多个API串行等待 | ~20% |
| **Explorer 文件列表** | `views/folder/views.py` | N+1查询（每层2次DB） | ~15% |

### 1.3 关键代码问题

#### 问题1：disk_usage 无条件扫描全表
```python
# spug_api/apps/document/views/disk.py:59-63
query = FileModel.objects.all()  # ❌ 没有 is_deleted=False 过滤
if not form.is_public:
    query = apply_tenant_filter(query, request.user)
total_size = query.aggregate(total_size=Sum('file_size'))['total_size'] or 0
```
**影响**：已删除文件也被计入，tenant_id 可能无索引。

#### 问题2：FolderTree 一次性加载全部
```javascript
// spug_web/src/pages/document/FolderTree.js:79
if (all) params.id = 'null';  // 一次性获取所有文件夹
```

#### 问题3：useDataFetching 串行请求
```javascript
// spug_web/src/pages/document/hooks/useDataFetching.js:54-66
// 4个请求串行执行
await fetchFolders(params);        // ~500ms
await fetchFolderContents(params); // ~800ms
await fetchDiskUsage();            // ~1500ms（最慢）
await fetchRecentFiles();          // ~300ms
```

---

## 2. 优化目标

| 指标 | 当前值 | 目标值 | 提升幅度 |
|------|--------|--------|----------|
| LCP | 3.14s | < 2.5s | -20% |
| disk_usage API | ~1500ms | < 200ms | -87% |
| FolderTree 加载 | ~500ms | < 200ms | -60% |
| 总请求数 | 4个串行 | 并行化 | 耗时减半 |

---

## 3. 限制条件

### 3.1 技术限制
- **数据库**：MySQL 5.7+，需要确保 `tenant_id`、`is_deleted` 有联合索引
- **前端**：React 18，保持现有 UI 不变
- **后端**：Django 3.2+，不能破坏现有权限模型

### 3.2 兼容性要求
- 现有 API 接口返回值结构不变（前端无感知）
- 租户隔离逻辑不变
- 已删除文件不显示在磁盘统计中（逻辑修正）

### 3.3 性能约束
- 单次文件夹浏览操作响应时间 < 1秒
- 1000节点树构建时间 < 200ms
- 并行请求总数不超过 6 个

---

## 4. 验收标准

### 4.1 性能指标

| 测试场景 | 指标 | 达标条件 |
|----------|------|----------|
| 资料库首页加载 | LCP | < 2.5s |
| 磁盘使用统计 | API 响应时间 | < 200ms |
| 文件夹树渲染 | 1000节点 | < 200ms |
| 并行优化 | 请求耗时 | 串行改并行后总耗时减少 > 50% |

### 4.2 功能验收

- [ ] disk_usage 只统计未删除文件
- [ ] 租户只能看到自己的磁盘使用量
- [ ] FolderTree 加载结果与优化前一致
- [ ] Explorer 内容加载结果与优化前一致
- [ ] 并行请求不会导致数据竞争或显示错误

### 4.3 测试用例

1. **disk_usage 准确性测试**
   - 上传文件A（10MB），验证 disk_usage 增加 10MB
   - 删除文件A，验证 disk_usage 不包含已删除文件
   - 用另一租户用户登录，验证只能看到自己的使用量

2. **FolderTree 完整性测试**
   - 1000节点树加载，对比优化前后节点数量
   - 展开任意节点，验证子节点显示正确

3. **LCP 测试**
   - 使用 Chrome DevTools Performance 面板测量
   - 测量 5 次取中位数

---

## 5. 优化方案概述

### 5.1 Phase 1：disk_usage 修复（预计 -1300ms）
1. 添加 `is_deleted=False` 过滤
2. 确保 `tenant_id + is_deleted` 联合索引存在
3. 添加数据库层面缓存（可选）

### 5.2 Phase 2：请求并行化（预计 -500ms）
1. 将 4 个串行请求改为 `Promise.all` 并行
2. disk_usage 异步加载，不阻塞主流程

### 5.3 Phase 3：FolderTree 懒加载（预计 -300ms）
1. 初始只加载根目录和一级子文件夹
2. 点击展开时再加载子节点

---

## 6. 后续监控

优化上线后，建议在 Grafana 中添加以下指标：
- `document_api_disk_usage_duration_seconds` (histogram)
- `document_api_folder_tree_duration_seconds` (histogram)
- `document_lcp_seconds` (gauge)
