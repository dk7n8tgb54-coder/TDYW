/**
 * Copyright (c) OpenSpug Organization. https://github.com/openspug/spug
 * Copyright: (c) <spug.dev@gmail.com>
 * Released under the AGPL-3.0 License.
 *
 * 账号签名管理弹窗（仅超级管理员可见）
 * - 展示目标账号、当前签名、版本、赋予人、赋予时间、状态
 * - 首次赋予 / 替换 / 停用 / 重新启用
 * - 上传先本地预览，管理员确认后提交
 * - 替换前提示"只影响后续使用，不影响历史版本"
 * - 历史版本分页查看
 * - 预览框固定 320x120，object-fit: contain
 */
import React, {useState, useEffect, useRef} from 'react';
import {observer} from 'mobx-react';
import {
  Modal, Upload, Button, Tag, message, Input, Spin, Empty, Pagination,
  Typography, Space, Divider,
} from 'antd';
import {UploadOutlined, PlusOutlined} from '@ant-design/icons';
import {http} from 'libs';
import store from './store';

const {Text} = Typography;

// 签名图片限制（与后端一致）
const MAX_SIZE = 2 * 1024 * 1024;
const MIN_DIM = 100;
const MAX_DIM = 2000;

// 状态文案与颜色
function statusTag(status) {
  if (status === 'active') return <Tag color="success">已配置</Tag>;
  if (status === 'disabled') return <Tag color="default">已停用</Tag>;
  return <Tag>未配置</Tag>;
}

// 当前签名展示区块（只读 + 停用/启用按钮）
function CurrentSignatureSection({detail, configured, isDisabled, currentPreviewUrl, onDisable, onEnable}) {
  if (!configured) {
    return <Empty description="尚未配置签名" image={Empty.PRESENTED_IMAGE_SIMPLE}/>;
  }
  return (
    <div style={{display: 'flex', gap: 24, alignItems: 'flex-start'}}>
      <div style={{
        width: 320, height: 120, border: '1px solid #d9d9d9',
        background: '#fafafa', display: 'flex', alignItems: 'center',
        justifyContent: 'center', flexShrink: 0,
      }}>
        {currentPreviewUrl ? (
          <img src={currentPreviewUrl} alt="当前签名"
               style={{maxWidth: '100%', maxHeight: '100%', objectFit: 'contain'}}/>
        ) : (
          <Text type="secondary">预览加载中</Text>
        )}
      </div>
      <div style={{flex: 1, minWidth: 0}}>
        <div style={{marginBottom: 8}}>{statusTag(detail.status)}</div>
        <div style={{marginBottom: 4}}><Text type="secondary">版本：</Text><Text strong>{detail.version}</Text></div>
        <div style={{marginBottom: 4}}><Text type="secondary">赋予人：</Text><Text>{detail.assigned_by_name}</Text></div>
        <div style={{marginBottom: 4}}><Text type="secondary">赋予时间：</Text><Text>{detail.assigned_at}</Text></div>
        {detail.disabled_at && (
          <div style={{marginBottom: 4}}><Text type="secondary">停用时间：</Text><Text>{detail.disabled_at}</Text></div>
        )}
        <div style={{marginBottom: 4, wordBreak: 'break-all'}}>
          <Text type="secondary">SHA256：</Text>
          <Text code style={{fontSize: 12}}>{(detail.sha256 || '').slice(0, 16)}…</Text>
        </div>
        <Space style={{marginTop: 8}}>
          {isDisabled ? (
            <Button type="primary" size="small" onClick={onEnable}>重新启用</Button>
          ) : (
            <Button size="small" danger onClick={onDisable}>停用</Button>
          )}
        </Space>
      </div>
    </div>
  );
}

