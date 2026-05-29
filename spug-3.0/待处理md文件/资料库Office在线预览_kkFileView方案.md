# 资料库 Office 在线预览方案（kkFileView）

## 1. 方案概述

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

## 2. 技术选型：kkFileView

### 2.1 选择理由

1. **国产开源**：中文文档齐全，社区活跃
2. **格式支持全**：基于 LibreOffice，兼容性好
3. **独立部署**：Java服务，与Python项目解耦
4. **私有化部署**：数据安全可控，不依赖外网
5. **成熟稳定**：4.x版本已稳定运行多年

### 2.2 架构图

```
┌─────────────────────────────────────────────────────────────┐
│                        用户浏览器                            │
│  ┌─────────────────┐      ┌─────────────────────────────┐  │
│  │   资料库前端      │      │   iframe 嵌入 kkFileView    │  │
│  │   (React)       │─────▶│   预览页面                   │  │
│  └─────────────────┘      └─────────────────────────────┘  │
│           │                                                │
│           │ 1. 获取预览URL                                  │
│           ▼                                                │
│  ┌─────────────────┐                                       │
│  │   Django API    │                                       │
│  │   /api/preview  │                                       │
│  └─────────────────┘                                       │
│           │                                                │
└───────────┼────────────────────────────────────────────────┘
            │ 2. 转发文件流
            ▼
┌─────────────────────────────────────────────────────────────┐
│                    kkFileView 服务 (Java)                    │
│  ┌─────────────────────────────────────────────────────┐   │
│  │  - 接收文件流                                         │   │
│  │  - 调用 LibreOffice 转换                              │   │
│  │  - 生成 HTML/图片 预览                                │   │
│  └─────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────┘
```

---

## 3. 部署方案

### 3.1 Docker 部署 kkFileView

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
      - OFFICE_PREVIEW_TYPE=image    # image:图片模式(快), pdf:PDF模式(清晰)
      - CACHE_ENABLED=true
      - CACHE_CLEAN_CRON=0 0 3 * * ?  # 每天凌晨3点清理缓存
    volumes:
      - ./kkfileview-cache:/opt/kkfileview/cache
      - ./kkfileview-log:/opt/kkfileview/log
    restart: always
    networks:
      - spug-network  # 与主服务同网络

networks:
  spug-network:
    external: true
```

### 3.2 配置文件

```properties
# application.properties (挂载到容器)
server.port=8012

# 预览类型：image(图片，快) 或 pdf(PDF，清晰)
office.preview.type=image

# 缓存配置
cache.enabled=true
cache.clean.cron=0 0 3 * * ?

# 文件大小限制（MB）
file.size.max=100

# 允许跨域（重要）
cors.enabled=true
cors.origin=*
```

---

## 4. 后端实现

### 4.1 新增预览接口

```python
# apps/document/views/file/preview_office.py

import logging
import base64
import urllib.parse
from django.conf import settings
from django.views.generic import View
from libs import json_response, auth

logger = logging.getLogger(__name__)


class OfficePreviewView(View):
    """Office文件在线预览接口"""
    
    PREVIEW_TYPES = ['doc', 'docx', 'xls', 'xlsx', 'ppt', 'pptx', 'pdf']
    
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
            # 1. 获取文件对象
            file_obj = self._get_file(file_id, request.user)
            if not file_obj:
                return json_response(error='文件不存在或无权限访问')
            
            # 2. 检查文件类型
            file_ext = self._get_file_extension(file_obj.name)
            if file_ext not in self.PREVIEW_TYPES:
                return json_response(error=f'不支持的文件类型: {file_ext}')
            
            # 3. 检查文件大小
            if file_obj.file_size > 100 * 1024 * 1024:  # 100MB
                return json_response(error='文件过大，不支持在线预览')
            
            # 4. 生成预览URL
            preview_url = self._generate_preview_url(file_obj, request)
            
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
    
    def _generate_preview_url(self, file_obj, request):
        """生成kkFileView预览URL"""
        
        # 构建文件访问URL（需可被kkFileView访问）
        file_url = self._get_file_access_url(file_obj, request)
        
        # Base64编码URL（kkFileView要求）
        encoded_url = base64.b64encode(file_url.encode()).decode()
        
        # 构建预览URL
        preview_base = settings.KKFILEVIEW_URL  # http://kkfileview:8012
        preview_url = f"{preview_base}/onlinePreview?url={urllib.parse.quote(encoded_url)}"
        
        return preview_url
    
    def _get_file_access_url(self, file_obj, request):
        """
        获取文件访问URL
        
        方案：通过API代理（推荐，带权限验证）
        """
        # 生成临时token用于预览授权
        from apps.document.libs.token_utils import generate_preview_token
        token = generate_preview_token(file_obj.id, request.user.id)
        
        # 构建带token的下载URL
        base_url = settings.SITE_URL  # https://spug.example.com
        return f"{base_url}/api/document/file/{file_obj.id}/download/?preview=1&token={token}"
