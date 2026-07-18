/**
 * Copyright (c) OpenSpug Organization. https://github.com/openspug/spug
 * Copyright: (c) <spug.dev@gmail.com>
 * Released under the AGPL-3.0 License.
 */
import React from 'react';
import {observer} from 'mobx-react';
import {Modal, Descriptions, Alert, Spin, Empty, message, Typography} from 'antd';
import {http} from 'libs';
import store from './departmentDutyLogStore';

const {Text} = Typography;

function generateUUID() {
  return 'xxxxxxxxxxxx4xxxyxxxxxxxxxxxxxxx'.replace(/[xy]/g, function(c) {
    const r = Math.random() * 16 | 0;
    const v = c === 'x' ? r : (r & 0x3 | 0x8);
    return v.toString(16);
  });
}

@observer
class DepartmentDutyLogSignModal extends React.Component {
  state = {
    signatureInfo: null,
    sigLoading: false,
    sigImageUrl: '',
    sigImageError: false,
    submitting: false,
    requestId: '',
  };
  _mounted = false;

  componentDidMount() {
    this._mounted = true;
    // 生成唯一 request_id，同一次签署重试复用
    this.setState({requestId: generateUUID()});
    this.fetchMySignature();
  }

  componentWillUnmount() {
    this._mounted = false;
    if (this.state.sigImageUrl) {
      URL.revokeObjectURL(this.state.sigImageUrl);
    }
  }

  fetchMySignature = () => {
    this.setState({sigLoading: true});
    http.get('/api/signature/mine/')
      .then(data => {
        if (!this._mounted) return;
        this.setState({signatureInfo: data});
        if (data.available && data.preview_url) {
          this.loadSignaturePreview(data.preview_url);
        } else {
          this.setState({sigLoading: false});
        }
      })
      .catch(() => {
        if (!this._mounted) return;
        this.setState({sigLoading: false, signatureInfo: {available: false}});
      });
  };

  loadSignaturePreview = (previewUrl) => {
    // 通过带认证头的请求加载签名预览图片
    http.get(previewUrl, {
      responseType: 'blob',
    }).then(response => {
      if (!this._mounted) return;
      const blob = new Blob([response.data], {type: 'image/png'});
      const url = URL.createObjectURL(blob);
      this.setState({sigImageUrl: url, sigLoading: false, sigImageError: false});
    }).catch(() => {
      if (!this._mounted) return;
      this.setState({sigLoading: false, sigImageError: true});
    });
  };

  handleSign = () => {
    const record = store.record;
    const {requestId, signatureInfo} = this.state;

    if (!signatureInfo || !signatureInfo.available) {
      message.error('当前账号未配置有效签名，请联系超级管理员');
      return;
    }
    if (this.state.sigImageError || !this.state.sigImageUrl) {
      message.error('签名图片加载失败，无法签署');
      return;
    }

    this.setState({submitting: true});
    http.post(`/api/department-duty-log/records/${record.id}/sign/`, {
      version: record.version,
      confirm: true,
      request_id: requestId,
    }).then(() => {
      if (!this._mounted) return;
      message.success('签署成功');
      store.signVisible = false;
      store.fetchRecords();
    }).catch(() => {}).finally(() => {
      if (this._mounted) this.setState({submitting: false});
    });
  };

  render() {
    const record = store.record;
    if (!record) return null;

    const {signatureInfo, sigLoading, sigImageUrl, sigImageError, submitting} = this.state;
    const canSign = signatureInfo && signatureInfo.available && sigImageUrl && !sigImageError;

    return (
      <Modal
        title="签署确认"
        visible={store.signVisible}
        onCancel={() => store.signVisible = false}
        onOk={this.handleSign}
        confirmLoading={submitting}
        okText="签署并提交"
        okButtonProps={{disabled: !canSign}}
        width={560}
        destroyOnClose
        maskClosable={false}
      >
        {sigLoading ? (
          <div style={{textAlign: 'center', padding: 40}}><Spin tip="加载签名信息..."/></div>
        ) : (
          <>
            {(!signatureInfo || !signatureInfo.available) && (
              <Alert
                type="warning"
                message="当前账号未配置有效签名"
                description="请联系超级管理员配置签名后再进行签署。"
                showIcon
                style={{marginBottom: 16}}
              />
            )}

            {sigImageError && (
              <Alert
                type="error"
                message="签名图片加载失败"
                description="请刷新重试或联系超级管理员。"
                showIcon
                style={{marginBottom: 16}}
              />
            )}

            <Descriptions column={1} size="small" bordered style={{marginBottom: 16}}>
              <Descriptions.Item label="签署人">
                {signatureInfo ? (store.currentUser ? store.currentUser.name : '--') : '--'}
              </Descriptions.Item>
              <Descriptions.Item label="值班日期">{record.duty_date}</Descriptions.Item>
              <Descriptions.Item label="市电电压">{record.mains_voltage || '--'}</Descriptions.Item>
              <Descriptions.Item label="UPS电压">{record.ups_voltage || '--'}</Descriptions.Item>
              <Descriptions.Item label="天气情况">{record.weather || '--'}</Descriptions.Item>
              <Descriptions.Item label="值班记录摘要">
                <div style={{
                  whiteSpace: 'pre-wrap',
                  maxHeight: 100,
                  overflow: 'auto',
                  fontSize: 13,
                }}>
                  {record.duty_record_summary || '--'}
                </div>
              </Descriptions.Item>
            </Descriptions>

            {signatureInfo && signatureInfo.available && (
              <>
                <div style={{marginBottom: 8, fontWeight: 500}}>当前签名预览：</div>
                {sigImageUrl ? (
                  <div style={{
                    textAlign: 'center',
                    padding: 16,
                    border: '1px solid #f0f0f0',
                    borderRadius: 4,
                  }}>
                    <img src={sigImageUrl} alt="签名预览"
                      style={{maxWidth: '100%', maxHeight: 120, objectFit: 'contain'}}/>
                  </div>
                ) : sigImageError ? (
                  <Empty description="签名图片加载失败"/>
                ) : (
                  <Empty description="签名图片加载中..."/>
                )}
                {signatureInfo.version && (
                  <Text type="secondary" style={{fontSize: 12, display: 'block', marginTop: 4}}>
                    签名版本：v{signatureInfo.version}
                  </Text>
                )}
              </>
            )}

            <Alert
              type="info"
              message="签署后记录将锁定，不可再编辑或删除。如需更正，请通过作废后新建更正记录。"
              showIcon
              style={{marginTop: 16}}
            />
          </>
        )}
      </Modal>
    );
  }
}

export default DepartmentDutyLogSignModal;
