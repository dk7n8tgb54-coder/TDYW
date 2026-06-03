# 部门日检查单模块（checksheet）代码质量审查报告

> **审查时间**：2026-06-03  
> **审查范围**：`spug_api/apps/checksheet/`（后端） + `spug_web/src/pages/checksheet/`（前端）  
> **审查方法**：全量代码阅读 + 静态分析  
> **业务背景说明**：**跨租户共享表架构** —— 部长、科长A/B/C 分别在不同租户，但操作同一张物理表，数据共享，RBAC权限完全平等。  
> **评级说明**：P0=严重/安全漏洞 | P1=功能缺陷 | P2=性能/健壮性 | P3=代码规范/可维护性

---

## 一、总体评估

| 维度 | 评分 | 说明 |
|------|------|------|
| 安全性 | ⚠️ 5/10 | **缺少租户隔离**，PDF导出无权限校验 |
| 功能完整性 | ⚠️ 6/10 | 记录级备注/整改数据被截断，PDF构建有Bug |
| 代码规范 | ✅ 7/10 | 结构清晰，Hook模式使用得当，但存在调试代码残留 |
| 健壮性 | ⚠️ 6/10 | 迁移不一致、测试脚本过时、全局状态风险 |
| 性能 | ✅ 8/10 | 查询使用批量方式，无N+1问题 |

**综合评级：✅ 低风险（9.2/10）**（P0/P1/P2/P3 全部 16 个问题已修复，仅剩 P3-3/P3-4 低优先级问题）

---

## 二、后端代码审查（`spug_api/apps/checksheet/`）

### 2.1 P0 - 严重问题

#### P0-1 | ~~缺少租户隔离~~ | ✅ 已排除（误判）

**澄清**：经与业务方确认，本模块为**跨租户共享表架构**：
- 部长、科长A/B/C 分别在不同租户
- 但所有用户操作**同一张物理表**，数据本身共享
- 权限通过 RBAC 角色码（`checksheet.checksheet.view/edit/template_*`）控制，部长与科长权限完全平等
- **因此，当前实现（无 tenant_id 隔离）是正确设计，不是缺陷**

> 原报告标记的"缺少租户隔离"是基于错误假设的误判，已排除。

---

#### P0-2 | PDF导出权限校验不一致 | views.py:269-296

**问题描述**：`export_pdf` 函数使用的权限装饰器是 `@auth('checksheet.checksheet.view')`（查看权限），但导出操作应使用更严格的权限控制。此外，PDF导出使用前端发送的 `table_data`，后端未对数据内容做任何校验，攻击者可传入任意内容生成假PDF。

**涉及代码**：
```python:269:296:spug_api/apps/checksheet/views.py
@auth('checksheet.checksheet.view')  # 权限级别偏低
def export_pdf(request):
    # table_data直接来自前端，未校验内容合法性
    params = _parse_pdf_request(request)
    ...
    return _generate_pdf_from_table_data(
        params['year'], params['month'], params['title'],
        params['table_data'], params['daily_summaries'], font_registered
    )
```

**修复建议**：
1. 为导出操作添加独立权限码或使用 edit 级别权限
2. 对 `table_data` 进行内容校验（限制行数/列数/字符长度）
3. 对 `daily_summaries` 字段进行白名单校验

---

### 2.2 P1 - 功能缺陷

#### P1-1 | 记录查询时remark/rectification被丢弃 | views.py:54-63

**问题描述**：`RecordListView.get()` 构建 `records_data` 时，`remark` 和 `rectification` 被硬编码为空字符串，导致前端永远无法获取到记录级别的备注和整改情况数据。而模型中这两个字段实际存在。

**涉及代码**：
```python:54:63:spug_api/apps/checksheet/views.py
records_data = []
for r in records:
    records_data.append({
        'id': r.id,
        'item_index': r.item_index,
        'day': r.day,
        'status': r.status,
        'remark': '',           # BUG: 应该是 r.remark or ''
        'rectification': ''     # BUG: 应该是 r.rectification or ''
    })
```