```

### 4.2 预览代理接口（供kkFileView调用）

```python
# apps/document/views/file/preview_proxy.py

import logging
from django.http import FileResponse, Http404
from django.views.generic import View
from apps.document.libs.token_utils import verify_preview_token

logger = logging.getLogger(__name__)


class PreviewProxyView(View):
    """
    Office预览代理接口
    
    供kkFileView服务调用，用于获取文件流
    带token验证，防止未授权访问
    """
    
    def get(self, request, file_id):
        """代理文件下载给kkFileView"""
        
        # 1. 验证预览token
        token = request.GET.get('token')
        if not token:
            return json_response(error='缺少授权token', status=401)
        
        user_id = verify_preview_token(token, file_id)
        if not user_id:
            return json_response(error='无效的授权token', status=403)
        
        # 2. 获取文件对象
        file_obj = self._get_file(file_id)
        if not file_obj:
            raise Http404('文件不存在')
        
        # 3. 返回文件流
        try:
            response = FileResponse(
                open(file_obj.file_path, 'rb'),
                content_type=self._get_content_type(file_obj.name)
            )
            response['Content-Disposition'] = f'inline; filename="{file_obj.name}"'
            return response
        except FileNotFoundError:
            logger.error(f'[PreviewProxy] 文件丢失: {file_obj.file_path}')
            return json_response(error='文件已丢失', status=404)
    
    def _get_file(self, file_id):
        """获取文件对象"""
        from apps.document.models import DocumentFilePrivate, DocumentFilePublic
        
        # 查询私有和公共空间
        file_obj = DocumentFilePrivate.objects.filter(id=file_id).first()
        if not file_obj:
            file_obj = DocumentFilePublic.objects.filter(id=file_id).first()
        return file_obj
    
    def _get_content_type(self, filename):
        """获取MIME类型"""
        import mimetypes
        return mimetypes.guess_type(filename)[0] or 'application/octet-stream'
```

### 4.3 Token工具类

```python
# apps/document/libs/token_utils.py

import jwt
import time
from django.conf import settings


def generate_preview_token(file_id, user_id, expire_seconds=300):
    """
    生成预览授权token
    
    Args:
        file_id: 文件ID
        user_id: 用户ID
        expire_seconds: 过期时间（秒），默认5分钟
    
    Returns:
        str: JWT token
    """
    payload = {
        'file_id': file_id,
        'user_id': user_id,
        'exp': int(time.time()) + expire_seconds,
        'type': 'preview'
    }
    return jwt.encode(payload, settings.SECRET_KEY, algorithm='HS256')


def verify_preview_token(token, file_id):
    """
    验证预览token
    
    Args:
        token: JWT token
        file_id: 期望的文件ID
    
    Returns:
        int: 用户ID（验证通过）或 None（验证失败）
    """
    try:
        payload = jwt.decode(token, settings.SECRET_KEY, algorithms=['HS256'])
        
        # 验证token类型和文件ID
        if payload.get('type') != 'preview':
            return None
        if payload.get('file_id') != file_id:
            return None
        
        return payload.get('user_id')
    
    except jwt.ExpiredSignatureError:
        return None
    except jwt.InvalidTokenError:
        return None
