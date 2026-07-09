# 行业规章差异化优化方案与 AI 执行提示词

## 1. 背景结论

当前第一版“行业规章”不是简单复制粘贴资料管理，已经完成了一部分必要底座：

- 前端新增 `IndustryRulesIndex`，通过 `mode="industryRules"` 复用资料库页面。
- 前端通过 `system_folder=industry_rules` 给资料库请求注入行业规章上下文。
- 后端新增 `DocumentSystemFolder`，把行业规章绑定到公共资料库中的受保护根目录。
- 后端在多数资料库文件、文件夹接口中增加了行业规章范围校验。
- 权限从 `document.document.*` 拆出了 `document.industry_rule.*`。

但从产品形态看，它目前仍然更像“资料管理的一个受保护目录”，而不是“行业规章管理”。主要原因是：业务对象仍然只有文件和文件夹，没有规章台账、版本、生效废止、发布单位、适用范围等行业规章语义。

因此下一步不建议继续复制资料管理页面，而是保留资料库作为文件底座，在其上增加行业规章业务层。

## 2. 当前第一版需要保留的设计

以下设计方向是合理的，不要推倒重做：

1. 继续复用资料库的文件能力。
   上传、下载、预览、缩略图、搜索、传输队列、物理文件存储不需要另起一套。

2. 继续使用 `system_folder=industry_rules` 限定行业规章根目录。
   它可以保证行业规章入口只能访问受保护目录内的文件。

3. 继续保留独立权限前缀。
   行业规章权限应使用 `document.industry_rule.*`，不要要求用户同时拥有 `document.document.*`。

4. 继续保护行业规章根目录。
   根目录不允许删除、重命名、移动，避免业务入口失效。

## 3. 当前第一版主要问题

### 3.1 产品差异性不足

当前页面仍是资料库文件浏览体验，行业规章只有标题、根目录和权限变化。用户看到的核心对象仍是“文件 / 文件夹”，缺少“规章”概念。

应补充：

- 规章编号
- 规章名称
- 发布单位
- 规章类别
- 适用专业或适用范围
- 发布日期
- 生效日期
- 废止日期
- 状态：现行、即将生效、已废止、草稿
- 版本号
- 关联附件
- 备注或摘要

### 3.2 上传权限链可能不完整

资料库上传流程会调用传输记录接口，例如：

- `spug_api/apps/document/views/transfer/create.py`
- `spug_api/apps/document/views/transfer/list.py`
- `spug_api/apps/document/views/transfer/progress.py`
- `spug_api/apps/document/views/transfer/status.py`
- `spug_api/apps/document/views/transfer/cancel.py`
- `spug_api/apps/document/views/transfer/delete.py`
- `spug_api/apps/document/views/transfer/batch.py`

这些接口当前仍可能使用 `@auth('document.document.upload')` 或 `@auth('document.document.view')`。

如果用户只有 `document.industry_rule.upload`，没有 `document.document.upload`，行业规章上传可能会被传输记录接口拒绝。

### 3.3 菜单定位偏资料库

当前路由把行业规章放在资料库父菜单下：

```text
资料库
  - 资料管理
  - 行业规章
```

如果产品上希望行业规章是独立业务模块，建议后续把它从“资料库”父菜单中独立出来，或者至少在页面视觉和字段上明显区分。

### 3.4 后端缺少行业规章业务接口

当前主要仍使用 `/api/document/*` 接口。建议新增行业规章业务接口，例如：

```text
GET    /api/industry-rule/
POST   /api/industry-rule/
PUT    /api/industry-rule/<id>/
DELETE /api/industry-rule/<id>/
POST   /api/industry-rule/<id>/attach/
POST   /api/industry-rule/<id>/retire/
```

文件本身仍存储在资料库，业务接口只维护规章台账和文件关联。

## 4. 推荐目标架构

### 4.1 分层原则

```text
行业规章模块
  - 负责规章台账、分类、状态、版本、适用范围、业务查询

资料库模块
  - 负责文件存储、预览、下载、上传、缩略图、传输队列

系统目录绑定
  - 负责把行业规章限制在公共库中的受保护根目录内
```