// 上传/替换签名区块（本地预览 + 选择图片 + 备注 + 提交）
function UploadReplaceSection({
  previewUrl, pendingFile, pendingSize, remark, setRemark,
  submitting, configured, onBeforeUpload, onResetPending, onSubmit,
}) {
  return (
    <div style={{display: 'flex', gap: 24, alignItems: 'flex-start'}}>
      <div style={{
        width: 320, height: 120, border: '1px dashed #d9d9d9',
        background: '#fafafa', display: 'flex', alignItems: 'center',
        justifyContent: 'center', flexShrink: 0,
      }}>
        {previewUrl ? (
          <img src={previewUrl} alt="待上传预览"
               style={{maxWidth: '100%', maxHeight: '100%', objectFit: 'contain'}}/>
        ) : (
          <Text type="secondary">选择图片后在此预览</Text>
        )}
      </div>
      <div style={{flex: 1, minWidth: 0}}>
        <Upload
          accept=".png,image/png"
          showUploadList={false}
          beforeUpload={onBeforeUpload}
          maxCount={1}
        >
          <Button icon={<PlusOutlined/>}>选择 PNG 图片</Button>
        </Upload>
        <div style={{marginTop: 8, color: '#999', fontSize: 12}}>
          仅支持 PNG，最大 2MB，宽高均需 {MIN_DIM}～{MAX_DIM} 像素。
        </div>
        {pendingFile && (
          <div style={{marginTop: 8}}>
            <Text type="secondary">文件：</Text>
            <Text>{pendingFile.name} ({pendingSize.width}×{pendingSize.height})</Text>
            <Button type="link" size="small" onClick={onResetPending}>清除</Button>
          </div>
        )}
        <div style={{marginTop: 8}}>
          <Text type="secondary">管理备注：</Text>
          <Input.TextArea
            value={remark} onChange={e => setRemark(e.target.value)}
            rows={2} maxLength={200} placeholder="可选，仅超级管理员可见"
            style={{marginTop: 4}}/>
        </div>
        <Button
          type="primary" icon={<UploadOutlined/>}
          style={{marginTop: 12}}
          loading={submitting}
          disabled={!pendingFile}
          onClick={onSubmit}
        >
          {configured ? '提交替换' : '提交赋予'}
        </Button>
        {configured && (
          <div style={{marginTop: 8, color: '#faad14', fontSize: 12}}>
            替换签名只影响后续使用，不影响历史版本。
          </div>
        )}
      </div>
    </div>
  );
}

// 历史版本分页列表
function HistorySection({history, historyLoading, onPageChange}) {
  return (
    <Spin spinning={historyLoading}>
      {history.items.length === 0 ? (
        <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="暂无历史版本"/>
      ) : (
        <div>
          {history.items.map(item => (
            <div key={item.attachment_id} style={{
              display: 'flex', justifyContent: 'space-between', alignItems: 'center',
              padding: '6px 0', borderBottom: '1px solid #f0f0f0',
            }}>
              <div>
                {item.is_current && <Tag color="blue" style={{marginRight: 8}}>当前</Tag>}
                <Text type="secondary">v{item.version || '-'}</Text>
                <Text style={{marginLeft: 12}}>{item.uploaded_by_name}</Text>
                <Text type="secondary" style={{marginLeft: 12, fontSize: 12}}>{item.uploaded_at}</Text>
              </div>
              <Text type="secondary" style={{fontSize: 12}}>
                {(item.sha256 || '').slice(0, 12)}…
              </Text>
            </div>
          ))}
          {history.total > history.page_size && (
            <Pagination
              size="small" style={{marginTop: 12, textAlign: 'right'}}
              current={history.page} pageSize={history.page_size}
              total={history.total}
              showTotal={t => `共 ${t} 条`}
              onChange={onPageChange}
            />
          )}
        </div>
      )}
    </Spin>
  );
}

