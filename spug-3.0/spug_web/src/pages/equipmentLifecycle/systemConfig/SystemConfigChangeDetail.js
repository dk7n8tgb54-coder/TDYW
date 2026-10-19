/**
 * Copyright (c) OpenSpug Organization. https://github.com/openspug/spug
 * Copyright (c) <spug.dev@gmail.com>
 * Released under the AGPL-3.0 License.
 */
/**
 * 系统详情 → 配置页签 —— 配置变更详情（Drawer，非独立页面）。
 * 展示变更公共信息、逐参数前后值快照、验证结果、附件、审计信息与回退关联；
 * 动作按钮按状态与权限显示：应用 / 验证 / 回退 / 取消。
 * 2026-10-19 起支持 readOnly：系统档案只读页签传入 readOnly 隐藏全部写操作
 * （应用/验证/回退/取消/附件上传删除），处理变更统一到维护入口完成。
 */
import React, {Fragment} from 'react';
import {observer} from 'mobx-react';
import {Drawer, Spin, Descriptions, Table, Tag, Button, Modal, Radio, Input, Upload, Divider, message} from 'antd';
import {PaperClipOutlined, UploadOutlined} from '@ant-design/icons';
import {AuthButton} from 'components';
import store from './store';
import {PERM, CONFIG_VERIFY_STATUS_TEXT, CONFIG_VERIFY_STATUS_COLOR} from '../constants';

const {TextArea} = Input;

@observer
class SystemConfigChangeDetail extends React.Component {
  state = {
    attachments: [],
    verifyVisible: false,
    verifyStatus: 'passed',
    verifyNote: '',
    uploading: false,
  };

  componentDidMount() {
    store.showDetail(this.props.changeId);
    this.fetchAttachments();
  }

  fetchAttachments = () => {
    store.fetchAttachments(this.props.changeId)
      .then(atts => this.setState({attachments: atts || []}))
      .catch(() => {});
  };

  handleUpload = (file) => {
    this.setState({uploading: true});
    store.uploadAttachment(this.props.changeId, file)
      .then(() => {
        this.fetchAttachments();
      })
      .catch(() => {})
      .finally(() => this.setState({uploading: false}));
    return false;
  };

  handleDeleteAttachment = (attachmentId) => {
    store.deleteAttachment(this.props.changeId, attachmentId)
      .then(() => {
        this.fetchAttachments();
      })
      .catch(() => {});
  };

  handleApply = () => {
    Modal.confirm({
      title: '应用配置变更',
      content: '应用后配置值立即生效，且已生效的变更不能被普通编辑覆盖。确认应用？',
      onOk: () => store.applyChange(store.detail.id, this.props.systemId)
        .then(() => message.success('配置变更已应用生效'))
        .catch(() => {}),
    });
  };

  handleVerify = () => {
    this.setState({verifyVisible: true, verifyStatus: 'passed', verifyNote: ''});
  };

  submitVerify = () => {
    store.verifyChange(store.detail.id, this.props.systemId, this.state.verifyStatus, this.state.verifyNote)
      .then(() => {
        message.success('验证结果已保存');
        this.setState({verifyVisible: false});
      })
      .catch(() => {});
  };

  handleRollback = () => {
    Modal.confirm({
      title: '回退配置变更',
      content: '回退会生成一条新的反向配置变更（原记录保留），把参数值恢复为本次变更前的值。确认回退？',
      onOk: () => store.rollbackChange(store.detail.id, this.props.systemId)
        .then(res => {
          message.success(`已回退并生成反向变更 ${res.change_no}`);
          if (res.id) {
            store.showDetail(res.id);
            this.fetchAttachments();
          }
        })
        .catch(() => {}),
    });
  };

  handleCancel = () => {
    Modal.confirm({
      title: '取消草稿变更',
      content: '取消后本变更不再应用。确认取消？',
      onOk: () => store.cancelChange(store.detail.id, this.props.systemId)
        .then(() => message.success('配置变更已取消'))
        .catch(() => {}),
    });
  };

  get isDraft() {
    return store.detail.status === 'draft';
  }

  renderActions() {
    const d = store.detail;
    if (!d.id) return null;
    return (
      <div style={{marginTop: 16}}>
        {this.isDraft && (
          <Fragment>
            <AuthButton auth={PERM.CONFIG_APPLY} type="primary" loading={store.isActionSubmitting}
              onClick={this.handleApply} style={{marginRight: 8}}>应用变更</AuthButton>
            <AuthButton auth={PERM.CONFIG_EDIT} loading={store.isActionSubmitting}
              onClick={this.handleCancel}>取消变更</AuthButton>
          </Fragment>
        )}
        {d.status === 'applied' && (
          <Fragment>
            <AuthButton auth={PERM.CONFIG_VERIFY} type="primary" loading={store.isActionSubmitting}
              onClick={this.handleVerify} style={{marginRight: 8}}>验证</AuthButton>
            <AuthButton auth={PERM.CONFIG_ROLLBACK} loading={store.isActionSubmitting}
              onClick={this.handleRollback}>回退</AuthButton>
          </Fragment>
        )}
        {d.status === 'verified' && (
          <AuthButton auth={PERM.CONFIG_ROLLBACK} loading={store.isActionSubmitting}
            onClick={this.handleRollback}>回退</AuthButton>
        )}
      </div>
    );
  }