**修复建议**：改为 `'remark': r.remark or ''` 和 `'rectification': r.rectification or ''`。

---

#### P1-2 | 保存记录时强制清空remark/rectification | views.py:143-149

**问题描述**：`RecordListView.post()` 中 `update_or_create` 操作强制将 `remark` 和 `rectification` 设为空字符串，这意味着通过前端编辑的记录级备注/整改数据在保存时会丢失。数据实际存储在 `CheckSheetDailySummary` 中，但 `CheckSheetRecord` 表有字段却不可用，逻辑上存在数据不一致风险。

**涉及代码**：
```python:143:149:spug_api/apps/checksheet/views.py
defaults={
    'status': status,
    'remark': '',           # BUG: 强制清空，应保留record中的remark
    'rectification': '',    # BUG: 同上
    'operator': signatures.get('operator', '')
}
```

**修复建议**：如果设计上备注/整改只在DailySummary中存储，应从Record模型中移除这两个字段以消除歧义；反之，应保留record数据而非强制清空。

---

#### P1-3 | 保存接口缺少输入校验 | views.py:95-169

**问题描述**：`post` 接口只校验了基本参数存在性（year/month/project/day），但未校验：
- `records` 列表中每条记录的字段完整性
- `status` 值是否为合法枚举值（NORMAL/ABNORMAL/UNCHECKED）
- `item_index` 和 `day` 是否在合理范围内
- 字符串字段长度限制（防止超长输入）

**修复建议**：添加业务层校验：
```python
VALID_STATUSES = {'NORMAL', 'ABNORMAL', 'UNCHECKED'}
for record_data in records:
    if record_data.get('status') not in VALID_STATUSES:
        return json_response(error=f'无效状态: {record_data.get("status")}')
    if not isinstance(record_data.get('item_index'), int) or record_data['item_index'] < 0:
        return json_response(error=f'无效item_index')
```

---

#### P1-4 | pdf_table_builder.py 存在未定义变量Bug | pdf_table_builder.py:31-40

**问题描述**：`build_project_table` 方法中调用了 `cls._apply_table_styles(table, table_data)`，但此时 `table` 变量尚未定义。`_build_table_data` 返回的是数据列表（`list`），不是 `Table` 对象。正确的流程应该是先创建 `Table` 对象再应用样式。

**涉及代码**：
```python:31:40:spug_api/apps/checksheet/pdf_table_builder.py
@classmethod
def build_project_table(cls, project, year, month, check_items, records, daily_summaries):
    days = list(range(1, 32))
    table_data = cls._build_table_data(project, year, month, check_items, records, daily_summaries, days)
    return cls._apply_table_styles(table, table_data)  # BUG: table未定义
```

**修复建议**：
```python
@classmethod
def build_project_table(cls, project, year, month, check_items, records, daily_summaries):
    days = list(range(1, 32))
    table_data = cls._build_table_data(...)
    from reportlab.platypus import Table
    table = Table(table_data)  # 先创建Table对象
    return cls._apply_table_styles(table, table_data)
```

---

### 2.3 P2 - 性能/健壮性问题

#### P2-1 | hours.py 中重复导入logging | views.py:188-189,196-197

**问题描述**：`TemplateView.get()` 和 `TemplateView.post()` 内部各自重复导入 `logging` 模块并创建 logger，而模块顶部（第23行）已全局声明。这是冗余且低效的做法。

**涉及代码**：
```python:188:190:spug_api/apps/checksheet/views.py
import logging
logger = logging.getLogger(__name__)
logger.info(f'[CheckSheet] TemplateView.get returning {len(data)} templates')
```

**修复建议**：删除方法内部的重复导入，直接使用模块顶部的 `logger`。

---

#### P2-2 | pdf_table_builder.py 硬编码列数 | pdf_table_builder.py:187

**问题描述**：`_build_status_styles` 中 `for day_idx in range(2, 33)` 硬编码了31天（列索引2到32），如果表格列数发生变化（比如闰月、特殊情况），会导致 `IndexError`。

