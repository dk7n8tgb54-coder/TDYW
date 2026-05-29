# 资料库 Office 文件在线预览功能方案

## 1. 需求概述

### 1.1 目标
为资料库模块增加 Office 文件（Word、Excel、PowerPoint）在线预览功能，用户无需下载即可在浏览器中查看文档内容。

### 1.2 支持格式
| 格式类型 | 扩展名 | 优先级 |
|---------|--------|--------|
| Word | .doc, .docx | P0 |
| Excel | .xls, .xlsx | P0 |
| PowerPoint | .ppt, .pptx | P1 |
| PDF | .pdf | P0（已有，需整合）|

---

## 2. 技术方案选型

### 2.1 方案对比

| 方案 | 原理 | 优点 | 缺点 | 适用场景 |
|------|------|------|------|----------|
| **OnlyOffice** | 自建文档服务器 | 功能完整、可编辑、私有化 | 资源占用高、配置复杂 | 大型企业、需要编辑功能 |
| **LibreOffice + unoconv** | 转换为PDF后预览 | 开源免费、格式支持全 | 转换慢、格式可能失真 | 中小型企业、只读预览 |
| **Microsoft Office Online** | 微软云服务 | 格式兼容性最好 | 需公网、数据出境 | 国际化企业 |
| **kkFileView** | 开源文档预览方案 | 集成方便、支持多种格式 | 依赖Java、资源占用中等 | 推荐方案 |
| **前端解析（mammoth.js等）** | 浏览器直接解析 | 无服务端压力 | 格式支持有限、大文件卡 | 简单文档预览 |

### 2.2 推荐方案：kkFileView

**选择理由：**
1. 国产开源项目，文档齐全
2. 支持 Word、Excel、PPT、PDF 等主流格式
3. 提供独立服务，与现有系统解耦
4. 支持私有化部署，数据安全可控
5. 社区活跃，持续维护

---

## 3. 系统架构

```
┌─────────────────────────────────────────────────────────────────┐
│                         用户浏览器                              │
│  ┌─────────────────┐    ┌─────────────────┐                    │
│  │   资料库前端     │───▶│  kkFileView     │                    │
│  │   (React)       │    │   预览页面       │                    │
│  └─────────────────┘    └─────────────────┘                    │
│           │                       ▲                             │
│           │ 1. 获取预览URL        │ 3. 加载文档                  │
│           ▼                       │                             │
│  ┌─────────────────┐    ┌────────┴────────┐                    │
│  │   Django API    │───▶│   kkFileView    │                    │
│  │   /api/preview  │ 2. 转发文件流        │   服务              │
│  └─────────────────┘    │   (Java)        │                    │
│                         └─────────────────┘                    │
│                                  ▲                              │
│                                  │ 4. 读取文件                   │
│                         ┌────────┴────────┐                    │
│                         │   文件存储        │                    │
│                         │ (本地/NFS/OSS)   │                    │
│                         └─────────────────┘                    │
└─────────────────────────────────────────────────────────────────┘
```

---

## 4. 详细设计

### 4.1 部署方案

#### 4.1.1 Docker 部署 kkFileView

```yaml
# docker-compose.yml
version: '3'
services:
  kkfileview:
    image: keking/kkfileview:4.1.0
    container_name: kkfileview
    ports:
      - "8012:8012"
    environment:
      - OFFICE_PREVIEW_TYPE=image  # image/pdf
      - CACHE_ENABLED=true
      - CACHE_CLEAN_CRON=0 0 3 * * ?
    volumes:
      - ./kkfileview-cache:/opt/kkfileview/cache
      - ./kkfileview-log:/opt/kkfileview/log
    restart: always
```

#### 4.1.2 配置文件

```properties
# application.properties
server.port=8012
server.context-path=/

# 文件预览类型
office.preview.type=image
office.preview.switch.disabled=false

# 缓存配置
cache.enabled=true
cache.clean.cron=0 0 3 * * ?

# 文件大小限制（MB）
file.size.max=100

# 允许跨域
cors.enabled=true
cors.origin=*
```

### 4.2 后端接口设计

#### 4.2.1 新增预览接口

