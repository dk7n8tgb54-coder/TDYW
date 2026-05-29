# Office 文件在线预览功能方案

## 一、需求概述

基于 Spug 资料库模块现有架构，实现 Office 文件（doc、docx、xls、xlsx、ppt、pptx）的在线预览功能。

## 二、现有架构分析

### 2.1 后端文件处理流程
- **上传**: `FileUploadView` (upload.py) - 接收文件并保存到存储目录
- **下载**: `FileDownloadView` (download.py) - 提供文件下载
- **预览**: `FilePreviewView` (preview.py) - 支持图片、PDF、视频预览

### 2.2 前端预览组件
- **PreviewModal.js** - 预览弹窗组件，支持图片、视频、PDF

### 2.3 文件存储结构
```
/data/spug/spug_api/storage/documents/
├── public/          # 公共空间
└── private/         # 私有空间（按用户ID分目录）
```

## 三、技术方案选型

### 方案对比

| 方案 | 优点 | 缺点 | 推荐度 |
|------|------|------|--------|
| **OnlyOffice Document Server** | 功能完整，支持编辑，开源 | 需要独立部署服务 | ⭐⭐⭐⭐⭐ |
| **LibreOffice + PDF转换** | 轻量，无需额外服务 | 预览为PDF，非原生体验 | ⭐⭐⭐⭐ |
| **Microsoft Office Online** | 原生体验好 | 需要微软服务，有数据安全风险 | ⭐⭐⭐ |
| **KKFileView** | 国产开源，集成简单 | 依赖Java，资源占用大 | ⭐⭐⭐⭐ |

### 推荐方案：OnlyOffice Document Server

**理由**：
1. 完整的 Office 文档预览和编辑能力
2. 开源免费，社区活跃
3. 与 Spug 的容器化部署方式兼容
4. 支持 docx、xlsx、pptx 等现代格式

## 四、详细实现方案

### 4.1 架构设计

```
┌─────────────────────────────────────────────────────────────┐
│                        用户浏览器                            │
└───────────────────────┬─────────────────────────────────────┘
                        │
                        ▼
┌─────────────────────────────────────────────────────────────┐
│                    Spug Web 前端                            │
│  ┌───────────────────────────────────────────────────────┐  │
│  │  PreviewModal.js (扩展)                               │  │
│  │  - 检测 Office 文件类型                                │  │
│  │  - 嵌入 OnlyOffice 编辑器                              │  │
│  └───────────────────────────────────────────────────────┘  │
└───────────────────────┬─────────────────────────────────────┘
                        │
                        ▼
┌─────────────────────────────────────────────────────────────┐
│                   Spug API 后端                             │
│  ┌───────────────────────────────────────────────────────┐  │
│  │  FilePreviewView (preview.py)                         │  │
│  │  - /api/document/preview/ - 现有接口                   │  │
│  │  - /api/document/preview/office/ - 新增接口            │  │
│  │    * 返回文档配置信息（URL、Key等）                     │  │
│  └───────────────────────────────────────────────────────┘  │
│  ┌───────────────────────────────────────────────────────┐  │
│  │  OfficePreviewService (新增)                          │  │
│  │  - 生成文档预览 Token                                  │  │
│  │  - 与 OnlyOffice 服务通信                              │  │
│  │  - 缓存预览会话                                        │  │
│  └───────────────────────────────────────────────────────┘  │
└───────────────────────┬─────────────────────────────────────┘
                        │
                        ▼
┌─────────────────────────────────────────────────────────────┐
│              OnlyOffice Document Server                     │
│  - 独立容器部署                                            │
│  - 提供文档渲染和预览能力                                   │
│  - 回调 Spug API 进行权限验证                               │
└─────────────────────────────────────────────────────────────┘
```

### 4.2 后端实现

#### 4.2.1 新增 Office 预览服务

**文件**: `spug_api/apps/document/services/office_preview.py`