```

### 4.4 URL路由配置

```python
# apps/document/urls.py

from django.urls import path
from .views.file.preview_office import OfficePreviewView
from .views.file.preview_proxy import PreviewProxyView

urlpatterns = [
    # ... 其他路由
    
    # Office预览接口
    path('file/<int:file_id>/preview/office/', OfficePreviewView.as_view(), name='office_preview'),
    
    # 预览代理接口（供kkFileView调用）
    path('file/<int:file_id>/download/', PreviewProxyView.as_view(), name='preview_proxy'),
]
```

### 4.5 配置项

```python
# settings.py

# kkFileView 配置
KKFILEVIEW_URL = 'http://kkfileview:8012'  # kkFileView服务地址（Docker内网）
SITE_URL = 'https://spug.example.com'       # 本服务外网地址

# 预览token配置
PREVIEW_TOKEN_EXPIRE = 300  # 预览链接有效期（秒）
```

---

## 5. 前端实现

### 5.1 预览组件

```jsx
// components/OfficePreview/index.jsx
import React, { useState, useEffect } from 'react';
import { Modal, Spin, Alert, Button } from 'antd';
import { DownloadOutlined } from '@ant-design/icons';
import http from 'libs/http';

const OfficePreview = ({ visible, fileId, fileName, onClose, onDownload }) => {
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
      if (response.preview_url) {
        setPreviewUrl(response.preview_url);
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
      title={
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
          <span>预览: {fileName}</span>
          <Button 
            type="primary" 
            icon={<DownloadOutlined />}
            size="small"
            onClick={onDownload}
          >
            下载原文件
          </Button>
        </div>
      }
      visible={visible}
      onCancel={onClose}
      width="90%"
      style={{ top: 20 }}
      bodyStyle={{ height: '80vh', padding: 0 }}
      footer={null}
      destroyOnClose  // 关闭时销毁，释放内存
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
          action={
            <Button size="small" onClick={fetchPreviewUrl}>
              重试
            </Button>
          }
        />
      )}
      
      {previewUrl && !loading && (
        <iframe
          src={previewUrl}
          style={{ width: '100%', height: '100%', border: 'none' }}
          sandbox="allow-scripts allow-same-origin"
          title="Office预览"
        />
      )}
    </Modal>
  );
};

export default OfficePreview;
```

### 5.2 文件列表集成

```jsx
// 在文件列表组件中添加预览逻辑
import OfficePreview from './components/OfficePreview';

const FileList = () => {
  const [previewVisible, setPreviewVisible] = useState(false);
  const [previewFile, setPreviewFile] = useState(null);

  const handlePreview = (file) => {
    const officeExts = ['doc', 'docx', 'xls', 'xlsx', 'ppt', 'pptx'];
    const pdfExts = ['pdf'];
    const ext = file.name.split('.').pop().toLowerCase();
    
    if (officeExts.includes(ext)) {
      // Office文件使用kkFileView预览
      setPreviewFile(file);
      setPreviewVisible(true);
    } else if (pdfExts.includes(ext)) {
      // PDF使用原有预览方式
      handlePdfPreview(file);
    } else {
      // 其他文件提示下载
      message.info('该文件类型不支持在线预览，请下载后查看');
    }
  };

  return (
    <>
      {/* 文件列表渲染 */}
      
      {/* Office预览弹窗 */}
      <OfficePreview
        visible={previewVisible}
        fileId={previewFile?.id}
        fileName={previewFile?.name}
        onClose={() => setPreviewVisible(false)}
        onDownload={() => handleDownload(previewFile)}
      />
    </>
  );
};
```

---

## 6. 部署步骤

### 6.1 部署 kkFileView

```bash
# 1. 进入项目目录
cd /data/spug

# 2. 创建 kkFileView 目录
mkdir -p kkfileview
cd kkfileview

# 3. 创建 docker-compose.yml（内容见3.1节）
vim docker-compose.yml