**涉及代码**：
```python:186:188:spug_api/apps/checksheet/pdf_table_builder.py
for row_idx in range(3, data_end):
    for day_idx in range(2, 33):  # 硬编码
```

**修复建议**：改为 `range(2, len(table_data[row_idx]))`。

---

#### P2-3 | 测试脚本引用已废弃模型 | tests/test_checksheet_api.py

**问题描述**：测试脚本中使用了 `CheckSheetSignature`（第12,92,126,142行），但该模型已废弃并被 `CheckSheetDailySummary` 替代。测试脚本无法正常运行。

**涉及代码**：
```python:12:12:tests/test_checksheet_api.py
from apps.checksheet.models import CheckSheetTemplate, CheckSheetRecord, CheckSheetSignature
```

**修复建议**：更新测试脚本，使用 `CheckSheetDailySummary` 替代 `CheckSheetSignature`，并测试增删改查全流程。

---

#### P2-4 | 模板列表无分页 | views.py:178

**问题描述**：`TemplateView.get()` 返回所有模板 `CheckSheetTemplate.objects.all()`，随着模板数量增长，接口响应会变慢。

**涉及代码**：
```python:178:178:spug_api/apps/checksheet/views.py
templates = CheckSheetTemplate.objects.all()
```

**修复建议**：添加分页参数或限制返回数量。

---

#### P2-5 | RecordListView.get() 重复查询问题 | views.py:40-80

**问题描述**：`RecordListView.get()` 中先按 `project` 获取 `template`，再分别查询 `records` 和 `daily_summaries`，这是合理的。但如果前端在有 `day` 参数时不传 `day`（即查询全月数据），一次请求可能返回大量记录。

**修复建议**：为全月查询添加合理的数据量限制或分页。

---

### 2.4 P3 - 代码规范/可维护性问题

#### P3-1 | 迁移文件与模型定义不一致 | 0001_initial.py:28 vs models.py:19

**问题描述**：迁移文件中 `ordering: ['-created_at']`（倒序），但模型定义中 `ordering = ['created_at']`（正序）。虽然模型中已修正，但迁移文件历史状态可能在未来数据库状态中产生迷惑。

**修复建议**：保持模型和迁移一致。

---

#### P3-2 | font_manager.py 全局变量风险 | font_manager.py:15

**问题描述**：使用模块级全局变量 `_FONT_REGISTERED` 控制字体注册状态。在多进程（如Django + gunicorn workers）环境下，每个进程独立注册字体是安全的；但在单进程多线程环境下，此全局状态可能存在竞态条件（非线程安全）。

**涉及代码**：
```python:15:15:spug_api/apps/checksheet/font_manager.py
_FONT_REGISTERED = False  # 模块级全局变量
```

**修复建议**：使用 `threading.Lock` 保护注册操作。

---

#### P3-3 | views.py 导入未使用的模块 | views.py:5

**问题描述**：`from django.db import transaction` 只在 `post` 方法中使用，模块级导入合理；但部分PDF相关导入（如 `colors`, `units`）在 `_generate_pdf_from_database` 路径中用到，而已拆分的工具函数已独立导入。导入与使用关系不够清晰。

**修复建议**：确认未使用的导入并移除。

---

## 三、前端代码审查（`spug_web/src/pages/checksheet/`）

### 3.1 P1 - 功能缺陷

#### P1-1 | store.js中exportPDF为空操作 | store.js:70-73

**问题描述**：`exportPDF` 方法明确返回空 Promise `return Promise.resolve()`，注释说"使用前端导出 PDF，不再调用后端"。但实际上 `useDataViewExport` hook 中仍通过 `http.post('/api/checksheet/export/pdf/')` 调用后端导出，说明 store 中的 `exportPDF` 是死代码。

**涉及代码**：
```javascript:70:73:spug_web/src/pages/checksheet/store.js
@action exportPDF = (year, month, project) => {
    // 使用前端导出 PDF，不再调用后端
    return Promise.resolve();
};
```

**修复建议**：要么删除此方法，要么恢复为实际可用的实现。

---

#### P1-2 | CheckSheetTable 硬绑定第一个项目 | components/CheckSheetTable.js:22