### 4.2 数据模型建议

新增业务模型，推荐命名为 `IndustryRule`，可以放在独立 app，例如：

```text
spug_api/apps/industry_rule/
```

也可以先放在 document app 内，但不推荐长期这样做。

建议字段：

```python
class IndustryRule(models.Model):
    title = models.CharField(max_length=255)
    rule_no = models.CharField(max_length=100, blank=True, default='')
    category = models.CharField(max_length=50, blank=True, default='')
    issuing_authority = models.CharField(max_length=200, blank=True, default='')
    applicable_scope = models.CharField(max_length=255, blank=True, default='')
    publish_date = models.DateField(null=True, blank=True)
    effective_date = models.DateField(null=True, blank=True)
    repeal_date = models.DateField(null=True, blank=True)
    status = models.CharField(max_length=20, default='active')
    version = models.CharField(max_length=50, blank=True, default='')
    summary = models.TextField(blank=True, default='')
    document_file = models.ForeignKey(
        'document.DocumentFilePublic',
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
    )
    folder = models.ForeignKey(
        'document.DocumentFolderPublic',
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
    )
    created_by = models.ForeignKey(User, null=True, on_delete=models.SET_NULL)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
```

状态建议：

```text
draft       草稿
active      现行
upcoming    即将生效
retired     已废止
```

### 4.3 页面形态建议

行业规章页面不要直接展示资料库 Explorer 作为第一屏，而应优先展示规章台账：

```text
筛选区：
  关键词、类别、发布单位、状态、生效日期范围

列表列：
  规章编号、规章名称、类别、发布单位、生效日期、状态、版本、附件、更新时间、操作

操作：
  查看、编辑、上传/关联附件、下载附件、预览附件、废止、删除
```

资料库目录树可以作为“附件选择 / 附件管理”的辅助入口，而不是主体验。

### 4.4 权限建议

保留现有权限，并补充更贴合业务的权限命名：

```text
document.industry_rule.view
document.industry_rule.add
document.industry_rule.edit
document.industry_rule.delete
document.industry_rule.upload
document.industry_rule.download
document.industry_rule.retire
```

如果短期不改权限结构，至少要保证所有行业规章上传链路都能使用 `document.industry_rule.upload`。

## 5. 实施优先级

### P0：修复行业规章上传权限链

目标：只有行业规章权限的用户，也能完整上传、暂停、恢复、取消和完成上传。

处理范围：

- `spug_api/apps/document/views/transfer/create.py`
- `spug_api/apps/document/views/transfer/list.py`
- `spug_api/apps/document/views/transfer/progress.py`
- `spug_api/apps/document/views/transfer/status.py`
- `spug_api/apps/document/views/transfer/cancel.py`
- `spug_api/apps/document/views/transfer/delete.py`
- `spug_api/apps/document/views/transfer/batch.py`

要求：

- 将固定 `@auth('document.document.*')` 改为支持上下文的权限判断。
- 当请求带 `system_folder=industry_rules` 时，使用 `document.industry_rule.*`。
- 普通资料库请求仍使用 `document.document.*`。
- 不破坏现有资料库上传逻辑。

### P1：新增行业规章台账业务模型和接口

目标：让行业规章从“文件目录”变成“规章记录”。

新增：

- 后端 app 或模块：`industry_rule`
- 模型：`IndustryRule`
- 列表、详情、新增、编辑、删除、废止、附件关联接口
- 后端筛选：关键词、类别、状态、发布单位、生效日期范围

### P2：改造前端行业规章页面

目标：行业规章第一屏是业务台账，不是资料库 Explorer。

新增或改造：

- `spug_web/src/pages/document/IndustryRulesIndex.js`
- 或新建 `spug_web/src/pages/industryRule/index.js`

页面应包含：

- 筛选栏
- 规章列表
- 新建/编辑弹窗
- 附件上传/关联入口
- 附件预览和下载
- 状态标签

### P3：完善审计和导入能力

建议审计动作：

```text
industry_rule.create
industry_rule.update
industry_rule.delete
industry_rule.retire
industry_rule.attach_file
industry_rule.download
industry_rule.preview
```