```python
# Copyright: (c) OpenSpug Organization
# Released under the AGPL-3.0 License.
"""
Office 文档预览服务
集成 OnlyOffice Document Server
"""

import os
import jwt
import uuid
import logging
from datetime import datetime, timedelta
from django.conf import settings
from django.core.cache import cache

logger = logging.getLogger(__name__)


class OfficePreviewService:
    """Office 文档预览服务"""
    
    # 支持的文件类型
    SUPPORTED_TYPES = {
        'doc': 'word',
        'docx': 'word',
        'xls': 'cell',
        'xlsx': 'cell',
        'ppt': 'slide',
        'pptx': 'slide',
        'odt': 'word',
        'ods': 'cell',
        'odp': 'slide',
    }
    
    # MIME 类型映射
    MIME_TYPES = {
        'doc': 'application/msword',
        'docx': 'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
        'xls': 'application/vnd.ms-excel',
        'xlsx': 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
        'ppt': 'application/vnd.ms-powerpoint',
        'pptx': 'application/vnd.openxmlformats-officedocument.presentationml.presentation',
    }
    
    def __init__(self):
        self.document_server_url = getattr(settings, 'ONLYOFFICE_SERVER_URL', 'http://onlyoffice:80')
        self.jwt_secret = getattr(settings, 'ONLYOFFICE_JWT_SECRET', settings.SECRET_KEY)
        self.callback_url = getattr(settings, 'ONLYOFFICE_CALLBACK_URL', '/api/document/office/callback/')
    
    def is_office_file(self, filename):
        """检查是否为 Office 文件"""
        ext = os.path.splitext(filename.lower())[1][1:]
        return ext in self.SUPPORTED_TYPES
    
    def get_document_type(self, filename):
        """获取文档类型 (word/cell/slide)"""
        ext = os.path.splitext(filename.lower())[1][1:]
        return self.SUPPORTED_TYPES.get(ext)
    
    def generate_preview_config(self, file_obj, user, is_public=False):
        """
        生成 OnlyOffice 预览配置
        
        Args:
            file_obj: 文件模型实例
            user: 当前用户
            is_public: 是否为公共空间
            
        Returns:
            dict: OnlyOffice 配置
        """
        # 生成唯一文档 Key
        doc_key = self._generate_doc_key(file_obj, user)
        
        # 生成文件下载 URL（临时 Token）
        file_url = self._generate_file_url(file_obj, user, is_public)
        
        # 生成回调 Token
        callback_token = self._generate_callback_token(file_obj, user)
        
        # 缓存预览会话
        self._cache_preview_session(doc_key, file_obj, user, callback_token)
        
        # 构建 OnlyOffice 配置
        config = {
            'document': {
                'fileType': self._get_file_extension(file_obj.name),
                'key': doc_key,
                'url': file_url,
                'title': file_obj.display_name or file_obj.name,
            },
            'documentType': self.get_document_type(file_obj.name),
            'editorConfig': {
                'mode': 'view',  # 仅预览模式
                'lang': 'zh-CN',
                'user': {
                    'id': str(user.id),
                    'name': user.username,
                },
                'permissions': {
                    'edit': False,
                    'download': True,
                    'print': True,
                }
            },
            'callbackUrl': f"{settings.BASE_URL}{self.callback_url}?token={callback_token}",
        }
        
        # 如果配置了 JWT，生成 Token
        if self.jwt_secret:
            config['token'] = self._generate_jwt_token(config)
        
        return {
            'server_url': self.document_server_url,
            'config': config,
        }
    
    def _generate_doc_key(self, file_obj, user):
        """生成文档唯一标识"""
        # 基于文件ID、修改时间和用户ID生成
        key_data = f"{file_obj.id}:{file_obj.updated_at}:{user.id}"
        return str(uuid.uuid5(uuid.NAMESPACE_DNS, key_data))
    
    def _generate_file_url(self, file_obj, user, is_public):
        """生成文件下载 URL（带临时 Token）"""
        from django.urls import reverse
        
        # 生成临时访问 Token
        token_data = {
            'file_id': file_obj.id,
            'user_id': user.id,
            'is_public': is_public,
            'exp': datetime.utcnow() + timedelta(hours=1),
        }
        token = jwt.encode(token_data, self.jwt_secret, algorithm='HS256')
        
        # 构建文件下载 URL
        return f"{settings.BASE_URL}/api/document/office/file/?token={token}"
    
    def _generate_callback_token(self, file_obj, user):
        """生成回调验证 Token"""
        token_data = {
            'file_id': file_obj.id,
            'user_id': user.id,
            'exp': datetime.utcnow() + timedelta(hours=24),
        }
        return jwt.encode(token_data, self.jwt_secret, algorithm='HS256')
    
    def _cache_preview_session(self, doc_key, file_obj, user, callback_token):
        """缓存预览会话信息"""
        cache_key = f"office_preview:{doc_key}"
        cache_data = {
            'file_id': file_obj.id,
            'user_id': user.id,
            'callback_token': callback_token,
            'created_at': datetime.utcnow().isoformat(),
        }
        cache.set(cache_key, cache_data, timeout=86400)  # 24小时
    
    def _generate_jwt_token(self, config):
        """生成 OnlyOffice JWT Token"""
        return jwt.encode(config, self.jwt_secret, algorithm='HS256')
    
    def _get_file_extension(self, filename):
        """获取文件扩展名"""
        return os.path.splitext(filename.lower())[1][1:]
    
    def verify_callback_token(self, token):
        """验证回调 Token"""
        try:
            payload = jwt.decode(token, self.jwt_secret, algorithms=['HS256'])
            return payload
        except jwt.ExpiredSignatureError:
            logger.warning("[OfficePreview] Callback token expired")
            return None
        except jwt.InvalidTokenError as e:
            logger.warning(f"[OfficePreview] Invalid callback token: {e}")
            return None
    
    def handle_callback(self, data, token):
        """
        处理 OnlyOffice 回调
        
        Args:
            data: 回调数据
            token: 验证 Token
            
        Returns:
            dict: 响应数据
        """
        # 验证 Token
        payload = self.verify_callback_token(token)
        if not payload:
            return {'error': 1, 'message': 'Invalid token'}
        
        status = data.get('status')
        
        # 0 - 找不到文档
        # 1 - 正在编辑
        # 2 - 准备保存
        # 3 - 保存错误
        # 4 - 文档关闭
        # 6 - 正在保存
        # 7 - 强制保存错误
        
        if status == 0:
            logger.error(f"[OfficePreview] Document not found: {data}")
        elif status == 1:
            logger.info(f"[OfficePreview] Document being edited: {data.get('key')}")
        elif status == 2 or status == 6:
            # 保存完成（预览模式下通常不会触发）
            logger.info(f"[OfficePreview] Document saved: {data.get('key')}")
        elif status == 3 or status == 7:
            logger.error(f"[OfficePreview] Save error: {data}")
        elif status == 4:
            logger.info(f"[OfficePreview] Document closed: {data.get('key')}")
            # 清理缓存
            self._cleanup_session(data.get('key'))
        
        return {'error': 0}
    
    def _cleanup_session(self, doc_key):
        """清理预览会话"""
        cache_key = f"office_preview:{doc_key}"
        cache.delete(cache_key)
        logger.info(f"[OfficePreview] Cleaned up session: {doc_key}")
```

