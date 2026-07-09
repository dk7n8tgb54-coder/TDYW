/**
 * Copyright (c) OpenSpug Organization. https://github.com/openspug/spug
 * Copyright (c) <spug.dev@gmail.com>
 * Released under the AGPL-3.0 License.
 */
import React from 'react';
import { observer } from 'mobx-react';
import { Modal, Spin } from 'antd';
import { AudioIcon, FileIcon as FileTypeIcon } from './components/FileTypeIcon';
import http from 'libs/http';
import { appendSystemFolderParam } from 'libs/systemFolderContext';
import uploadUIStore from './stores/upload/ui';
import navigationStore from './stores/navigation';
import ReactPlayer from 'react-player';
import AceEditor from 'react-ace';
import styles from './PreviewModal.module.less';

// Ace Editor modes
import 'ace-builds/src-noconflict/mode-python';
import 'ace-builds/src-noconflict/mode-javascript';
import 'ace-builds/src-noconflict/mode-typescript';
import 'ace-builds/src-noconflict/mode-java';
import 'ace-builds/src-noconflict/mode-c_cpp';
import 'ace-builds/src-noconflict/mode-golang';
import 'ace-builds/src-noconflict/mode-rust';
import 'ace-builds/src-noconflict/mode-ruby';
import 'ace-builds/src-noconflict/mode-php';
import 'ace-builds/src-noconflict/mode-html';
import 'ace-builds/src-noconflict/mode-css';
import 'ace-builds/src-noconflict/mode-json';
import 'ace-builds/src-noconflict/mode-xml';
import 'ace-builds/src-noconflict/mode-yaml';
import 'ace-builds/src-noconflict/mode-toml';
import 'ace-builds/src-noconflict/mode-sh';
import 'ace-builds/src-noconflict/mode-sql';
import 'ace-builds/src-noconflict/mode-markdown';
import 'ace-builds/src-noconflict/mode-lua';
import 'ace-builds/src-noconflict/mode-scala';
import 'ace-builds/src-noconflict/mode-kotlin';
import 'ace-builds/src-noconflict/mode-swift';
import 'ace-builds/src-noconflict/mode-dart';
import 'ace-builds/src-noconflict/mode-powershell';
import 'ace-builds/src-noconflict/mode-batchfile';
import 'ace-builds/src-noconflict/mode-protobuf';
import 'ace-builds/src-noconflict/mode-ini';
import 'ace-builds/src-noconflict/mode-csv';
import 'ace-builds/src-noconflict/mode-text';
import 'ace-builds/src-noconflict/mode-gitignore';

// Ace Editor themes
import 'ace-builds/src-noconflict/theme-tomorrow';
import 'ace-builds/src-noconflict/theme-monokai';

// 文件类型检测工具
const CODE_EXTENSIONS = new Set([
  '.py', '.js', '.jsx', '.ts', '.tsx', '.java', '.c', '.cpp', '.h', '.hpp',
  '.go', '.rs', '.rb', '.php', '.vue', '.sh', '.bash', '.zsh', '.yaml', '.yml',
  '.toml', '.sql', '.md', '.csv', '.log', '.ini', '.cfg', '.conf', '.env',
  '.dockerfile', '.tf', '.proto', '.lua', '.r', '.scala', '.kt', '.swift',
  '.dart', '.ps1', '.bat', '.makefile', '.gitignore',
]);

const OFFICE_EXTENSIONS = new Set([
  '.doc', '.docx', '.xls', '.xlsx', '.ppt', '.pptx',
]);

const OFFICE_MIME_TYPES = new Set([
  'application/msword',
  'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
  'application/vnd.ms-excel',
  'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
  'application/vnd.ms-powerpoint',
  'application/vnd.openxmlformats-officedocument.presentationml.presentation',
]);

const TEXT_APP_TYPES = new Set([
  'application/json',
  'application/xml',
  'application/javascript',
  'application/x-javascript',
]);

/**
 * 判断是否为代码/文本文件
 */
function isCodeFile(file) {
  if (!file) return false;
  if (file.file_type?.startsWith('text/')) return true;
  if (TEXT_APP_TYPES.has(file.file_type)) return true;
  const fileName = file.display_name || file.name || '';
  const ext = getFileExtension(fileName);
  if (ext && CODE_EXTENSIONS.has(ext)) return true;
  const basename = fileName.toLowerCase();
  if (['makefile', 'dockerfile', '.gitignore', '.env', 'readme', 'license'].includes(basename)) return true;
  return false;
}

/**
 * 判断是否为Office文件
 */
function isOfficeFile(file) {
  if (!file) return false;
  if (OFFICE_MIME_TYPES.has(file.file_type)) return true;
  const fileName = file.display_name || file.name || '';
  const ext = getFileExtension(fileName);
  return ext && OFFICE_EXTENSIONS.has(ext);
}

/**
 * 获取文件扩展名（小写）
 */
