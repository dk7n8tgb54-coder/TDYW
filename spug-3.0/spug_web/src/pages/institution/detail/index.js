/**
 * Copyright (c) OpenSpug Organization. https://github.com/openspug/spug
 * Released under the AGPL-3.0 License.
 *
 * 制度详情页（2026-10-30 修订状态交互优化）：
 * 页签按信息层级排列——
 * 1. 文件清单（默认）：制度以当前生效版本为主，一张清单承载 顺序/文件名/
 *    大小/负责人/状态/编制提交 与主要操作；修订号、工作副本来源与版本
 *    比较放草稿工作台与变更记录。修订进行中是显式状态（发布成功才结束），
 *    行操作按状态显示「开始修订」（真实状态动作）或「继续编辑」；
 * 2. 版本与发布：整套发布历史与回退/长期保留（发布主入口在头部整套
 *    待发布状态旁，发布者无需进入编辑工作台）；
 * 3. 文件变更记录：按具体文件回看发布参与与维护动作；
 * 4. 初始来源：原始上传文件（查阅/预览/下载与明确的高级恢复入口）；
 * 5. 操作记录 / 权限配置。
 * 文件分工（2026-10-29，替代旧「章节分工」）：分工单位是整份制度文件，
 * 负责人列直接点击修改分工（有权限者），支持勾选多份文件批量分工；
 * 独立的「章节分工」顶层页签已取消；旧章节记录在文件清单页签下方只读
 * 过渡展示，供人工核对。
 * 页签可见性与后端接口权限口径一致（utils.canViewPublished/canViewWorkspace，
 * 后端仍独立校验）；文案始终区分 初始来源/当前草稿/当前生效文件。
 */
import React from 'react';
import { observer } from 'mobx-react';
import { Spin, Tabs, Tag, Button, Result, Modal, message } from 'antd';
import { ArrowLeftOutlined } from '@ant-design/icons';
import { hasPermission, history } from 'libs';
import { AuthDiv } from 'components';
import ManualAuthButton from '../ManualAuthButton';
import { http } from 'libs';
import { canViewPublished } from '../utils';
import store from './store';
import FileListTab from './FileListTab';
import DraftStatusSummary from './DraftStatusSummary';
import PublishButton from './PublishButton';
import VersionsTab from './VersionsTab';
import FileChangeTab from './FileChangeTab';
import OriginalsTab from './OriginalsTab';
import RecordsTab from './RecordsTab';
import ConfigTab from './ConfigTab';

@observer
class InstitutionManualDetail extends React.Component {
  state = {activeKey: null};

  componentDidMount() {
    store.reset();
    const id = this.props.match.params.id;
    store.fetchDetail(id).then(() => {
      // 快速切换手册时丢弃非当前手册的迟到链路
      if (store.id === id && store.manual) {
        // 版本历史属已发布内容：无 can_view_published 口径权限时不发请求
        // （后端 VersionListView 同口径拒绝，不产生注定失败的调用；
        // 与 FileChangeTab 的发布记录守卫同款）
        if (canViewPublished(store.manual)) {
          store.fetchVersions(id);
        }
        // 原稿/文件清单由各页签进页签时按文件级接口懒加载，
        // 旧制度级 /originals/ 列表在多文件制度会被后端拒绝，不在入口预取
        // 旧章节分工记录（遗留只读）入口拉取一次，供文件清单页签过渡展示
        store.fetchChapters(id);
        store.fetchLogs(id);
        // 整套草稿状态摘要（详情头部）：工作区可见者进入即拉取一次；
        // 仅查看角色不请求也不展示（后端对该接口同样拒绝）
        store.fetchDraftStatusIfAllowed(id);
      }
    });
  }

  componentWillUnmount() {
    store.reset();
  }

  handleDelete = () => {
    const manual = store.manual;
    Modal.confirm({
      title: '删除确认',
      content: `确定删除手册「${manual.name}」？删除后不可恢复。`,
      onOk: () => http.delete(`/api/institution/manuals/${manual.id}/`)
        .then(() => {
          message.success('删除成功');
          history.push('/institution');
        }),
    });
  };

  /** 文件清单行「变更记录」→ 切到文件变更记录页签（预选由 store 传递） */
  handleOpenFileHistory = () => {
    this.setState({activeKey: 'file-changes'});
  };