```python
# views/file/preview_office.py

import logging
import requests
from django.conf import settings
from django.views.generic import View
from libs import json_response, auth

logger = logging.getLogger(__name__)


class OfficePreviewView(View):
    """Office文件在线预览接口"""
    
    PREVIEW_TYPES = ['doc', 'docx', 'xls', 'xlsx', 'ppt', 'pptx']
    
    @auth('document.document.view')
    def get(self, request, file_id):
        """
        获取Office文件预览URL
        
        GET /api/document/file/<file_id>/preview/office/
        
        Response:
        {
            "preview_url": "http://kkfileview:8012/onlinePreview?url=xxx",
            "file_type": "docx",
            "file_name": "文档.docx"
        }
        """
        try:
            # 1. 获取文件对象（根据公共空间/私有空间）
            file_obj = self._get_file(file_id, request.user)
            if not file_obj:
                return json_response(error='文件不存在或无权限访问')
            
            # 2. 检查文件类型
            file_ext = self._get_file_extension(file_obj.name)
            if file_ext not in self.PREVIEW_TYPES:
                return json_response(error=f'不支持的文件类型: {file_ext}')
            
            # 3. 生成预览URL
            preview_url = self._generate_preview_url(file_obj)
            
            return json_response(data={
                'preview_url': preview_url,
                'file_type': file_ext,
                'file_name': file_obj.name,
                'preview_type': 'office'
            })
            
        except Exception as e:
            logger.error(f'[OfficePreview] 生成预览URL失败: {e}', exc_info=True)
            return json_response(error='预览服务暂不可用')
    
    def _get_file(self, file_id, user):
        """获取文件对象（带租户过滤）"""
        from apps.document.models import DocumentFilePrivate, DocumentFilePublic
        from apps.document.libs.tenant_utils import apply_tenant_filter
        
        # 先尝试私有空间
        file_obj = apply_tenant_filter(
            DocumentFilePrivate.objects.filter(id=file_id),
            user
        ).first()
        
        if not file_obj:
            # 再尝试公共空间
            file_obj = DocumentFilePublic.objects.filter(id=file_id).first()
        
        return file_obj
    
    def _get_file_extension(self, filename):
        """获取文件扩展名"""
        return filename.split('.')[-1].lower() if '.' in filename else ''
    
    def _generate_preview_url(self, file_obj):
        """生成kkFileView预览URL"""
        import urllib.parse
        import base64
        
        # 构建文件访问URL（需可被kkFileView访问）
        file_url = self._get_file_access_url(file_obj)
        
        # Base64编码URL
        encoded_url = base64.b64encode(file_url.encode()).decode()
        
        # 构建预览URL
        preview_base = settings.KKFILEVIEW_URL  # http://kkfileview:8012
        preview_url = f"{preview_base}/onlinePreview?url={urllib.parse.quote(encoded_url)}"
        
        return preview_url
    
    def _get_file_access_url(self, file_obj):
        """
        获取文件访问URL
        
        方案1: 内网直接访问（推荐）
        - kkFileView和Django在同一内网
        - 直接通过文件路径访问
        
        方案2: 通过API代理
        - 提供临时下载链接
        - 需要身份验证
        """
        # 方案1: 直接文件路径（需挂载相同存储）
        if hasattr(settings, 'KKFILEVIEW_DIRECT_ACCESS') and settings.KKFILEVIEW_DIRECT_ACCESS:
            return f"file://{file_obj.file_path}"
        
        # 方案2: 通过API代理
        base_url = settings.SITE_URL  # https://spug.example.com
        return f"{base_url}/api/document/file/{file_obj.id}/download/?preview=1"


class OfficePreviewProxyView(View):
    """
    Office文件预览代理
    
    用于kkFileView无法直接访问内网文件时的代理方案
    """
    
    @auth('document.document.view')
    def get(self, request, file_id):
        """代理文件下载给kkFileView"""
        from django.http import FileResponse
        
        file_obj = self._get_file(file_id, request.user)
        if not file_obj:
            return json_response(error='文件不存在')
        
        try:
            response = FileResponse(
                open(file_obj.file_path, 'rb'),
                content_type=self._get_content_type(file_obj.name)
            )
            response['Content-Disposition'] = f'inline; filename="{file_obj.name}"'
            return response
        except FileNotFoundError:
            return json_response(error='文件已丢失')
    
    def _get_content_type(self, filename):
        """获取MIME类型"""
        import mimetypes
        return mimetypes.guess_type(filename)[0] or 'application/octet-stream'
```