function getFileExtension(fileName) {
  if (!fileName) return '';
  const lastDot = fileName.lastIndexOf('.');
  if (lastDot === -1) return '';
  return fileName.substring(lastDot).toLowerCase();
}

class PreviewModal extends React.Component {
  state = {
    textContent: '',
    textLanguage: 'text',
    textLoading: false,
    textError: '',
    officeUrl: '',
    officeLoading: false,
    officeError: '',
    // 【H-2修复】短时效预览令牌，替代将 x-token 暴露在 URL 中
    previewToken: '',
    previewTokenLoading: false,
  };

  _prevFileId = null;
  _prevVisible = false;

  componentDidUpdate() {
    const file = uploadUIStore.previewFile;
    const visible = uploadUIStore.previewVisible;

    // 检测是否需要加载数据
    if (visible && file && (file.id !== this._prevFileId || (visible && !this._prevVisible))) {
      this._prevFileId = file.id;
      this._prevVisible = visible;

      // 【H-2修复】需要 URL 预览的文件类型，先获取 preview_token
      const isImage = file?.file_type?.startsWith('image/');
      const isVideo = file?.file_type?.startsWith('video/');
      const isAudio = file?.file_type?.startsWith('audio/');
      const isPDF = file?.file_type === 'application/pdf' ||
                    file?.file_type?.startsWith('application/pdf') ||
                    (file?.display_name || file?.name || '').toLowerCase().endsWith('.pdf');

      if (isImage || isVideo || isAudio || isPDF) {
        this.fetchPreviewToken(file);
      }

      if (isCodeFile(file)) {
        this.fetchTextContent(file);
      } else if (isOfficeFile(file)) {
        this.fetchOfficeUrl(file);
      }
    }

    if (!visible && this._prevVisible) {
      // 弹窗关闭时清理状态
      this._prevVisible = false;
    }
  }

  componentWillUnmount() {
    // 清理状态
    this._prevFileId = null;
    this._prevVisible = false;
  }

  fetchTextContent = (file) => {
    const isPublic = navigationStore.isPublic;
    this.setState({ textLoading: true, textError: '', textContent: '' });
    
    http.get(`/api/document/text_content/?id=${file.id}&is_public=${isPublic}`)
      .then((data) => {
        this.setState({
          textLoading: false,
          textContent: data.content,
          textLanguage: data.language || 'text',
        });
      })
      .catch((err) => {
        this.setState({ textLoading: false, textError: typeof err === 'string' ? err : '加载文件内容失败' });
      });
  };

  fetchOfficeUrl = (file) => {
    const isPublic = navigationStore.isPublic;
    this.setState({ officeLoading: true, officeError: '', officeUrl: '' });
    
    http.get(`/api/document/office_preview_url/?id=${file.id}&is_public=${isPublic}`)
      .then((data) => {
        this.setState({
          officeLoading: false,
          officeUrl: data.preview_url,
        });
      })
      .catch((err) => {
        this.setState({ officeLoading: false, officeError: typeof err === 'string' ? err : 'Office预览服务不可用' });
      });
  };

  // 【H-2修复】获取短时效预览令牌，替代将 x-token 暴露在 URL 中
  fetchPreviewToken = (file) => {
    const isPublic = navigationStore.isPublic;
    this.setState({ previewTokenLoading: true, previewToken: '' });
    
    http.get(`/api/document/preview_token/?id=${file.id}&is_public=${isPublic}`)
      .then((data) => {
        this.setState({ previewTokenLoading: false, previewToken: data.preview_token });
      })
      .catch((err) => {
        this.setState({ previewTokenLoading: false, previewToken: '' });
      });
  };

  handleClose = () => {
    this.setState({
      textContent: '',
      textLanguage: 'text',
      textLoading: false,
      textError: '',
      officeUrl: '',
      officeLoading: false,
      officeError: '',
      previewToken: '',
      previewTokenLoading: false,
    });
    this._prevFileId = null;
    uploadUIStore.closePreview();
  };

  renderCodePreview = () => {
    const { textContent, textLanguage, textLoading, textError } = this.state;
    const file = uploadUIStore.previewFile;
    const fileName = file?.display_name || file?.name || '';

    if (textLoading) {
      return (
        <div className={styles.loadingContainer}>
          <Spin tip="加载文件内容..." />
        </div>
      );
    }

    if (textError) {
      return (
        <div className={styles.noPreview}>
          <div className={styles.icon} title="错误"><span role="img" aria-label="错误">⚠️</span></div>
          <div>{textError}</div>
          <div className={styles.hint}>请下载文件后使用对应软件打开</div>
        </div>
      );
    }

    return (
      <div className={styles.codeContainer}>
        <div className={styles.codeHeader}>
          <span className={styles.codeLang}>{textLanguage}</span>
          <span className={styles.codeInfo}>
            {fileName} · {textContent.split('\n').length} 行
          </span>
        </div>
        <AceEditor
          mode={textLanguage}
          theme="tomorrow"
          value={textContent}
          readOnly
          name="code-preview-editor"
          width="100%"
          height="calc(100% - 36px)"
          fontSize={13}
          showPrintMargin={false}
          showGutter={true}
          highlightActiveLine={false}
          setOptions={{
            useWorker: false,
            showLineNumbers: true,
            tabSize: 4,
            wrap: true,
            readOnly: true,
            highlightGutterLine: false,
          }}
          editorProps={{
            $blockScrolling: true,
          }}
        />
      </div>
    );
  };