#### 4.2.2 扩展预览视图

**修改文件**: `spug_api/apps/document/views/file/preview.py`

```python
# 在现有 FilePreviewView 中添加 Office 预览支持

from ...services.office_preview import OfficePreviewService

class FilePreviewView(View):
    """文件预览视图 - 支持图片、PDF、视频流、Office文档"""

    @auth('document.document.view')
    def get(self, request):
        form, error = JsonParser(
            Argument('id', type=int, help='参数错误'),
            Argument('is_public', type=bool, required=False, default=False),
            Argument('type', required=False, default='')  # 新增：预览类型
        ).parse(request.GET)
        
        if error is not None:
            return json_response(error=error)
            
        FileModel = get_file_model(is_public=form.is_public)

        file_query = FileModel.objects.filter(pk=form.id)
        if not form.is_public:
            file_query = apply_tenant_filter(file_query, request.user, strict_mode=True)
        file = file_query.select_related('created_by').first()
        
        if not file:
            return json_response(error='文件不存在')
            
        if not os.path.exists(file.file_path):
            return json_response(error='文件不存在')

        # 如果是 Office 预览请求
        if form.type == 'office':
            return self._handle_office_preview(request, file, form.is_public)
        
        # 原有预览逻辑...
        # 支持图片预览
        if file.file_type.startswith('image/'):
            with open(file.file_path, 'rb') as f:
                response = HttpResponse(f.read())
                response['Content-Type'] = file.file_type
                return response
        
        # 支持PDF预览
        elif file.file_type == 'application/pdf' or file.file_type.startswith('application/pdf'):
            with open(file.file_path, 'rb') as f:
                response = HttpResponse(f.read())
                response['Content-Type'] = 'application/pdf'
                response['Content-Disposition'] = f'inline; filename="{file.name}"'
                return response
        
        # 支持视频流
        elif file.file_type.startswith('video/'):
            return self._handle_video_stream(request, file)
        
        # 检查是否为 Office 文件
        office_service = OfficePreviewService()
        if office_service.is_office_file(file.name):
            # 返回 Office 预览配置
            return self._handle_office_preview(request, file, form.is_public)
        
        else:
            return json_response(error='该文件类型不支持在线预览')

    def _handle_office_preview(self, request, file, is_public):
        """处理 Office 文档预览"""
        office_service = OfficePreviewService()
        
        try:
            config = office_service.generate_preview_config(
                file_obj=file,
                user=request.user,
                is_public=is_public
            )
            return json_response(data=config)
        except Exception as e:
            logger.error(f'[Document] Office preview error: {e}', exc_info=True)
            return json_response(error=f'生成预览失败: {str(e)}')
```

