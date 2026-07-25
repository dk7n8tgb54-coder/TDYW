/**
 * Copyright (c) OpenSpug Organization. https://github.com/openspug/spug
 * Copyright: (c) <spug.dev@gmail.com>
 * Released under the AGPL-3.0 License.
 */
import React from 'react';
import {observer} from 'mobx-react';
import {Drawer, Descriptions, Tag, Alert, Spin, Empty} from 'antd';
import {http} from 'libs';
import store from './departmentDutyLogStore';

@observer
class DepartmentDutyLogDetail extends React.Component {
  state = {
    sigImageUrl: '',
    sigLoading: false,
    sigError: '',
  };
  _mounted = false;

  componentDidUpdate(prevProps) {
    // 当记录切换时重新加载签名图片
    if (store.record && store.record.id !== this._lastRecordId) {
      this._lastRecordId = store.record.id;
      this.loadSignatureImage();
    }
  }

  componentDidMount() {
    this._mounted = true;
    if (store.record && store.record.id) {
      this._lastRecordId = store.record.id;
      this.loadSignatureImage();
    }
  }

  componentWillUnmount() {
    this._mounted = false;
    this.revokeUrl();
  }

  revokeUrl() {
    if (this.state.sigImageUrl) {
      URL.revokeObjectURL(this.state.sigImageUrl);
    }
  }

  loadSignatureImage = () => {
    const record = store.record;
    if (!record || !record.signature_usage_id) {
      this.setState({sigImageUrl: '', sigLoading: false, sigError: ''});
      return;
    }
    if (record.status !== 'signed' && record.status !== 'void') {
      this.setState({sigImageUrl: '', sigLoading: false, sigError: ''});
      return;
    }

    this.revokeUrl();
    this.setState({sigLoading: true, sigError: '', sigImageUrl: ''});

    http.get(`/api/department-duty-log/records/${record.id}/signature-image/`, {
      responseType: 'blob',
    }).then(response => {
      if (!this._mounted) return;
      const blob = new Blob([response.data], {type: 'image/png'});
      const url = URL.createObjectURL(blob);
      this.setState({sigImageUrl: url, sigLoading: false});
    }).catch(err => {
      if (!this._mounted) return;
      this.setState({sigLoading: false, sigError: '签名文件异常'});
    });
  };

  renderStatus = (status) => {
    const tagInfo = store.statusTagMap[status] || store.statusTagMap.draft;
    return <Tag color={tagInfo.color}>{tagInfo.text}</Tag>;
  };

  render() {
    const record = store.record;
    if (!record) return null;

    return (
      <Drawer
        title="值班日志详情"
        visible={store.detailVisible}
        onClose={() => {
          this.revokeUrl();
          store.detailVisible = false;
        }}
        width={640}
        destroyOnClose
      >
        <Spin spinning={store.detailLoading}>
        {record.status === 'void' && record.void_reason && (
          <Alert
            type="error"
            message={`已作废：${record.void_reason}`}
            description={`作废时间：${record.voided_at || '--'}`}
            showIcon
            style={{marginBottom: 16}}
          />
        )}

        <Descriptions column={2} bordered size="small">
          <Descriptions.Item label="日期">{record.duty_date}</Descriptions.Item>
          <Descriptions.Item label="状态">{this.renderStatus(record.status)}</Descriptions.Item>
          <Descriptions.Item label="值班员">{record.duty_person_name}</Descriptions.Item>
          <Descriptions.Item label="市电电压">{record.mains_voltage || '--'}</Descriptions.Item>
          <Descriptions.Item label="UPS电压">{record.ups_voltage || '--'}</Descriptions.Item>
          <Descriptions.Item label="天气情况">{record.weather || '--'}</Descriptions.Item>
          <Descriptions.Item label="值班记录" span={2}>
            <div style={{whiteSpace: 'pre-wrap', maxHeight: 300, overflow: 'auto'}}>
              {record.duty_record || '--'}
            </div>
          </Descriptions.Item>
          <Descriptions.Item label="备注" span={2}>
            <div style={{whiteSpace: 'pre-wrap'}}>
              {record.remark || '--'}
            </div>
          </Descriptions.Item>
        </Descriptions>

        {(record.status === 'signed' || record.status === 'void') && (
          <>
            <div style={{marginTop: 24, marginBottom: 8, fontWeight: 500, fontSize: 15}}>签署信息</div>
            <Descriptions column={2} bordered size="small">
              <Descriptions.Item label="签署人">{record.signed_by_name || '--'}</Descriptions.Item>
              <Descriptions.Item label="签名版本">{record.signature_version || '--'}</Descriptions.Item>
              <Descriptions.Item label="业务快照哈希" span={2}>
                <span style={{wordBreak: 'break-all', fontSize: 12}}>
                  {record.business_snapshot_hash || '--'}
                </span>
              </Descriptions.Item>
            </Descriptions>

            <div style={{marginTop: 16, marginBottom: 8, fontWeight: 500, fontSize: 15}}>签名图片</div>
            {this.state.sigLoading ? (
              <div style={{textAlign: 'center', padding: 40}}><Spin tip="加载中..."/></div>
            ) : this.state.sigError ? (
              <Alert type="error" message={this.state.sigError} showIcon/>
            ) : this.state.sigImageUrl ? (
              <div style={{textAlign: 'center', padding: 16, border: '1px solid #f0f0f0', borderRadius: 4}}>
                <img src={this.state.sigImageUrl} alt="签名"
                  style={{maxWidth: '100%', maxHeight: 200, objectFit: 'contain'}}/>
              </div>
            ) : (
              <Empty description="无签名图片"/>
            )}
          </>
        )}
        </Spin>
      </Drawer>
    );
  }
}

export default DepartmentDutyLogDetail;
