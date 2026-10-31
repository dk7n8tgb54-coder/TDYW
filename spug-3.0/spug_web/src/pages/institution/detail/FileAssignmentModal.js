/**
 * Copyright (c) OpenSpug Organization. https://github.com/openspug/spug
 * Released under the AGPL-3.0 License.
 *
 * 文件分工弹窗（指定/改派/清空文件负责人 + 分工说明）：
 * - 分工单位是整份制度文件，每份文件至多一名负责人（后端字段就在文件
 *   条目上，结构上不存在互相冲突的多条"当前分工"）。
 * - owner_id 必须显式提交：null=清空为「未分配」。
 * - 批量模式（传入 files 数组）：统一应用到所选文件，明确展示已选
 *   数量与作用范围；不预填现有负责人（多份文件现状可能不同）。
 * - 负责人候选走制度模块专用接口 /assignment-owners/（仅 id+name 最小
 *   字段，权限与分工写路径一致）；不得再拉账号管理列表
 *   /api/account/user/（要求 system.account.view，无账号查看权的分工
 *   用户会被拒，候选静默降级为空列表是缺陷，2026-10-30 修正）。
 * - 候选加载失败在弹窗内展示明确错误与重试入口（请求带
 *   skipErrorNotification，HTTP 拦截器不再弹同一条错误），绝不把失败
 *   静默表现为空候选列表。
 * - 指定负责人不授予任何权限本身，但负责人独占编辑（2026-10-31 授权
 *   模型）：负责人须持有本手册编制资格（授权 can_edit），候选已按此
 *   过滤（assignment-owners 候选=持本手册编制授权的启用账号），后端
 *   在写路径独立校验；本弹窗只提交数据，不做权限判断的替代品。
 */
import React from 'react';
import { Modal, Select, Input, Form, Alert, Button } from 'antd';
import { http } from 'libs';

const {Option} = Select;

export default class FileAssignmentModal extends React.Component {
  formRef = React.createRef();

  state = {owners: [], ownersError: '', fetchingOwners: false, submitting: false};

  _mounted = false;

  componentDidMount() {
    this._mounted = true;
    this.fetchOwners();
  }

  componentWillUnmount() {
    this._mounted = false;
  }

  fetchOwners() {
    this.setState({fetchingOwners: true, ownersError: ''});
    http.get(
      `/api/institution/manuals/${this.props.manualId}/assignment-owners/`,
      {skipErrorNotification: true})
      .then(data => {
        if (!this._mounted) return;
        const items = Array.isArray(data) ? data : [];
        this.setState({owners: items, ownersError: ''});
      })
      .catch(err => {
        if (!this._mounted) return;
        // 拦截器被抑制，错误在此处展示一次（err 通常为拦截器给的文案）
        this.setState({ownersError: typeof err === 'string' && err ? err : '负责人候选加载失败'});
      })
      .finally(() => {
        if (this._mounted) this.setState({fetchingOwners: false});
      });
  }

  handleOk = () => {
    this.formRef.current.validateFields().then(values => {
      this.setState({submitting: true});
      // ownerId undefined（未选择）与显式清空统一按 null 提交
      this.props.onSubmit(values.owner_id || null, (values.note || '').trim())
        .then(() => this.props.onClose())
        .catch(() => {})
        .finally(() => this.setState({submitting: false}));
    }).catch(() => {});
  };

  render() {
    const file = this.props.file || {};
    const files = this.props.files || null;
    const isBatch = Array.isArray(files);
    const assignment = file.assignment || {};
    const title = isBatch
      ? `批量文件分工（${files.length} 份文件）`
      : `文件分工：${file.name || ''}`;
    return (
      <Modal visible confirmLoading={this.state.submitting}
        title={title}
        onCancel={this.props.onClose} onOk={this.handleOk}>
        {isBatch && (
          <Alert style={{marginBottom: 12}} type="info" showIcon
            message={`本次操作将统一应用到已选的 ${files.length} 份文件：${files.map(f => f.name).join('、')}`}
            description="批量操作整体生效：任一文件校验失败则整批不生效。负责人未变（仅修改说明）的文件保留其提交编制记录。"/>
        )}
        {this.state.ownersError && (
          <Alert style={{marginBottom: 12}} type="error" showIcon
            message={`负责人候选加载失败：${this.state.ownersError}`}
            description="未加载到候选不代表没有可用负责人，请重试；也可清空负责人保持未分配。"
            action={<Button size="small" type="primary"
              loading={this.state.fetchingOwners}
              onClick={() => this.fetchOwners()}>重试</Button>}/>
        )}
        <Form ref={this.formRef} labelCol={{span: 5}} wrapperCol={{span: 17}}
          initialValues={{
            owner_id: isBatch ? undefined : (assignment.owner_id || undefined),
            note: isBatch ? '' : (assignment.note || ''),
          }}>
          <Form.Item name="owner_id" label="负责人"
            extra={isBatch
              ? '统一设置所选文件的负责人；清空即全部未分配。负责人须持有本手册编制资格（候选已按此过滤，后端独立校验），此后由负责人独占编辑'
              : '负责人完成编制后可在文件清单提交编制；负责人须持有本手册编制资格（候选已按此过滤，后端独立校验），此后由负责人独占编辑'}>
            <Select allowClear showSearch optionFilterProp="children"
              loading={this.state.fetchingOwners}
              placeholder={isBatch ? '选择负责人账号（清空即全部未分配）'
                : '选择负责人账号（清空即未分配）'}>
              {this.state.owners.map(u => (
                <Option key={u.id} value={u.id}>{u.name}</Option>
              ))}
            </Select>
          </Form.Item>
          <Form.Item name="note" label="分工说明">
            <Input.TextArea rows={2} maxLength={500}
              placeholder="职责范围、协作方式等补充说明（可选）"/>
          </Form.Item>
        </Form>
      </Modal>
    );
  }
}