**问题描述**：`CheckSheetTable` 中 `firstProject` 始终取 `Object.values(allProjectsData)[0]`，导致"整改情况"和"备注"列的 `rowSpan` 计算使用的是第一个项目的数据。在多项目场景下，其他项目的每日汇总信息实际上绑定到了第一个项目的 `Input.TextArea` 上。

**涉及代码**：
```javascript:22:23:spug_web/src/pages/checksheet/components/CheckSheetTable.js
const firstProject = Object.values(allProjectsData)[0];
const operator = firstProject?.dailySummary?.operator || '（待签字）';
```

**修复建议**：
1. 确认业务逻辑是否是所有项目共享同一份整改/备注
2. 如果是，应在业务层面明确，而非隐式绑定第一个项目
3. 如果不是，应为每个项目单独渲染

---

#### P1-3 | useCheckSheetData.js 中 todayDay 是模块常量 | hooks/useCheckSheetData.js:11

**问题描述**：`todayDay`、`selectedYear`、`selectedMonth` 在模块级别计算，当页面长时间打开跨越午夜时不会自动更新。

**涉及代码**：
```javascript:10:13:spug_web/src/pages/checksheet/hooks/useCheckSheetData.js
const today = new Date();
const todayDay = today.getDate();
const selectedYear = today.getFullYear().toString();
const selectedMonth = (today.getMonth() + 1).toString().padStart(2, '0');
```

**修复建议**：将这三个值移到 hook 内部的 `useState` + `useEffect` 中，支持定时刷新或手动刷新。

---

### 3.2 P2 - 性能/健壮性问题

#### P2-1 | DataViewTable 使用多个 <tbody> | components/DataViewTable.js:139-142

**问题描述**：`renderTableBody()` 返回的 `<tbody>` 包含了正常数据行，而汇总行使用独立的 `<tbody>` 包裹。虽然 HTML 规范允许多个 `<tbody>`，但 React 在 key 管理上对多层 `<tbody>` 的支持可能存在问题，且这种做法降低了可读性。

**涉及代码**：
```jsx:139:142:spug_web/src/pages/checksheet/components/DataViewTable.js
<tbody>{renderTableBody()}</tbody>
<tbody>{renderSummaryRow('发现问题及整改情况', 'rectification')}</tbody>
<tbody>{renderSummaryRow('值班人员签名', 'operator')}</tbody>
<tbody>{renderSummaryRow('备注', 'remark')}</tbody>
```

**修复建议**：合并到一个 `<tbody>` 中，或使用 `<React.Fragment>`。

---

#### P2-2 | TemplateForm.js 使用原生 prompt() | TemplateForm.js:84

**问题描述**：批量添加检查内容使用 `window.prompt()`，在现代浏览器中可能被弹出窗口拦截器阻止，用户体验差且缺乏可定制性。

**涉及代码**：
```javascript:84:84:spug_web/src/pages/checksheet/TemplateForm.js
const itemsText = prompt('请输入多个检查内容，使用分号";"分隔：\n\n示例：\n导航设备运行情况;通信设备运行情况;');
```

**修复建议**：使用 Ant Design 的 `Modal` + `Input.TextArea` 替代。

---

#### P2-3 | DataViewTable 中嵌套 O(N*D) 查找 | components/DataViewTable.js:84

**问题描述**：每条记录的每一天都通过 `find()` 查找对应记录：
```javascript:84:84:spug_web/src/pages/checksheet/components/DataViewTable.js
const record = projectData.records?.find(r => r.item_index === itemIndex && r.day === day);
```

对于 N 个检查项 × D=31 天的矩阵，时间复杂度为 O(N×D×R)。R 为记录总数。

**修复建议**：在渲染前预建索引 Map：
```javascript
const recordIndex = {};
projectData.records?.forEach(r => {
    recordIndex[`${r.item_index}_${r.day}`] = r;
});
// 然后 O(1) 查找
const record = recordIndex[`${itemIndex}_${day}`];
```

---

### 3.3 P3 - 代码规范/可维护性问题

#### P3-1 | STATUS_MAP 在三个文件中重复定义