### 4.3 前端集成

#### 4.3.1 预览组件

```jsx
// components/OfficePreview/index.jsx
import React, { useState, useEffect } from 'react';
import { Modal, Spin, Alert } from 'antd';

const OfficePreview = ({ visible, fileId, fileName, onClose }) => {
  const [previewUrl, setPreviewUrl] = useState('');
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  useEffect(() => {
    if (visible && fileId) {
      fetchPreviewUrl();
    }
  }, [visible, fileId]);

  const fetchPreviewUrl = async () => {
    setLoading(true);
    setError(null);
    
    try {
      const response = await http.get(`/api/document/file/${fileId}/preview/office/`);
      if (response.data && response.data.preview_url) {
        setPreviewUrl(response.data.preview_url);
      } else {
        setError('无法生成预览链接');
      }
    } catch (err) {
      setError(err.message || '预览服务暂不可用');
    } finally {
      setLoading(false);
    }
  };

  return (
    <Modal
      title={`预览: ${fileName}`}
      visible={visible}
      onCancel={onClose}
      width="90%"
      style={{ top: 20 }}
      bodyStyle={{ height: '80vh', padding: 0 }}
      footer={null}
    >
      {loading && (
        <div style={{ textAlign: 'center', padding: '50px' }}>
          <Spin size="large" tip="正在加载预览..." />
        </div>
      )}
      
      {error && (
        <Alert
          message="预览失败"
          description={error}
          type="error"
          showIcon
          style={{ margin: '20px' }}
        />
      )}
      
      {previewUrl && !loading && (
        <iframe
          src={previewUrl}
          style={{ width: '100%', height: '100%', border: 'none' }}
          sandbox="allow-scripts allow-same-origin"
        />
      )}
    </Modal>
  );
};

export default OfficePreview;
```

#### 4.3.2 文件列表集成

```jsx
// 在文件列表中添加预览按钮
const handlePreview = (file) => {
  const officeExts = ['doc', 'docx', 'xls', 'xlsx', 'ppt', 'pptx'];
  const ext = file.name.split('.').pop().toLowerCase();
  
  if (officeExts.includes(ext)) {
    // Office文件使用kkFileView预览
    setPreviewFile(file);
    setPreviewVisible(true);
  } else if (ext === 'pdf') {
    // PDF使用原有预览方式
    handlePdfPreview(file);
  } else {
    // 其他文件提示下载
    message.info('该文件类型不支持在线预览，请下载后查看');
  }
};
```

### 4.4 配置项

```python
# settings.py

# kkFileView 配置
KKFILEVIEW_URL = 'http://kkfileview:8012'  # kkFileView服务地址
KKFILEVIEW_DIRECT_ACCESS = True  # 是否直接访问文件路径
KKFILEVIEW_TIMEOUT = 30  # 预览链接有效期（秒）

# 预览文件大小限制（MB）
OFFICE_PREVIEW_MAX_SIZE = 50

# 支持的预览格式
OFFICE_PREVIEW_TYPES = ['doc', 'docx', 'xls', 'xlsx', 'ppt', 'pptx']
```

---

## 5. 安全考虑

### 5.1 访问控制

| 安全措施 | 实现方式 |
|---------|---------|
| 身份验证 | 通过Django的@auth装饰器验证用户权限 |
| 租户隔离 | 使用apply_tenant_filter确保数据隔离 |
| 文件权限 | 检查用户是否有权访问该文件 |
| URL时效 | 预览URL可设置有效期，防止长期有效 |

### 5.2 网络安全

```yaml
# docker-compose 网络安全配置
services:
  kkfileview:
    networks:
      - internal  # 只允许内网访问
    ports:
      - "127.0.0.1:8012:8012"  # 不暴露到公网
```

### 5.3 文件安全

```python
# 文件路径安全检查
def _validate_file_path(self, file_path):
    """确保文件路径在允许的目录内"""
    import os
    
    base_dir = settings.DOCUMENT_STORAGE_PATH
    real_path = os.path.realpath(file_path)
    real_base = os.path.realpath(base_dir)
    
    if not real_path.startswith(real_base):
        raise ValueError('非法的文件路径')
    
    return real_path
```