#### 4.2.3 新增 Office 文件服务视图

**文件**: `spug_api/apps/document/views/file/office_file.py`

```python
# Copyright: (c) OpenSpug Organization
# Released under the AGPL-3.0 License.
"""
Office 预览文件服务
提供带 Token 验证的文件下载（供 OnlyOffice 服务调用）
"""

import jwt
import logging
from django.views.generic import View
from django.http import HttpResponse, HttpResponseForbidden
from django.conf import settings

from libs import json_response
from ...libs.document_utils import get_file_model

logger = logging.getLogger(__name__)


class OfficeFileView(View):
    """
    Office 预览文件服务
    用于 OnlyOffice Document Server 获取文件内容
    """
    
    def get(self, request):
        """提供文件下载（带 Token 验证）"""
        token = request.GET.get('token')
        
        if not token:
            return HttpResponseForbidden('Missing token')
        
        try:
            # 验证 Token
            payload = jwt.decode(
                token, 
                getattr(settings, 'ONLYOFFICE_JWT_SECRET', settings.SECRET_KEY),
                algorithms=['HS256']
            )
            
            file_id = payload.get('file_id')
            user_id = payload.get('user_id')
            is_public = payload.get('is_public', False)
            
            # 获取文件
            FileModel = get_file_model(is_public=is_public)
            file = FileModel.objects.filter(pk=file_id).first()
            
            if not file or not os.path.exists(file.file_path):
                return HttpResponseForbidden('File not found')
            
            # 返回文件内容
            with open(file.file_path, 'rb') as f:
                response = HttpResponse(f.read())
                response['Content-Type'] = file.file_type or 'application/octet-stream'
                response['Content-Disposition'] = f'inline; filename="{file.name}"'
                response['Access-Control-Allow-Origin'] = '*'
                response['Access-Control-Allow-Methods'] = 'GET, OPTIONS'
                return response
                
        except jwt.ExpiredSignatureError:
            logger.warning("[OfficeFile] Token expired")
            return HttpResponseForbidden('Token expired')
        except jwt.InvalidTokenError as e:
            logger.warning(f"[OfficeFile] Invalid token: {e}")
            return HttpResponseForbidden('Invalid token')
        except Exception as e:
            logger.error(f"[OfficeFile] Error: {e}", exc_info=True)
            return HttpResponseForbidden('Internal error')


class OfficeCallbackView(View):
    """
    OnlyOffice 回调处理
    处理文档打开、关闭、保存等事件
    """
    
    def post(self, request):
        """处理 OnlyOffice 回调"""
        from ...services.office_preview import OfficePreviewService
        
        token = request.GET.get('token')
        
        try:
            import json
            data = json.loads(request.body)
            
            office_service = OfficePreviewService()
            result = office_service.handle_callback(data, token)
            
            return json_response(data=result)
            
        except json.JSONDecodeError:
            logger.error("[OfficeCallback] Invalid JSON")
            return json_response(error='Invalid JSON')
        except Exception as e:
            logger.error(f"[OfficeCallback] Error: {e}", exc_info=True)
            return json_response(error='Internal error')
```