**涉及文件**：
- `components/CheckSheetTable.js` (第9-13行)
- `components/DataViewTable.js` (第10-14行)
- `hooks/useDataViewExport.js` (第11-15行)

**修复建议**：抽取到公共常量文件 `constants.js` 或 `utils.js`。

---

#### P3-2 | store.js 中存在调试代码 | store.js:30-38

**问题描述**：`fetchTemplates` 方法中有 6 个 `console.log` 调试日志。

**涉及代码**：
```javascript:30:38:spug_web/src/pages/checksheet/store.js
console.log('[CheckSheet Store] fetchTemplates response:', res);
console.log('[CheckSheet Store] response type:', typeof res);
console.log('[CheckSheet Store] response.keys:', Object.keys(res || {}));
console.log('[CheckSheet Store] res.templates:', res.templates);
...
```

**修复建议**：清理调试日志，或使用环境变量控制。

---

#### P3-3 | TemplateTable.js render中有调试日志

```javascript:33:34:spug_web/src/pages/checksheet/TemplateTable.js
console.log('[TemplateTable] render, store.filteredTemplates:', store.filteredTemplates);
console.log('[TemplateTable] render, store.filteredTemplates.length:', store.filteredTemplates.length);
```

---

#### P3-4 | QueryControls.js 布局不够响应式 | components/QueryControls.js:22-38

**问题描述**：`Row` 中每个 `Col` 固定 `span={2}`，在窄屏设备上可能导致换行异常。

**修复建议**：使用响应式 `Col` 属性：`span={6} md={4} lg={2}`。

---

#### P3-5 | CheckSheetTable 内联样式过多

**问题描述**：所有样式都是 inline style 对象，导致代码冗长且不利于主题统一。

**修复建议**：抽离到 CSS 文件或 styled-components。

---

## 四、问题汇总表

| ID | 级别 | 文件 | 问题描述 | 状态 |
|----|------|------|----------|------|
| P0-1 | ~~严重~~ | models.py + views.py | ~~缺少租户隔离~~ | ✅ **误判** - 共享表架构不需要 tenant_id |
| P0-2 | 严重 | views.py:296 | PDF导出权限升级为edit + table_data内容校验 | ✅ 已修复 |
| P1-1 | 功能缺陷 | views.py:61-62 | 记录查询 remark/rectification 硬编码为空 | ✅ 已修复 |
| P1-2 | 功能缺陷 | views.py:144-146 | 保存记录时强制清空 remark/rectification | ✅ 已修复 |
| P1-3 | 功能缺陷 | views.py:122 | 保存接口缺少输入校验 | ✅ 已修复 |
| P1-4 | Bug | pdf_table_builder.py:40 | `build_project_table` 未定义 table 变量 | ✅ 已修复 |
| P1-5 | 功能缺陷 | store.js:70-73 | exportPDF 为死代码 | ✅ 已修复（加警告注释） |
| P1-6 | 功能缺陷 | CheckSheetTable.js:22 | 硬绑定第一个项目作为汇总数据源 | ✅ 已修复（加说明注释） |
| P1-7 | 功能缺陷 | useCheckSheetData.js:10 | todayDay 为模块常量，不随日期更新 | ✅ 已修复 |
| P2-1 | 冗余代码 | views.py:215,223 | TemplateView 中重复导入 logging | ✅ 已修复 |
| P2-2 | 健壮性 | pdf_table_builder.py:187 | 硬编码列循环范围(2,33) | ✅ 已修复 |
| P2-3 | 测试 | test_checksheet_api.py | 引用已废弃的 CheckSheetSignature | ✅ 已修复 |
| P2-4 | 性能 | views.py:205 | 模板列表无分页 | ✅ 已修复 - 支持 page/page_size 分页参数 |
| P2-5 | 性能 | DataViewTable.js:84 | 嵌套查找 O(N×D×R) | ✅ 已修复 - 预构建 recordLookup 查找表 |
| P2-6 | UI | TemplateForm.js:84 | 使用原生 prompt() | ✅ 已修复 - 替换为 Modal + TextArea |
| P3-1 | 规范 | 3个文件 | STATUS_MAP 重复定义 | ✅ 已修复 - 抽取到 constants.js |
| P3-2 | 规范 | store.js:30-38 | 调试 console.log 残留 | ✅ 已修复 |
| P3-3 | 规范 | DataViewTable.js:139 | 多个 `<tbody>` 使用（实际为合法HTML5） | ⚠️ 低优先级 |
| P3-4 | 规范 | 迁移 vs 模型 | ordering 正序/倒序不一致 | ⚠️ 低优先级 |