  renderHeader() {
    const manual = store.manual;
    const canEdit = (manual.my_roles || []).includes('edit');
    // 元数据管理功能资格：页面码；手册所有者对象级豁免（规则 2：
    // 所有者对本人手册拥有全部权限，后端 manual_auth 同口径）
    const canManage = manual.is_owner ||
      hasPermission('institution.manual.edit') ||
      hasPermission('institution.manual.config');
    return (
      <div style={{marginBottom: 12}}>
        <div style={{display: 'flex', alignItems: 'center', gap: 12}}>
          <Button type="link" icon={<ArrowLeftOutlined/>} style={{padding: 0}}
            onClick={() => history.push('/institution')}>返回</Button>
          <h2 style={{margin: 0}}>{manual.name}</h2>
          {manual.code && <Tag>{manual.code}</Tag>}
          <Tag color={manual.status === 'active' ? 'green' : 'default'}>
            {manual.status_display}
          </Tag>
          <Tag>{manual.org_type_display || '-'} · {manual.org_name || '-'}</Tag>
          {typeof manual.files_count === 'number' && (
            <Tag>{manual.files_count} 份文件</Tag>
          )}
        </div>
        <div style={{marginTop: 8, display: 'flex', gap: 8}}>
          {/* 草稿工作台后端要求手册编制资格（can_edit_manual_files，所有者
              豁免），与入口口径一致；仅有管理权限无编制资格者进入只会撞
              错误页。按文件编辑请用文件清单行内的「继续编辑」（深链直达
              对应文件）。所有者不需要 draft_edit 页面码（ManualAuthButton）。 */}
          {canEdit && manual.status === 'active' && (
            <ManualAuthButton manual={manual} auth="institution.manual.draft_edit"
              size="small"
              onClick={() => history.push(`/institution/manuals/${manual.id}/draft`)}>
              草稿工作台
            </ManualAuthButton>
          )}
          {canManage && (
            <ManualAuthButton manual={manual} auth="institution.manual.delete"
              size="small" danger type="link"
              disabled={!!manual.current_version}
              onClick={this.handleDelete}>删除手册</ManualAuthButton>
          )}
        </div>
        {/* 整套草稿状态摘要（显眼位置）+ 发布新版本入口（发布角色，位于
            整套待发布状态旁而非版本历史中；发布者无需进入编辑工作台即可
            核对整套变化并发布） */}
        <div style={{display: 'flex', alignItems: 'flex-start', gap: 8}}>
          <div style={{flex: 1, minWidth: 0}}>
            <DraftStatusSummary/>
          </div>
          <PublishButton/>
        </div>
      </div>
    );
  }

  render() {
    if (store.isFetching && !store.manual) {
      return <div style={{padding: 40, textAlign: 'center'}}><Spin/></div>;
    }
    if (store.error && !store.manual) {
      return (
        <Result status="403" title="无法打开手册" subTitle={store.error}
          extra={<Button type="primary" onClick={() => history.push('/institution')}>返回列表</Button>}/>
      );
    }
    if (!store.manual) return null;
    // 「权限配置」页签可见（2026-10-31 授权模型）：持 config 权限码者
    // （编辑密码维护等配置能力），或手册所有者/平台超管（管理本手册
    // 的账号授权与所有者）。后端对各接口仍独立校验。
    const canConfig = hasPermission('institution.manual.config') ||
      store.manual.is_owner || store.manual.is_admin;
    const activeKey = this.state.activeKey || 'files';
    return (
      <AuthDiv auth="institution.manual.view">
        {this.renderHeader()}
        {/* 受控页签：文件清单行可直达「文件变更记录」并预选该文件 */}
        <Tabs activeKey={activeKey} onChange={key => this.setState({activeKey: key})}>
          <Tabs.TabPane tab="文件清单" key="files">
            <FileListTab onOpenFileHistory={this.handleOpenFileHistory}/>
          </Tabs.TabPane>
          <Tabs.TabPane tab="版本与发布" key="versions">
            <VersionsTab/>
          </Tabs.TabPane>
          <Tabs.TabPane tab="文件变更记录" key="file-changes">
            <FileChangeTab/>
          </Tabs.TabPane>
          <Tabs.TabPane tab="初始来源" key="originals">
            <OriginalsTab/>
          </Tabs.TabPane>
          <Tabs.TabPane tab="操作记录" key="logs">
            <RecordsTab/>
          </Tabs.TabPane>
          {canConfig && (
            <Tabs.TabPane tab="权限配置" key="config">
              <ConfigTab/>
            </Tabs.TabPane>
          )}
        </Tabs>
      </AuthDiv>
    );
  }
}

export default InstitutionManualDetail;
