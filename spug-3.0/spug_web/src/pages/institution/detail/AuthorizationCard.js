/**
 * Copyright (c) OpenSpug Organization. https://github.com/openspug/spug
 * Released under the AGPL-3.0 License.
 *
 * 账号授权卡片（2026-10-31 授权模型改造，替代旧「角色关联」配置）：
 * 逐本账号授权 = 每账号一行（查看/编制/发布三个布尔授权位），
 * 「保存授权」整体替换（PUT authorizations/，items 全量）。
 * 仅手册所有者/平台超级管理员可读写（后端独立校验；编制/发布授权不足
 * 以读写授权配置）。
 * - 挂载即拉取授权清单与账号候选；清单失败置错误态可重试，候选失败在
 *   卡片内展示错误与重试（skipErrorNotification，FileAssignmentModal
 *   同款模式），绝不把失败静默表现为空候选列表。
 * - 保存成功提示只在实际成功响应之后；revoked_sessions>0 时追加说明
 *   被撤销的进行中编辑会话数（失权撤销，未落盘内容已显式丢弃）。
 * - 全 False 的账号行无意义：保存前过滤（后端不落行）；重复账号不允许
 *   添加（后端校验去重，前端添加入口已按候选过滤）。
 */
import React from 'react';
import { observer } from 'mobx-react';
import { Card, Table, Tag, Button, Select, Alert, Checkbox, message } from 'antd';
import { DeleteOutlined } from '@ant-design/icons';
import store from './store';

const {Option} = Select;

// 三个授权位的展示配置（查看/编制/发布；与后端 can_view/can_edit/can_publish 对应）
const AUTH_BITS = [
  {key: 'can_view', label: '查看', tip: '可见手册与已发布版本（发布域）'},
  {key: 'can_edit', label: '编制', tip: '可进入草稿工作区；被指派为文件负责人后可编辑（负责人独占）'},
  {key: 'can_publish', label: '发布', tip: '可发布新版本与废止（发布域操作）'},
];

function rowsFromServer(items) {
  return (items || []).map(x => ({
    account_id: x.account_id,
    account_name: x.account_name,
    can_view: !!x.can_view,
    can_edit: !!x.can_edit,
    can_publish: !!x.can_publish,
  }));
}

@observer
class AuthorizationCard extends React.Component {
  state = {
    rows: null,
    addAccountId: undefined,
    saving: false,
  };

  componentDidMount() {
    this.fetchAll();
  }

  /** 拉取授权清单与账号候选；清单成功后把服务端行同步进本地编辑副本 */
  fetchAll = () => {
    const id = store.id;
    store.fetchAuthorizations(id).then(() => {
      const auth = store.authorizations;
      if (auth) {
        this.setState({
          rows: rowsFromServer(auth.items),
          addAccountId: undefined,
        });
      }
    });
    store.fetchAccountOptions(id);
  };

  handleToggleBit = (index, bitKey) => (e) => {
    const rows = this.state.rows.slice();
    rows[index] = {...rows[index], [bitKey]: e.target.checked};
    this.setState({rows});
  };

  handleRemoveRow = (index) => {
    const rows = this.state.rows.slice();
    rows.splice(index, 1);
    this.setState({rows});
  };

  handleAddRow = () => {
    const accountId = this.state.addAccountId;
    if (!accountId) {
      message.warning('请先选择要添加的账号');
      return;
    }
    const rows = this.state.rows || [];
    if (rows.some(r => r.account_id === accountId)) {
      message.warning('该账号已在授权清单中');
      return;
    }
    const option = (store.accountOptions || []).find(o => o.id === accountId);
    this.setState({
      rows: rows.concat({
        account_id: accountId,
        account_name: option ? option.name : `账号 ${accountId}`,
        can_view: true, can_edit: false, can_publish: false,
      }),
      addAccountId: undefined,
    });
  };