---

## 6. 性能优化

### 6.1 缓存策略

```python
# 预览URL缓存（避免重复生成）
from django.core.cache import cache

def _generate_preview_url(self, file_obj):
    cache_key = f'office_preview:{file_obj.id}'
    preview_url = cache.get(cache_key)
    
    if not preview_url:
        preview_url = self._build_preview_url(file_obj)
        cache.set(cache_key, preview_url, 300)  # 缓存5分钟
    
    return preview_url
```

### 6.2 大文件处理

```python
# 大文件限制
OFFICE_PREVIEW_MAX_SIZE = 50 * 1024 * 1024  # 50MB

def get(self, request, file_id):
    file_obj = self._get_file(file_id, request.user)
    
    # 检查文件大小
    if file_obj.file_size > settings.OFFICE_PREVIEW_MAX_SIZE:
        return json_response({
            'error': '文件过大，不支持在线预览',
            'max_size': settings.OFFICE_PREVIEW_MAX_SIZE,
            'file_size': file_obj.file_size
        })
    
    # ...
```

### 6.3 异步转换

对于超大文件，可以考虑异步转换：

```python
# tasks/office_preview.py
from celery import shared_task

@shared_task
def convert_office_to_pdf(file_id):
    """异步将Office文件转换为PDF"""
    # 转换逻辑
    pass
```

---

## 7. 部署步骤

### 7.1 部署 kkFileView

```bash
# 1. 拉取镜像
docker pull keking/kkfileview:4.1.0

# 2. 启动服务
docker run -d \
  --name kkfileview \
  -p 8012:8012 \
  -v /data/kkfileview/cache:/opt/kkfileview/cache \
  -v /data/kkfileview/log:/opt/kkfileview/log \
  -e OFFICE_PREVIEW_TYPE=image \
  keking/kkfileview:4.1.0

# 3. 验证服务
curl http://localhost:8012
```

### 7.2 配置 Django

```python
# 1. 添加配置到 settings.py
KKFILEVIEW_URL = 'http://kkfileview:8012'

# 2. 添加URL路由
# urls.py
path('file/<int:file_id>/preview/office/', OfficePreviewView.as_view()),

# 3. 重启 Django 服务
supervisorctl restart daphne
```

### 7.3 前端部署

```bash
# 1. 安装依赖
npm install

# 2. 构建
npm run build

# 3. 部署到Nginx
cp -r build/* /var/www/html/
```

---

## 8. 测试计划

### 8.1 功能测试

| 测试项 | 测试内容 | 预期结果 |
|--------|---------|---------|
| Word预览 | 上传.docx文件，点击预览 | 正常显示文档内容 |
| Excel预览 | 上传.xlsx文件，点击预览 | 正常显示表格内容 |
| PPT预览 | 上传.pptx文件，点击预览 | 正常显示幻灯片 |
| 大文件 | 上传50MB以上文件 | 提示文件过大 |
| 权限控制 | 无权限用户访问预览 | 返回403错误 |
| 租户隔离 | 跨租户访问文件预览 | 返回404错误 |

### 8.2 性能测试

| 测试项 | 指标 | 目标 |
|--------|------|------|
| 预览加载时间 | 从点击到显示内容 | < 5秒 |
| 并发预览 | 同时10个用户预览 | 无卡顿 |
| 内存占用 | kkFileView服务 | < 2GB |

---

## 9. 风险与应对

| 风险 | 影响 | 应对措施 |
|------|------|---------|
| kkFileView服务故障 | 无法预览 | 降级为下载提示 |
| 格式兼容性问题 | 文档显示异常 | 提供下载原文件选项 |
| 大文件导致OOM | 服务崩溃 | 文件大小限制 + 监控告警 |
| 安全漏洞 | 数据泄露 | 内网部署 + 访问控制 |

---

## 10. 后续优化

1. **编辑功能**：集成 OnlyOffice 实现文档在线编辑
2. **批注功能**：支持在预览时添加批注
3. **水印功能**：预览时添加用户水印
4. **移动端适配**：优化移动端预览体验
5. **历史版本**：支持预览历史版本文档

---

**方案制定**: 2026-03-31  
**预计工时**: 3-5人日  
**优先级**: P1