#### 4.2.4 URL 配置

**修改文件**: `spug_api/apps/document/urls.py`

```python
from django.urls import path
from .views.file import (
    FileView, 
    FileUploadView, 
    FileDownloadView, 
    FilePreviewView,
    FileCopyView,
    FileMoveView,
    FileRenameView,
)
from .views.file.office_file import OfficeFileView, OfficeCallbackView

urlpatterns = [
    # ... 现有路由 ...
    
    # Office 预览相关
    path('office/file/', OfficeFileView.as_view(), name='document-office-file'),
    path('office/callback/', OfficeCallbackView.as_view(), name='document-office-callback'),
]
```

#### 4.2.5 配置项

**修改文件**: `spug_api/apps/config.py` 或 `settings.py`

```python
# OnlyOffice 配置
ONLYOFFICE_CONFIG = {
    'SERVER_URL': os.environ.get('ONLYOFFICE_SERVER_URL', 'http://onlyoffice:80'),
    'JWT_SECRET': os.environ.get('ONLYOFFICE_JWT_SECRET', SECRET_KEY),
    'CALLBACK_URL': '/api/document/office/callback/',
}

# 合并到 settings
ONLYOFFICE_SERVER_URL = ONLYOFFICE_CONFIG['SERVER_URL']
ONLYOFFICE_JWT_SECRET = ONLYOFFICE_CONFIG['JWT_SECRET']
ONLYOFFICE_CALLBACK_URL = ONLYOFFICE_CONFIG['CALLBACK_URL']
```

### 4.3 前端实现

#### 4.3.1 扩展预览组件

**修改文件**: `spug_web/src/pages/document/PreviewModal.js`