  handleSave = () => {
    const rows = this.state.rows || [];
    // 全 False 的行无意义（后端不落授权行），保存前过滤
    const items = rows
      .filter(r => r.can_view || r.can_edit || r.can_publish)
      .map(r => ({
        account_id: r.account_id,
        can_view: !!r.can_view,
        can_edit: !!r.can_edit,
        can_publish: !!r.can_publish,
      }));
    this.setState({saving: true});
    store.saveAuthorizations(store.id, items)
      .then(data => {
        const revoked = data && data.revoked_sessions;
        message.success(revoked > 0
          ? `授权已保存；已撤销 ${revoked} 个进行中的编辑会话`
          : '授权已保存');
        this.setState({
          rows: rowsFromServer(data && data.items),
        });
      })
      .catch(() => {
        // 失败：HTTP 拦截器已提示一次，这里不重复弹错；保留本地编辑副本
      })
      .finally(() => this.setState({saving: false}));
  };

  render() {
    const {rows, addAccountId, saving} = this.state;
    const options = store.accountOptions || [];
    const existingIds = (rows || []).map(r => r.account_id);
    return (
      <Card title="账号授权（查看 / 编制 / 发布）" size="small" style={{marginBottom: 16}}>
        <p style={{marginTop: 0, color: '#666', fontSize: 12}}>
          授权按账号逐本授予（整体保存）：查看=可见手册与发布版；编制=可进入
          草稿工作区（编辑内容还须被指派为对应文件的负责人，单写会话）；
          发布=可发布与废止。取消「编制」授权会撤销该账号的进行中编辑会话。
        </p>
        {store.authorizationsError && (
          <Alert type="error" showIcon style={{marginBottom: 8}}
            message={store.authorizationsError}
            action={<Button size="small" type="primary"
              onClick={this.fetchAll}>重试</Button>}/>
        )}
        {store.accountOptionsError && (
          <Alert type="warning" showIcon style={{marginBottom: 8}}
            message={`账号候选加载失败：${store.accountOptionsError}`}
            description="未加载到候选不代表没有可添加账号，请重试。"
            action={<Button size="small" type="primary"
              loading={false}
              onClick={() => store.fetchAccountOptions(store.id)}>重试</Button>}/>
        )}
        <Table rowKey="account_id" size="small" pagination={false}
          loading={store.isFetchingAuthorizations}
          dataSource={rows || []}
          locale={{emptyText: rows === null
            ? '加载中…' : '暂无账号授权：平台超级管理员始终可见全部手册'}}>
          <Table.Column title="账号" dataIndex="account_name" ellipsis/>
          {AUTH_BITS.map(bit => (
            <Table.Column key={bit.key} width={90}
              title={<span title={bit.tip}>{bit.label}</span>}
              render={(_, row, index) => (
                <Checkbox checked={row[bit.key]}
                  onChange={this.handleToggleBit(index, bit.key)}/>
              )}/>
          ))}
          <Table.Column width={60} title=""
            render={(_, row, index) => (
              <Button type="link" size="small" danger
                icon={<DeleteOutlined/>}
                onClick={() => this.handleRemoveRow(index)}/>
            )}/>
        </Table>
        <div style={{marginTop: 12, display: 'flex', gap: 8, flexWrap: 'wrap',
          alignItems: 'center'}}>
          <Select style={{minWidth: 200}} showSearch optionFilterProp="children"
            placeholder="选择要添加授权的账号"
            value={addAccountId}
            onChange={v => this.setState({addAccountId: v})}>
            {options.filter(o => !existingIds.includes(o.id)).map(o => (
              <Option key={o.id} value={o.id}>{o.name}</Option>
            ))}
          </Select>
          <Button size="small" onClick={this.handleAddRow}>添加账号</Button>
          <Button type="primary" size="small" loading={saving}
            onClick={this.handleSave}>保存授权</Button>
          <span style={{color: '#999', fontSize: 12}}>
            <Tag color="purple" style={{marginRight: 4}}>提示</Tag>
            保存为整体替换：已删除的行即撤销对应账号授权
          </span>
        </div>
      </Card>
    );
  }
}

export default AuthorizationCard;