  renderAudioPreview = () => {
    const { previewToken } = this.state;
    const file = uploadUIStore.previewFile;
    const isPublic = navigationStore.isPublic;
    const fileName = file?.display_name || file?.name || '';

    return (
      <div className={styles.audioContainer}>
        <div className={styles.audioIcon}><AudioIcon size={48} /></div>
        <div className={styles.audioName}>{fileName}</div>
        {previewToken ? (
          <audio
            controls
            src={appendSystemFolderParam(`/api/document/preview/?id=${file.id}&preview_token=${previewToken}&is_public=${isPublic}`)}
            style={{ width: '80%', maxWidth: '500px' }}
          >
            您的浏览器不支持音频播放
          </audio>
        ) : (
          <Spin tip="加载中..." />
        )}
      </div>
    );
  };

  renderOfficePreview = () => {
    const { officeUrl, officeLoading, officeError } = this.state;
    const file = uploadUIStore.previewFile;
    const fileName = file?.display_name || file?.name || '';

    if (officeLoading) {
      return (
        <div className={styles.loadingContainer}>
          <Spin tip="正在加载Office预览..." />
        </div>
      );
    }

    if (officeError) {
      return (
        <div className={styles.noPreview}>
          <div className={styles.icon} title="错误"><span role="img" aria-label="错误">⚠️</span></div>
          <div>{officeError}</div>
          <div className={styles.hint}>
            请下载文件后使用对应软件打开，或联系管理员配置kkFileView服务
          </div>
        </div>
      );
    }

    if (!officeUrl) {
      return (
        <div className={styles.loadingContainer}>
          <Spin tip="正在获取预览地址..." />
        </div>
      );
    }

    return (
      <div className={styles.officeContainer}>
        <iframe
          src={officeUrl}
          style={{
            width: '100%',
            height: '100%',
            border: 'none',
          }}
          title={`Preview: ${fileName}`}
          allow="autoplay"
        />
      </div>
    );
  };

  render() {
    const file = uploadUIStore.previewFile;
    const visible = uploadUIStore.previewVisible;
    const isPublic = navigationStore.isPublic;
    const { previewToken } = this.state;

    // 判断文件类型
    const isImage = file?.file_type?.startsWith('image/');
    const isVideo = file?.file_type?.startsWith('video/');
    const isAudio = file?.file_type?.startsWith('audio/');
    const isCode = isCodeFile(file);
    const isOffice = isOfficeFile(file);
    const fileName = file?.display_name || file?.name || '';
    const isPDF = file?.file_type === 'application/pdf' ||
                  file?.file_type?.startsWith('application/pdf') ||
                  fileName.toLowerCase().endsWith('.pdf');

    // 【H-2修复】需要 preview_token 的 URL 构造
    const previewUrl = previewToken
      ? appendSystemFolderParam(`/api/document/preview/?id=${file.id}&preview_token=${previewToken}&is_public=${isPublic}`)
      : '';

    return (
      <Modal
        title={fileName || '预览'}
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
            {previewUrl ? (
              <img
                src={previewUrl}
                alt={fileName}
                style={{ maxWidth: '100%', maxHeight: '100%', objectFit: 'contain' }}
              />
            ) : (
              <Spin tip="加载中..." />
            )}
          </div>
        ) : isVideo ? (
          visible && (
            <div className={styles.previewContainer}>
              {previewUrl ? (
                <ReactPlayer
                  url={previewUrl}
                  controls
                  width="100%"
                  height="100%"
                />
              ) : (
                <Spin tip="加载中..." />
              )}
            </div>
          )
        ) : isAudio ? (
          this.renderAudioPreview()
        ) : isCode ? (
          this.renderCodePreview()
        ) : isPDF ? (
          <div className={styles.previewContainer} style={{ height: '100%' }}>
            {previewUrl ? (
              <iframe
                src={previewUrl}
                style={{
                  width: '100%',
                  height: '100%',
                  border: 'none'
                }}
                title="PDF Preview"
              />
            ) : (
              <Spin tip="加载中..." />
            )}
          </div>
        ) : isOffice ? (
          this.renderOfficePreview()
        ) : (
          <div className={styles.noPreview}>
            <div className={styles.icon}><FileTypeIcon size={48} /></div>
            <div>该文件类型不支持在线预览</div>
            <div className={styles.hint}>请下载文件后使用对应软件打开</div>
          </div>
        )}
      </Modal>
    );
  }
}

export default observer(PreviewModal);