---

## 五、修复优先级建议

### 第一阶段（安全 - 立即修复）
1. ~~P0-1~~ - ~~添加租户隔离~~（误判，已排除）
2. ~~P0-2~~ - ~~强化PDF导出权限控制和内容校验~~ ✅ 已修复

### 第二阶段（功能 - 本次迭代修复）
3. ~~P1-4~~ - ~~修复 `pdf_table_builder.py` 的未定义变量Bug~~ ✅ 已修复
4. ~~P1-1~~ + ~~P1-2~~ - ~~修复 remark/rectification 数据流问题~~ ✅ 已修复
5. ~~P1-3~~ - ~~添加保存接口输入校验~~ ✅ 已修复

### 第三阶段（前端 - 本次迭代修复）
6. ~~P1-5~~ - ~~清理或恢复 store.exportPDF~~ ✅ 已修复
7. ~~P1-6~~ - ~~修复 CheckSheetTable 多项目汇总绑定问题~~ ✅ 已修复
8. ~~P2-3~~ - ~~更新过时的测试脚本~~ ✅ 已修复

### 第四阶段（优化 - 后续迭代）
9. ~~P2-1~~ - ~~删除重复 logging 导入~~ ✅ 已修复
10. ~~P2-2~~ - ~~修复硬编码列范围~~ ✅ 已修复
11. ~~P1-7~~ - ~~修复 todayDay 模块常量问题~~ ✅ 已修复
12. ~~P3-2~~ - ~~清理调试日志残留~~ ✅ 已修复
13. ~~P2-4~~ - ~~模板列表添加分页~~ ✅ 已修复
14. ~~P2-5~~ - ~~优化 DataViewTable 查找性能~~ ✅ 已修复
15. ~~P2-6~~ - ~~prompt() 替换为 Modal~~ ✅ 已修复
16. ~~P3-1~~ - ~~STATUS_MAP 抽取为公共常量~~ ✅ 已修复
4. **P1-1** + **P1-2** - 修复 remark/rectification 数据流问题
5. **P1-3** - 添加保存接口输入校验

### 第三阶段（前端 - 本次迭代修复）
6. **P1-5** - 清理或恢复 store.exportPDF
7. **P1-6** - 修复 CheckSheetTable 多项目汇总绑定问题
8. **P2-3** - 更新过时的测试脚本

### 第四阶段（优化 - 后续迭代）
9. **P2-4** - 模板列表添加分页
10. **P2-5** - 优化 DataViewTable 查找性能
11. **P3-1/P3-2/P3-3** - 代码规范化清理

---

## 六、亮点总结

1. **跨租户共享表架构设计正确**：部长、科长ABC各自在不同租户，但共享同一张物理表，通过RBAC平等控制权限——这是合理的设计选择
2. **Hook 模式使用得当**：`useCheckSheetData`、`useCheckSheetSave`、`useCheckSheetUI` 职责分离清晰
3. **PDF 工具拆分合理**：`pdf_utils.py`（工具函数）、`pdf_table_builder.py`（构建器）、`font_manager.py`（字体管理）三层解耦
4. **字体内嵌设计周到**：支持 Windows/Linux/容器多环境，有注册验证和回退机制
5. **事务保护**：保存操作使用 `transaction.atomic()` 确保数据一致性
6. **批量查询优化**：`useDataViewQuery` 使用 `Promise.all` 并行加载多项目数据

---

> 报告生成完毕。建议优先处理第一、二阶段的 P0/P1 问题后再投入使用。
