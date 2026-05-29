# CheckSheet PDF导出与前端显示一致方案

## 问题说明

之前PDF导出功能存在以下问题：
1. **表格结构不一致**：前端是合并所有项目到一个表格，后端是每个项目生成独立表格
2. **列顺序不一致**：前端是「项目 → 检查项目 → 1日...31日」，后端是「序号 → 检查项目 → 1日...31日」
3. **数据来源不同**：前端显示的是经过处理的视图数据，后端直接从数据库读取

## 解决方案

采用**前端驱动**的方式：前端构造表格数据并发送给后端，后端只负责PDF渲染。

### 实现细节

#### 1. 前端修改（DataView.js）

```javascript
const handleExportPDF = async () => {
  // 1. 构建表格数据（与前端表格完全一致）
  const tableData = [];

  // 表头
  const headerRow = ['项目', '检查项目'];
  days.forEach(day => headerRow.push(`${day}日`));
  tableData.push(headerRow);

  // 数据行
  Object.entries(viewData).forEach(([project, projectData]) => {
    const checkItems = projectData.template?.check_items || [];
    checkItems.forEach((item, itemIndex) => {
      const row = [itemIndex === 0 ? project : '', item];
      days.forEach(day => {
        const record = projectData.records?.find(
          r => r.item_index === itemIndex && r.day === day
        );
        const status = record?.status || 'UNCHECKED';
        const statusInfo = STATUS_MAP[status];
        let cellValue = statusInfo.label;
        if (record?.remark) {
          cellValue += ` ${record.remark}`;
        }
        row.push(cellValue);
      });
      tableData.push(row);
    });
  });

  // 2. 发送给后端
  const response = await http.post('/api/checksheet/export/pdf/', {
    year: selectedYear,
    month: selectedMonth,
    table_data: tableData,
    title: `${selectedYear}年${selectedMonth}月 全部项目检查表`
  });
};
```

#### 2. 后端修改（views.py）

支持两种请求方式：
- **POST请求**：接收前端发送的`table_data`，生成与前端一致的PDF
- **GET请求**：保持旧逻辑，从数据库读取并生成PDF（向后兼容）

```python
@auth('checksheet.checksheet.view')
def export_pdf(request):
    if request.method == 'POST':
        # 新方式：使用前端发送的表格数据
        data = json.loads(request.body)
        table_data = data.get('table_data', [])
        return _generate_pdf_from_table_data(...)
    else:
        # 旧方式：从数据库读取（向后兼容）
        return _generate_pdf_from_database(...)
```

#### 3. 辅助函数

- `_generate_pdf_from_table_data()`: 使用前端数据生成PDF，保持表格结构与前端一致
- `_generate_pdf_from_database()`: 从数据库读取生成PDF（旧逻辑）

## 优势

1. **前端所见即所得**：PDF表格与前端表格完全一致
2. **灵活性强**：前端可以自定义列顺序、列名、样式等
3. **维护简单**：后端只负责PDF渲染，业务逻辑在前端
4. **向后兼容**：旧接口仍然可用

## 效果对比

### 修改前
```
前端表格：
[项目] [检查项目] [1日] [2日] ... [31日]
[项目A] [项目1]  [√]   [×]   ...
        [项目2]  [—]   [√]   ...
[项目B] [项目1]  [√]   [√]   ...

后端PDF：
[项目A 2025年03月 检查表]
值班人员签名：xxx
[序号] [检查项目] [1日] [2日] ...
[1]    [项目1]     [√]   [×]   ...
[2]    [项目2]     [—]   [√]   ...
[发现] [问题]      [...] [...] ...
[备注] [...]        [...] [...] ...

--- 分页符 ---

[项目B 2025年03月 检查表]
...
```

### 修改后
```
前端表格：
[项目] [检查项目] [1日] [2日] ... [31日]
[项目A] [项目1]  [√]   [×]   ...
        [项目2]  [—]   [√]   ...
[项目B] [项目1]  [√]   [√]   ...

后端PDF（与前端一致）：
[2025年03月 全部项目检查表]
[项目] [检查项目] [1日] [2日] ... [31日]
[项目A] [项目1]  [√]   [×]   ...
        [项目2]  [—]   [√]   ...
[项目B] [项目1]  [√   [√]   ...
```

## 注意事项

1. **数据量限制**：如果表格过大（如项目多、检查项多），建议分页导出
2. **字体配置**：确保 `spug_api/apps/checksheet/fonts/` 目录下有中文字体文件
3. **兼容性**：如果其他地方调用旧接口（GET），仍会使用数据库方式生成PDF

## 测试步骤

1. 查询数据：选择年月 → 点击「查询全部」
2. 导出PDF：点击「导出PDF」
3. 对比检查：打开PDF，确认表格结构与前端显示一致