  renderItemColumns() {
    return [
      {title: '参数名称', dataIndex: 'param_name', width: 150},
      {title: '参数编码', dataIndex: 'param_code', width: 130},
      {title: '类型', dataIndex: 'data_type_text', width: 70},
      {title: '变更前值', dataIndex: 'old_value', width: 110,
        render: text => text === '' ? <Tag>未设置</Tag> : text},
      {title: '变更后值', dataIndex: 'new_value', width: 110},
      {title: '单位', dataIndex: 'unit', width: 70, render: text => text || '-'},
      {title: '单项验证', dataIndex: 'verify_status_text', width: 90,
        render: (text, record) => text
          ? <Tag color={CONFIG_VERIFY_STATUS_COLOR[record.verify_status]}>{text}</Tag>
          : '-'},
      {title: '备注', dataIndex: 'remark', render: text => text || '-'},
    ];
  }

  renderBasicInfo(d) {
    return (
      <Descriptions bordered size="small" column={2}>
        <Descriptions.Item label="变更编号">{d.change_no}</Descriptions.Item>
        <Descriptions.Item label="状态">{d.status_text}</Descriptions.Item>
        <Descriptions.Item label="所属系统" span={2}>{d.system_name}</Descriptions.Item>
        <Descriptions.Item label="变更原因" span={2}>{d.reason}</Descriptions.Item>
        <Descriptions.Item label="操作人">{d.created_by_name}</Descriptions.Item>
        <Descriptions.Item label="登记时间">{d.created_at}</Descriptions.Item>
        <Descriptions.Item label="生效时间">{d.applied_at || '-'}</Descriptions.Item>
        <Descriptions.Item label="生效操作人">{d.applied_by_name || '-'}</Descriptions.Item>
        <Descriptions.Item label="验证状态">
          <Tag color={CONFIG_VERIFY_STATUS_COLOR[d.verify_status || '']}>
            {CONFIG_VERIFY_STATUS_TEXT[d.verify_status || ''] || '未验证'}
          </Tag>
        </Descriptions.Item>
        <Descriptions.Item label="验证时间">{d.verified_at || '-'}</Descriptions.Item>
        <Descriptions.Item label="验证说明" span={2}>{d.verify_note || '-'}</Descriptions.Item>
        {d.rollback_of_no && (
          <Descriptions.Item label="回退自" span={2}>{d.rollback_of_no}</Descriptions.Item>
        )}
        {(d.rollback_changes || []).length > 0 && (
          <Descriptions.Item label="回退记录" span={2}>
            {d.rollback_changes.map(item => item.change_no).join('、')}
          </Descriptions.Item>
        )}
        {d.status === 'cancelled' && (
          <Fragment>
            <Descriptions.Item label="取消时间">{d.cancelled_at || '-'}</Descriptions.Item>
            <Descriptions.Item label="取消操作人">{d.cancelled_by_name || '-'}</Descriptions.Item>
          </Fragment>
        )}
      </Descriptions>
    );
  }

  renderAttachments() {
    return (
      <Fragment>
        <Divider orientation="left" plain style={{fontSize: 13}}>附件</Divider>
        <div>
          {(this.state.attachments || []).map(att => (
          <div key={att.id} style={{marginBottom: 4}}>
            <PaperClipOutlined style={{marginRight: 4}}/>
            {att.file_name}
            {this.isDraft && !this.props.readOnly && (
              <a style={{marginLeft: 8, color: '#f5222d'}}
                onClick={() => this.handleDeleteAttachment(att.id)}>删除</a>
            )}
          </div>
        ))}
        {this.isDraft && !this.props.readOnly && (
          <Upload
              multiple
              beforeUpload={this.handleUpload}
              showUploadList={false}
              disabled={this.state.uploading}
            >
              <Button size="small" loading={this.state.uploading}>
                <UploadOutlined/> 上传附件
              </Button>
            </Upload>
          )}
        </div>
      </Fragment>
    );
  }

  renderVerifyModal() {
    return (
      <Modal
        title="验证配置变更"
        visible={this.state.verifyVisible}
        confirmLoading={store.isActionSubmitting}
        onCancel={() => this.setState({verifyVisible: false})}
        onOk={this.submitVerify}
      >
        <div style={{marginBottom: 8}}>验证结论</div>
        <Radio.Group
          value={this.state.verifyStatus}
          onChange={e => this.setState({verifyStatus: e.target.value})}
        >
          <Radio value="passed">验证通过</Radio>
          <Radio value="failed">验证不通过</Radio>
        </Radio.Group>
        <div style={{margin: '12px 0 8px'}}>验证说明</div>
        <TextArea
          rows={2}
          maxLength={500}
          value={this.state.verifyNote}
          onChange={e => this.setState({verifyNote: e.target.value})}
          placeholder="选填，记录验证方式与结果说明"
        />
      </Modal>
    );
  }

  render() {
    const d = store.detail;
    return (
      <Drawer
        title={`配置变更 ${d.change_no || ''}`}
        visible={store.detailVisible}
        width={760}
        onClose={() => {
          store.hideDetail();
          if (this.props.onClose) this.props.onClose();
        }}
        destroyOnClose
      >
        <Spin spinning={store.isDetailFetching}>
          {this.renderBasicInfo(d)}
          <Divider orientation="left" plain style={{fontSize: 13}}>参数明细（变更前后值快照）</Divider>
          <Table
            rowKey="id"
            size="small"
            pagination={false}
            dataSource={d.items || []}
            columns={this.renderItemColumns()}
          />
          {this.renderAttachments()}
          {!this.props.readOnly && this.renderActions()}
        </Spin>
        {this.renderVerifyModal()}
      </Drawer>
    );
  }
}

export default SystemConfigChangeDetail;