function useSignatureModal(record) {
  const [loading, setLoading] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [detail, setDetail] = useState(null);
  // 本地预览
  const [previewUrl, setPreviewUrl] = useState('');
  const [pendingFile, setPendingFile] = useState(null);
  const [pendingSize, setPendingSize] = useState({width: 0, height: 0});
  const [remark, setRemark] = useState('');
  // 历史
  const [history, setHistory] = useState({items: [], total: 0, page: 1, page_size: 10});
  const [historyLoading, setHistoryLoading] = useState(false);
  const previewUrlRef = useRef('');

  useEffect(() => {
    fetchDetail();
    fetchHistory(1);
    return () => {
      if (previewUrlRef.current) {
        URL.revokeObjectURL(previewUrlRef.current);
        previewUrlRef.current = '';
      }
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [record.id]);

  function fetchDetail() {
    if (!record.id) return;
    setLoading(true);
    http.get(`/api/account/user/${record.id}/signature/`)
      .then(res => {
        setDetail(res);
        setRemark(res.remark || '');
      })
      .finally(() => setLoading(false));
  }

  function fetchHistory(page) {
    if (!record.id) return;
    setHistoryLoading(true);
    http.get(`/api/account/user/${record.id}/signature/history/`, {
      params: {page, page_size: 10},
    })
      .then(res => setHistory({
        items: res.items || [], total: res.total || 0,
        page: res.page || 1, page_size: res.page_size || 10,
      }))
      .finally(() => setHistoryLoading(false));
  }

  function resetPending() {
    if (previewUrlRef.current) {
      URL.revokeObjectURL(previewUrlRef.current);
      previewUrlRef.current = '';
    }
    setPreviewUrl('');
    setPendingFile(null);
    setPendingSize({width: 0, height: 0});
  }

  function handleBeforeUpload(file) {
    // 前端校验：仅用于体验，后端仍需执行完整校验
    const isPng = file.type === 'image/png' && file.name.toLowerCase().endsWith('.png');
    if (!isPng) {
      message.error('签名图片仅支持 PNG 格式');
      return false;
    }
    if (file.size > MAX_SIZE) {
      message.error('签名图片大小不能超过 2MB');
      return false;
    }
    // 校验尺寸
    const img = new Image();
    const url = URL.createObjectURL(file);
    img.onload = () => {
      if (img.width < MIN_DIM || img.height < MIN_DIM
          || img.width > MAX_DIM || img.height > MAX_DIM) {
        message.error(`图片尺寸需在 ${MIN_DIM}～${MAX_DIM} 像素之间（宽高均需满足）`);
        URL.revokeObjectURL(url);
      } else {
        // 清理旧的预览 URL
        if (previewUrlRef.current) {
          URL.revokeObjectURL(previewUrlRef.current);
        }
        previewUrlRef.current = url;
        setPreviewUrl(url);
        setPendingFile(file);
        setPendingSize({width: img.width, height: img.height});
      }
    };
    img.onerror = () => {
      message.error('图片解码失败，请上传有效的 PNG 图片');
      URL.revokeObjectURL(url);
    };
    img.src = url;
    // 返回 false 阻止 antd Upload 自动上传
    return false;
  }

  function handleSubmit() {
    if (!pendingFile) {
      message.error('请先选择签名图片');
      return;
    }
    const configured = detail && detail.configured;
    // 替换前二次确认
    if (configured) {
      Modal.confirm({
        title: '替换签名确认',
        content: '替换签名只影响后续使用，不影响历史版本。是否继续？',
        okText: '确认替换',
        cancelText: '取消',
        onOk: () => doSubmit('put'),
      });
    } else {
      doSubmit('post');
    }
  }

  function doSubmit(method) {
    setSubmitting(true);
    const formData = new FormData();
    formData.append('file', pendingFile);
    if (remark) formData.append('remark', remark);
    const url = `/api/account/user/${record.id}/signature/`;
    http({
      method, url, data: formData,
      headers: {'Content-Type': 'multipart/form-data'},
      timeout: 60000,
    })
      .then(() => {
        message.success(method === 'put' ? '签名已替换' : '签名已赋予');
        resetPending();
        fetchDetail();
        fetchHistory(1);
        // 刷新账号列表签名状态
        store.fetchRecords();
      })
      .finally(() => setSubmitting(false));
  }

  function handleDisable() {
    Modal.confirm({
      title: '停用签名确认',
      content: '停用后该账号无法使用当前签名进行后续操作，历史记录不受影响。是否继续？',
      okText: '确认停用',
      okButtonProps: {danger: true},
      cancelText: '取消',
      onOk: () => {
        return http.patch(`/api/account/user/${record.id}/signature/status/`, {
          status: 'disabled', reason: remark || '',
        })
          .then(() => {
            message.success('签名已停用');
            fetchDetail();
            store.fetchRecords();
          });
      },
    });
  }

  function handleEnable() {
    http.patch(`/api/account/user/${record.id}/signature/status/`, {status: 'active'})
      .then(() => {
        message.success('签名已启用');
        fetchDetail();
        store.fetchRecords();
      });
  }

  function handleClose() {
    resetPending();
    store.signatureVisible = false;
    store.signatureRecord = {};
  }

  const configured = detail && detail.configured;
  const isDisabled = detail && detail.status === 'disabled';
  // 当前签名预览（后端返回的 preview_url，短期令牌）
  const currentPreviewUrl = detail && detail.preview_url;

  return {
    loading, submitting, detail, previewUrl, pendingFile, pendingSize,
    remark, setRemark, history, historyLoading,
    configured, isDisabled, currentPreviewUrl,
    handleBeforeUpload, handleSubmit, resetPending,
    handleDisable, handleEnable, handleClose, fetchHistory,
  };
}

function SignatureModal() {
  const record = store.signatureRecord;
  const {
    loading, submitting, detail, previewUrl, pendingFile, pendingSize,
    remark, setRemark, history, historyLoading,
    configured, isDisabled, currentPreviewUrl,
    handleBeforeUpload, handleSubmit, resetPending,
    handleDisable, handleEnable, handleClose, fetchHistory,
  } = useSignatureModal(record);

  return (
    <Modal
      visible
      width={720}
      maskClosable={false}
      destroyOnClose
      title={`管理签名 - ${record.nickname || ''} (${record.username || ''})`}
      onCancel={handleClose}
      footer={[
        <Button key="close" onClick={handleClose}>关闭</Button>,
      ]}
    >
      <Spin spinning={loading}>
        {/* 账号信息（只读） */}
        <Space size="large" style={{marginBottom: 16}}>
          <Text>登录名：<Text strong>{record.username}</Text></Text>
          <Text>姓名：<Text strong>{record.nickname}</Text></Text>
          <Text>租户：<Text strong>{record.tenant_id}</Text></Text>
        </Space>

        {/* 当前签名 */}
        <Divider orientation="left" style={{margin: '8px 0'}}>当前签名</Divider>
        <CurrentSignatureSection
          detail={detail}
          configured={configured}
          isDisabled={isDisabled}
          currentPreviewUrl={currentPreviewUrl}
          onDisable={handleDisable}
          onEnable={handleEnable}
        />

        {/* 上传/替换 */}
        <Divider orientation="left" style={{margin: '16px 0 8px'}}>
          {configured ? '替换签名' : '赋予签名'}
        </Divider>
        <UploadReplaceSection
          previewUrl={previewUrl}
          pendingFile={pendingFile}
          pendingSize={pendingSize}
          remark={remark}
          setRemark={setRemark}
          submitting={submitting}
          configured={configured}
          onBeforeUpload={handleBeforeUpload}
          onResetPending={resetPending}
          onSubmit={handleSubmit}
        />

        {/* 历史版本 */}
        <Divider orientation="left" style={{margin: '16px 0 8px'}}>历史版本</Divider>
        <HistorySection
          history={history}
          historyLoading={historyLoading}
          onPageChange={p => fetchHistory(p)}
        />
      </Spin>
    </Modal>
  );
}

export default observer(SignatureModal);