# 4. 启动服务
docker-compose up -d

# 5. 验证服务
curl http://localhost:8012
# 应返回 kkFileView 首页
```

### 6.2 配置 Django

```python
# 1. 添加配置到 settings.py
KKFILEVIEW_URL = 'http://kkfileview:8012'  # Docker内网地址
SITE_URL = 'https://your-domain.com'       # 你的外网地址

# 2. 确保PyJWT已安装
pip install PyJWT

# 3. 重启服务
supervisorctl restart spug-api
```

### 6.3 配置前端

```bash
# 1. 复制预览组件到项目
cp OfficePreview.jsx spug_web/src/pages/document/components/

# 2. 在文件列表中引入使用
# 参考5.2节代码

# 3. 构建部署
npm run build
```

---

## 7. 安全考虑

### 7.1 访问控制

| 安全措施 | 实现方式 |
|---------|---------|
| 身份验证 | Django @auth 装饰器验证用户登录 |
| 权限检查 | 验证用户是否有权访问该文件 |
| 租户隔离 | 使用 apply_tenant_filter 确保数据隔离 |
| Token时效 | 预览URL 5分钟过期，防止长期有效 |
| 文件大小 | 限制100MB，防止大文件导致OOM |

### 7.2 网络安全

```yaml
# docker-compose 安全配置
services:
  kkfileview:
    networks:
      - spug-internal  # 仅内网访问
    ports:
      - "127.0.0.1:8012:8012"  # 不暴露到公网
    
networks:
  spug-internal:
    internal: true  # 禁止外网访问
```

### 7.3 路径安全

```python
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

## 8. 测试验证

### 8.1 功能测试

| 测试项 | 测试步骤 | 预期结果 |
|--------|---------|---------|
| Word预览 | 上传.docx，点击预览 | 正常显示文档内容 |
| Excel预览 | 上传.xlsx，点击预览 | 正常显示表格、公式 |
| PPT预览 | 上传.pptx，点击预览 | 正常显示幻灯片 |
| PDF预览 | 上传.pdf，点击预览 | 正常显示（整合到同一组件）|
| 大文件限制 | 上传150MB文件预览 | 提示"文件过大" |
| 权限控制 | 无权限用户访问预览URL | 返回403错误 |
| Token过期 | 等待5分钟后刷新预览 | 提示重新获取 |

### 8.2 性能测试

| 测试项 | 指标 | 目标 |
|--------|------|------|
| 预览加载时间 | 从点击到显示内容 | < 5秒 |
| 并发预览 | 同时10个用户预览 | 无卡顿 |
| 内存占用 | kkFileView服务 | < 2GB |
| 缓存命中 | 重复预览同一文件 | 秒开 |

---

## 9. 风险与应对

| 风险 | 影响 | 应对措施 |
|------|------|---------|
| kkFileView服务故障 | 无法预览Office | 降级为下载提示；监控告警 |
| 格式兼容性问题 | 文档显示异常 | 提供"下载原文件"按钮 |
| 大文件OOM | 服务崩溃 | 100MB限制 + 内存监控 |
| 安全漏洞 | 未授权访问 | Token验证 + 内网部署 |
| LibreOffice转换慢 | 首次预览慢 | 开启缓存 + 异步预转换 |

---

## 10. 后续优化

1. **缓存预热**：热门文件预先生成预览缓存
2. **水印功能**：预览时添加用户水印
3. **批注功能**：支持在预览时添加批注
4. **移动端适配**：优化手机端预览体验
5. **编辑功能**：集成 OnlyOffice 实现文档在线编辑

---

## 11. 总结

| 项目 | 内容 |
|------|------|
| **方案** | kkFileView 独立部署 |
| **工作量** | 后端2人日 + 前端1人日 + 部署0.5人日 |
| **依赖** | Docker、Java（容器内，无需关心）|
| **优点** | 格式兼容好、私有化部署、成熟稳定 |
| **缺点** | 需额外部署Java服务、占用资源较多 |

**推荐立即实施**，kkFileView是目前国内最成熟的Office预览方案。