建议后续支持 Excel 批量导入规章台账，但不要在第一轮实现中强行加入。

## 6. 验收标准

### 功能验收

- 只有 `document.industry_rule.view` 的用户可以访问行业规章列表，但不能上传或编辑。
- 只有 `document.industry_rule.upload` 的用户可以在行业规章内上传附件，不需要 `document.document.upload`。
- 行业规章接口不能访问行业规章根目录外的文件。
- 普通资料库用户不因为行业规章改造受到影响。
- 行业规章根目录不能删除、重命名、移动。
- 行业规章列表能按状态、类别、关键词筛选。
- 每条规章记录能关联至少一个资料库文件或一个主附件。

### 技术验收

- 后端权限不能只依赖前端传参，必须服务端校验 `system_folder` 范围。
- 新增迁移文件可正常执行。
- 关键 Python 文件通过 `py_compile`。
- 前端构建不报错。
- 不复制一套上传、下载、预览逻辑。

## 7. 可直接交给编程 AI 的提示词

```text
你是负责实现行业规章模块的编程 AI。请基于当前仓库完成“行业规章差异化优化”，不要把行业规章继续做成资料管理的简单复制。

当前第一版已经完成：
1. 前端 IndustryRulesIndex 复用 DocumentIndex，并传入 mode="industryRules"、systemFolderCode="industry_rules"。
2. 后端 document 模块新增 DocumentSystemFolder，用于绑定行业规章公共根目录。
3. 多数 document 文件/文件夹接口已经支持 system_folder=industry_rules 的范围校验。
4. 权限已拆出 document.industry_rule.*。

你需要按以下优先级执行：

P0：修复上传权限链
- 检查 spug_api/apps/document/views/transfer/ 下所有接口。
- 这些接口当前可能仍使用 @auth('document.document.upload') 或 @auth('document.document.view')。
- 改为支持行业规章上下文：
  - 请求带 system_folder=industry_rules 时，使用 document.industry_rule.upload 或 document.industry_rule.view。
  - 普通资料库请求继续使用 document.document.upload 或 document.document.view。
- 不要破坏普通资料库上传、暂停、恢复、取消、完成、失败、删除传输记录等流程。
- 如已有 document_auth 装饰器可复用，优先复用；否则实现一个小而清晰的上下文权限 helper。

P1：新增行业规章业务层
- 新增 IndustryRule 业务模型，记录规章编号、名称、类别、发布单位、适用范围、发布日期、生效日期、废止日期、状态、版本、摘要、关联附件。
- 文件附件继续引用 DocumentFilePublic，不要复制文件存储逻辑。
- 新增列表、详情、新增、编辑、删除、废止、附件关联接口。
- 列表支持关键词、类别、状态、发布单位、生效日期范围筛选。

P2：改造前端行业规章页面
- 行业规章第一屏应是“规章台账列表”，不是资料库 Explorer。
- 列表字段至少包括：规章编号、规章名称、类别、发布单位、生效日期、状态、版本、附件、更新时间、操作。
- 提供新建/编辑弹窗。
- 支持上传或关联附件，并复用现有资料库上传、预览、下载能力。
- 页面文案使用“规章、附件、废止、现行、生效”等业务术语，避免仍然全部显示“文件、文件夹、资料管理”。

P3：审计和验收
- 对新增、编辑、删除、废止、关联附件、下载附件等动作记录审计。
- 审计内容要完整准确但简洁，不记录敏感信息和大体积内容。
- 运行必要的语法检查和前端构建检查。

实施约束：
- 不要重写资料库模块。
- 不要复制一套上传下载预览逻辑。
- 不要移除现有 system_folder=industry_rules 保护机制。
- 不要要求行业规章用户必须同时拥有 document.document.* 权限。
- 保持普通资料库功能兼容。

完成后请说明：
1. 修改了哪些文件。
2. 行业规章相比资料管理新增了哪些差异化能力。
3. 如何验证只有行业规章权限的用户也能上传规章附件。
4. 执行了哪些检查。
```