```javascript
/**
 * Copyright (c) OpenSpug Organization
 * Released under the AGPL-3.0 License.
 */
import React from 'react';
import { observer } from 'mobx-react';
import { Modal, Spin } from 'antd';
import { X_TOKEN } from 'libs';
import uploadUIStore from './stores/upload/ui';
import navigationStore from './stores/navigation';
import ReactPlayer from 'react-player';
import styles from './PreviewModal.module.less';

// OnlyOffice 文档编辑器组件
class OnlyOfficeEditor extends React.Component {
  componentDidMount() {
    this.loadOnlyOfficeScript();
  }

  componentWillUnmount() {
    // 清理 OnlyOffice 实例
    if (window.DocEditor) {
      const editors = document.querySelectorAll('[id^="onlyoffice-editor-"]');
      editors.forEach(editor => {
        const instance = window.DocEditor.instances[editor.id];
        if (instance) {
          instance.destroyEditor();
        }
      });
    }
  }

  loadOnlyOfficeScript = () => {
    const { serverUrl } = this.props;
    const scriptUrl = `${serverUrl}/web-apps/apps/api/documents/api.js`;
    
    // 检查脚本是否已加载
    if (document.querySelector(`script[src="${scriptUrl}"]`)) {
      this.initEditor();
      return;
    }

    const script = document.createElement('script');
    script.src = scriptUrl;
    script.async = true;
    script.onload = this.initEditor;
    script.onerror = () => {
      console.error('Failed to load OnlyOffice script');
    };
    document.body.appendChild(script);
  };

  initEditor = () => {
    const { config } = this.props;
    const editorId = 'onlyoffice-editor-' + Date.now();
    
    if (window.DocEditor) {
      new window.DocEditor(editorId, config);
    }
  };

  render() {
    const editorId = 'onlyoffice-editor-' + Date.now();
    return <div id={editorId} style={{ width: '100%', height: '100%' }} />;
  }
}

class PreviewModal extends React.Component {
  state = {
    officeConfig: null,
    officeLoading: false,
    officeError: null,
  };

  handleClose = () => {
    this.setState({
      officeConfig: null,
      officeLoading: false,
      officeError: null,
    });
    uploadUIStore.closePreview();
  };

  // 获取 Office 预览配置
  fetchOfficeConfig = async (file) => {
    this.setState({ officeLoading: true, officeError: null });
    
    try {
      const isPublic = navigationStore.isPublic;
      const response = await fetch(
        `/api/document/preview/?id=${file.id}&type=office&is_public=${isPublic}&x-token=${X_TOKEN}`
      );
      
      const result = await response.json();
      
      if (result.error) {
        throw new Error(result.error);
      }
      
      this.setState({
        officeConfig: result.data,
        officeLoading: false,
      });
    } catch (error) {
      console.error('Failed to load Office preview:', error);
      this.setState({
        officeError: error.message,
        officeLoading: false,
      });
    }
  };

  render() {
    const file = uploadUIStore.previewFile;
    const visible = uploadUIStore.previewVisible;
    const isPublic = navigationStore.isPublic;
    const { officeConfig, officeLoading, officeError } = this.state;

    // 判断文件类型
    const isImage = file?.file_type?.startsWith('image/');
    const isVideo = file?.file_type?.startsWith('video/');
    const fileName = file?.display_name || file?.name || '';
    const isPDF = file?.file_type === 'application/pdf' ||
                  file?.file_type?.startsWith('application/pdf') ||
                  fileName.toLowerCase().endsWith('.pdf');
    
    // 判断 Office 文件
    const officeExtensions = ['.doc', '.docx', '.xls', '.xlsx', '.ppt', '.pptx', '.odt', '.ods', '.odp'];
    const isOffice = officeExtensions.some(ext => 
      fileName.toLowerCase().endsWith(ext)
    );

    // 如果是 Office 文件且配置未加载，获取配置
    if (isOffice && visible && !officeConfig && !officeLoading && !officeError) {
      this.fetchOfficeConfig(file);
    }

    return (
      <Modal
        title={file?.display_name || file?.name || '预览'}
        visible={visible}
        onCancel={this.handleClose}
        onOk={this.handleClose}
        footer={null}
        width="90%"
        style={{ top: 20, paddingBottom: 0 }}
        bodyStyle={{ padding: 0, height: 'calc(100vh - 100px)' }}
        destroyOnClose
        maskClosable
        keyboard
        afterClose={() => {
          if (document.activeElement instanceof HTMLElement) {
            document.activeElement.blur();
          }
        }}
        forceRender={false}
      >
        {isImage ? (
          <div className={styles.previewContainer}>
            <img
              src={`/api/document/preview/?id=${file.id}&x-token=${X_TOKEN}&is_public=${isPublic}`}
              alt={file?.display_name || file?.name}
              style={{ maxWidth: '100%', maxHeight: '100%', objectFit: 'contain' }}
            />
          </div>
        ) : isVideo ? (
          visible && (
            <div className={styles.previewContainer}>
              <ReactPlayer
                url={`/api/document/preview/?id=${file.id}&x-token=${X_TOKEN}&is_public=${isPublic}`}
                controls
                width="100%"
                height="100%"
              />
            </div>
          )
        ) : isPDF ? (
          <div className={styles.previewContainer} style={{ height: '100%' }}>
            <iframe
              src={`/api/document/preview/?id=${file.id}&x-token=${X_TOKEN}&is_public=${isPublic}`}
              style={{
                width: '100%',
                height: '100%',
                border: 'none'
              }}
              title="PDF Preview"
            />
          </div>
        ) : isOffice ? (
          <div className={styles.previewContainer} style={{ height: '100%' }}>
            {officeLoading ? (
              <div style={{ 
                display: 'flex', 
                justifyContent: 'center', 
                alignItems: 'center',
                height: '100%'
              }}>
                <Spin size="large" tip="加载 Office 预览..." />
              </div>
            ) : officeError ? (
              <div className={styles.noPreview}>
                <div className={styles.icon} role="img" aria-label="错误">⚠️</div>
                <div>Office 预览加载失败</div>
                <div className={styles.hint}>{officeError}</div>
              </div>
            ) : officeConfig ? (
              <OnlyOfficeEditor 
                serverUrl={officeConfig.server_url}
                config={officeConfig.config}
              />
            ) : null}
          </div>
        ) : (
          <div className={styles.noPreview}>
            <div className={styles.icon} role="img" aria-label="文件" title="文件">📄</div>
            <div>该文件类型不支持在线预览</div>
            <div className={styles.hint}>请下载文件后使用对应软件打开</div>
          </div>
        )}
      </Modal>
    );
  }
}

export default observer(PreviewModal);
```

### 4.4 Docker 部署配置

#### 4.4.1 OnlyOffice 服务配置

**文件**: `docker-compose.office.yml`

```yaml
version: '3.8'

services:
  onlyoffice:
    image: onlyoffice/documentserver:7.5
    container_name: onlyoffice
    restart: always
    ports:
      - "8085:80"  # OnlyOffice 服务端口
    environment:
      - JWT_ENABLED=true
      - JWT_SECRET=${ONLYOFFICE_JWT_SECRET:-your-secret-key}
      - JWT_HEADER=Authorization
    volumes:
      - onlyoffice_data:/var/www/onlyoffice/Data
      - onlyoffice_logs:/var/log/onlyoffice
    networks:
      - spug-network

volumes:
  onlyoffice_data:
  onlyoffice_logs:

networks:
  spug-network:
    external: true  # 使用 Spug 现有网络
```

#### 4.4.2 集成到现有 Docker Compose

在 `docker-compose.yml` 中添加：

```yaml
services:
  # ... 现有服务 ...
  
  onlyoffice:
    image: onlyoffice/documentserver:7.5
    container_name: spug-onlyoffice
    restart: always
    ports:
      - "8085:80"
    environment:
      - JWT_ENABLED=true
      - JWT_SECRET=${ONLYOFFICE_JWT_SECRET:-spug-onlyoffice-secret}
    volumes:
      - onlyoffice_data:/var/www/onlyoffice/Data
      - onlyoffice_logs:/var/log/onlyoffice
    networks:
      - spug-net

volumes:
  # ... 现有卷 ...
  onlyoffice_data:
  onlyoffice_logs:
```

#### 4.4.3 Nginx 代理配置（可选）

如果需要统一域名访问，在 Nginx 中添加：

```nginx
# OnlyOffice 服务代理
location /onlyoffice/ {
    proxy_pass http://onlyoffice/;
    proxy_http_version 1.1;
    proxy_set_header Upgrade $http_upgrade;
    proxy_set_header Connection "upgrade";
    proxy_set_header Host $host;
    proxy_set_header X-Real-IP $remote_addr;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Host $server_name;
}
```

## 五、依赖安装

### 5.1 Python 依赖

在 `spug_api/requirements.txt` 中添加：

```
# Office 预览相关
PyJWT>=2.8.0
```

### 5.2 前端依赖

无需额外依赖，使用 OnlyOffice 提供的 CDN 脚本。

## 六、安全考虑

### 6.1 权限控制
- Office 预览复用现有 `document.document.view` 权限
- 文件下载 Token 1小时过期
- 回调 Token 24小时过期
- 支持租户隔离（私有空间）

### 6.2 数据安全
- OnlyOffice 服务可部署在内网
- 文件通过临时 Token 访问，不暴露真实路径
- 支持 JWT 签名验证

### 6.3 网络隔离
```
用户浏览器 → Spug Web → Spug API → OnlyOffice 服务
                ↓
            文件下载 (临时Token)
```

## 七、测试清单

### 7.1 功能测试
- [ ] doc/docx 文件预览
- [ ] xls/xlsx 文件预览
- [ ] ppt/pptx 文件预览
- [ ] 大文件 (>10MB) 预览性能
- [ ] 多租户隔离验证
- [ ] Token 过期处理

### 7.2 兼容性测试
- [ ] Chrome/Edge 浏览器
- [ ] Firefox 浏览器
- [ ] Safari 浏览器
- [ ] 移动端浏览器（基础预览）

## 八、备选方案

如果 OnlyOffice 部署复杂，可考虑：

### 方案 B：LibreOffice 转换预览

```python
# 使用 LibreOffice 将 Office 转为 PDF 预览
import subprocess

def convert_to_pdf(input_path, output_dir):
    cmd = [
        'soffice',
        '--headless',
        '--convert-to', 'pdf',
        '--outdir', output_dir,
        input_path
    ]
    subprocess.run(cmd, check=True)
```

**优点**：无需额外服务，轻量级
**缺点**：仅支持静态预览，无交互

### 方案 C：KKFileView 集成

使用国产开源项目 KKFileView，支持更多格式。

---

**文档版本**: v1.0
**编写日期**: 2026-03-28
**适用版本**: Spug 3.0+
