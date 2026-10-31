/**
 * Copyright (c) OpenSpug Organization. https://github.com/openspug/spug
 * Released under the AGPL-3.0 License.
 *
 * 初始来源页签（2026-10-29 改版）：
 * - 一次拉取 originals-overview 聚合清单，每份制度文件一行：文件名、
 *   最初原稿的上传人与时间、首次进入的发布版本（原稿保护边界）、
 *   直接预览/下载；多条原稿记录在该行展开历史（新→旧）。
 * - 明确区分最初原稿与后续记录；初始来源不是当前生效内容（生效内容
 *   在「当前生效文件」，日常编辑在「草稿工作区」）。
 * - 「新增制度文件」（批量，每个上传文件各建一份制度文件）与
 *   「为已有文件更换来源」（按行受控操作，确认目标文件与草稿影响）
 *   严格分开，互不混用。两者业务门=手册所有者或制度管理员
 *   （2026-10-31 授权模型；页面权限码 upload 不变，后端独立校验）。
 * - 「从原始上传文件重建草稿」是明确的高级操作：未发布过版本可直接
 *   确认；已发布过版本收进"高级恢复操作"，带风险提示 + confirm=true
 *   + 编辑密码（后端独立校验）；原稿已按保留策略清理时禁用并解释。
 *   重建按文件负责人独占判定（编制授权 + assignment.is_mine）。
 */
import React from 'react';
import { observer } from 'mobx-react';
import { Table, Tag, Modal, message, Input, Alert, Button, Empty, Tooltip } from 'antd';
import { AuthButton } from 'components';
import { http } from 'libs';
import { downloadFile, formatSize, formatDateTime } from '../utils';
import PreviewModal from './PreviewModal';
import store from './store';

const CLEANED_TAG = <Tag color="default">已清理</Tag>;

@observer
class OriginalsTab extends React.Component {
  state = {
    preview: null,
    uploading: false,
    // 待"更换来源"的目标文件行（change 事件里据此分支上传语义）
    pendingReplace: null,
    advancedRecovery: false,
  };

  componentDidMount() {
    // 进页签一次拉取聚合清单（每文件一行），不做逐文件选择与逐行请求
    store.fetchOriginalsOverview(store.id);
  }

  componentWillUnmount() {
    this.unmounted = true;
  }

  showPreview = (request, fileName, title) => {
    request.then(data => {
      this.setState({preview: {
        url: data.preview_url, fileName: data.file_name || fileName, title,
      }});
    });
  };

  previewOriginal = (row, o) => {
    const name = o.file_name || row.name;
    // 版本来源明确：初始原稿与后续来源原稿在标题中分开
    const isFirst = row.first_original && row.first_original.id === o.id;
    this.showPreview(
      http.get(`/api/institution/manuals/${store.id}/originals/${o.id}/preview-url/`),
      name, `${isFirst ? '预览初始原稿' : '预览后续来源原稿'}：${name}`);
  };

  downloadOriginal = (row, o) => {
    downloadFile(
      `/api/institution/manuals/${store.id}/files/${row.file_id}/originals/${o.id}/download/`,
      o.file_name || row.name);
  };

  /**
   * 「从原始上传文件重建草稿」：原稿只用于首次建立草稿或管理员明确的
   * 重建操作，绝不是日常编辑入口（日常恢复走草稿工作台「从当前生效
   * 版本恢复草稿」）。已发布过版本（含废止）时：高风险确认 + 丢弃草稿
   * 需编辑密码 + confirm=true；原稿已清理的记录不渲染本入口。
   */
  createDraft = (row, original) => {
    const manual = store.manual || {};
    const hasDraft = !!(row.draft && row.draft.has_draft);
    if (manual.has_versions) {
      const needPassword = !!(manual.has_password && hasDraft);
      let password = '';
      Modal.confirm({
        title: '从原始上传文件重建草稿（高级恢复操作）',
        content: (
          <div>
            <p>
              将以原始上传文件「{original.file_name}」的副本重建制度文件
              「{row.name}」的草稿，当前草稿内容将被丢弃，操作不可撤销。
            </p>
            <p style={{color: '#f5222d'}}>
              该制度已发布过版本：如只是要恢复草稿，请优先在草稿工作台
              「从当前生效版本恢复草稿」；本操作以原始文件（而非当前生效版本）
              为编辑基线，仅限管理员明确要求从原始文件重新开始时使用。
            </p>
            {needPassword && (
              <Input.Password type="password" placeholder="请输入编辑密码确认"
                onChange={e => { password = e.target.value; }} style={{marginTop: 8}}/>
            )}
          </div>
        ),
        okText: '确认重建',
        onOk: () => {
          if (needPassword && !password) {
            message.warning('请输入编辑密码确认');
            return Promise.reject();
          }
          return http.post(
            `/api/institution/manuals/${store.id}/files/${row.file_id}/draft/create/`,
            Object.assign(
              {original_id: original.id, confirm: true},
              needPassword ? {password} : {}))
            .then(() => {
              message.success('已按原始上传文件重建草稿');
              this.refresh();
            });
        },
      });
      return;
    }
    Modal.confirm({
      title: '创建草稿',
      content: `将以原稿「${original.file_name}」的副本创建制度文件「${row.name}」的草稿` +
        (hasDraft ? '（已有草稿将被替换，修订序号继续递增）' : '') + '。确认继续？',
      onOk: () => http.post(
        `/api/institution/manuals/${store.id}/files/${row.file_id}/draft/create/`,
        {original_id: original.id})
        .then(() => {
          message.success('草稿已就绪，可进入草稿工作台');
          this.refresh();
        }),
    });
  };

  /**
   * 为已有文件更换来源（按行受控操作）：先选择文件，再确认目标文件与
   * 对草稿的影响，确认后才上传为该文件的一条新原稿记录（不改动草稿）。
   */
  pickReplaceSource = (row) => {
    this.setState({pendingReplace: row}, () => {
      if (this.fileInput) this.fileInput.click();
    });
  };

  confirmReplaceSource = (picked) => {
    const row = this.state.pendingReplace;
    if (!row || !picked.length) return;
    const hasDraft = !!(row.draft && row.draft.has_draft);
    Modal.confirm({
      title: '为已有文件更换来源',
      content: (
        <div>
          <p>目标制度文件：<b>{row.name}</b></p>
          <p>将上传 {picked.length} 份文件作为该文件新的初始来源记录：
            「{picked.map(f => f.name).join('、')}」。</p>
          <p>
            上传不会改动当前草稿
            {hasDraft ? `（当前草稿修订号 r${row.draft.revision} 保持不变）` : ''}
            ；如需以新来源重建草稿，请在展开历史中对新记录执行
            「从原始上传文件重建草稿」。
          </p>
        </div>
      ),
      okText: '确认上传',
      onOk: () => this.uploadOriginals(picked, row),
    });
  };

  async uploadOriginals(picked, row) {
    this.setState({uploading: true});
    let okCount = 0;
    // 逐个顺序上传：单个失败（拦截器已弹错）不中断剩余文件
    for (const file of picked) {
      const formData = new FormData();
      formData.append('file', file);
      try {
        await http.post(
          `/api/institution/manuals/${store.id}/files/${row.file_id}/originals/upload/`,
          formData);
        okCount += 1;
      } catch (err) {
        // 拦截器已提示单个失败，继续传剩余文件
      }
    }
    if (this.unmounted) return;
    this.setState({uploading: false, pendingReplace: null});
    if (okCount) message.success(`已为「${row.name}」上传 ${okCount} 份来源文件`);
    this.refresh();
  }

  async doCreateFiles(picked) {
    if (!picked.length) return;
    this.setState({uploading: true});
    // 批量新增：每个上传文件各建一份制度文件（条目+原稿+草稿一步），
    // 绝不因选中项把多个文件追加到同一份制度文件。
    let okCount = 0;
    for (const file of picked) {
      const formData = new FormData();
      formData.append('file', file);
      try {
        const data = await http.post(
          `/api/institution/manuals/${store.id}/files/create/`, formData);
        okCount += 1;
        // draft_error 非空 = 文件已创建但草稿未就绪（如 .doc 转换失败）：
        // 只警示不算失败
        if (data && data.draft_error) message.warning(data.draft_error);
      } catch (err) {
        // 拦截器已提示单个失败，继续传剩余文件
      }
    }
    if (this.unmounted) return;
    this.setState({uploading: false});
    if (okCount) message.success(`已新增 ${okCount} 份制度文件并生成草稿`);
    this.refresh();
  }

  handleInputChange = (e) => {
    const picked = Array.from(e.target.files || []);
    e.target.value = '';
    if (!picked.length) return;
    if (this.state.pendingReplace) this.confirmReplaceSource(picked);
    else this.doCreateFiles(picked);
  };

  refresh() {
    store.fetchOriginalsOverview(store.id);
    store.fetchDetail(store.id);
  }

  renderOriginalActions = (row, o) => {
    if (o.is_cleaned) {
      return <Tooltip title="原稿本体已按保留策略清理，仅存来源元数据（上传人/时间/哈希/清理时间）">
        {CLEANED_TAG}
      </Tooltip>;
    }
    return (
      <span>
        <AuthButton auth="institution.manual.view" type="link" size="small"
          onClick={() => this.previewOriginal(row, o)}>预览</AuthButton>
        <AuthButton auth="institution.manual.download" type="link" size="small"
          onClick={() => this.downloadOriginal(row, o)}>下载</AuthButton>
        {/* 已发布过版本：重建按钮收进"高级恢复操作"，默认不显示 */}
        {this.canRebuild(row) && (
          <AuthButton auth="institution.manual.draft_edit" type="link" size="small"
            danger={!!(store.manual && store.manual.has_versions)}
            onClick={() => this.createDraft(row, o)}>从原始上传文件重建草稿</AuthButton>
        )}
      </span>
    );
  };

  /**
   * 「重建草稿」门控（2026-10-31 负责人独占）：编制授权（my_roles.edit）
   * 且该文件负责人（assignment.is_mine）。row 为 originals-overview 行，
   * 负责人信息按 file_id 从 /files/ 清单（store.files）就地取；查不到
   * （已移除条目等）一律视为非负责人，不渲染入口。
   */
  isFileAssignee(row) {
    const entry = (store.files || []).find(f => f.id === row.file_id);
    return !!(entry && entry.assignment && entry.assignment.is_mine);
  }

  canRebuild(row) {
    const manual = store.manual || {};
    if (!(manual.my_roles || []).includes('edit')) return false;
    if (!this.isFileAssignee(row)) return false;
    return !manual.has_versions || this.state.advancedRecovery;
  }

  renderExpandedRow = (row) => (
    <Table rowKey="id" size="small" dataSource={row.history || []} pagination={false}>
      <Table.Column title="标记" width={90}
        render={(_, o) => (row.first_original && o.id === row.first_original.id
          ? <Tag color="blue">最初原稿</Tag> : <Tag>后续来源</Tag>)}/>
      <Table.Column title="文件名" dataIndex="file_name" ellipsis/>
      <Table.Column title="类型" dataIndex="ext" width={70}
        render={v => (v || '').toUpperCase()}/>
      <Table.Column title="大小" dataIndex="file_size" width={90}
        render={v => formatSize(v)}/>
      <Table.Column title="上传人" dataIndex="uploaded_by_name" width={100}/>
      <Table.Column title="上传时间" dataIndex="uploaded_at" width={145}
        render={v => formatDateTime(v)}/>
      <Table.Column title="清理时间" dataIndex="cleaned_at" width={145}
        render={v => (v ? formatDateTime(v) : '-')}/>
      <Table.Column title="操作" width={300}
        render={(_, o) => this.renderOriginalActions(row, o)}/>
    </Table>
  );

  /** 初始来源总览表：制度文件行 + 最初原稿/首次发布/来源记录/操作列 */
  renderOverviewTable(manual, canManageFiles, rows) {
    return (
      <Table rowKey="file_id" size="middle"
        loading={store.isFetchingOriginalsOverview}
        dataSource={rows} pagination={false}
        expandedRowRender={this.renderExpandedRow}
        locale={{emptyText: (
          <Empty description="该制度还没有制度文件；点击上方按钮上传第一份文件"/>)}}>
        <Table.Column title="制度文件" dataIndex="name" ellipsis
          render={(v, row) => (
            <span>
              {v}
              {row.is_removed && <Tag style={{marginLeft: 8}}>已移除</Tag>}
            </span>
          )}/>
        <Table.Column title="最初原稿" key="first" ellipsis
          render={(_, row) => {
            const first = row.first_original;
            if (!first) return '-';
            return (
              <span>
                {first.file_name}
                <span style={{color: '#888', marginLeft: 8}}>
                  {first.uploaded_by_name || '-'} · {formatDateTime(first.uploaded_at)}
                </span>
                {first.is_cleaned && CLEANED_TAG}
              </span>
            );
          }}/>
        <Table.Column title="首次发布" dataIndex="first_published_version_no" width={95}
          render={v => (v != null ? `v${v}` : '未发布')}/>
        <Table.Column title="来源记录" key="count" width={110}
          render={(_, row) => `${row.originals_count} 条（展开历史）`}/>
        <Table.Column title="操作" width={280}
          render={(_, row) => {
            const first = row.first_original;
            return (
              <span>
                {first && !first.is_cleaned && (
                  <span>
                    <AuthButton auth="institution.manual.view" type="link" size="small"
                      onClick={() => this.previewOriginal(row, first)}>预览</AuthButton>
                    <AuthButton auth="institution.manual.download" type="link" size="small"
                      onClick={() => this.downloadOriginal(row, first)}>下载</AuthButton>
                  </span>
                )}
                {first && first.is_cleaned && CLEANED_TAG}
                <Tooltip title={canManageFiles
                  ? '为该文件上传一条新的初始来源记录（不改动当前草稿）'
                  : '更换来源仅限手册所有者或制度管理员'}>
                  <AuthButton auth="institution.manual.upload" type="link" size="small"
                    disabled={this.state.uploading || !canManageFiles}
                    onClick={() => this.pickReplaceSource(row)}>更换来源</AuthButton>
                </Tooltip>
                {/* 主行重建入口基于最初原稿；后续来源记录的重建在展开历史内 */}
                {first && !first.is_cleaned && this.canRebuild(row) && (
                  <AuthButton auth="institution.manual.draft_edit" type="link" size="small"
                    danger={!!manual.has_versions}
                    onClick={() => this.createDraft(row, first)}>重建草稿</AuthButton>
                )}
              </span>
            );
          }}/>
      </Table>
    );
  }

  render() {
    const manual = store.manual || {};
    // 「更换来源/上传原稿（新增制度文件）」业务门=手册所有者或制度管理员
    // （后端 files/create 与 originals/upload 同口径，2026-10-31 起）；
    // 「重建草稿」另按文件负责人独占判定（canRebuild(row)）
    const canManageFiles = !!manual.is_owner || !!manual.is_admin;
    const canEditRole = (manual.my_roles || []).includes('edit');
    const canRebuildAnywhere = canEditRole &&
      (store.originalsOverview || []).some(row => this.isFileAssignee(row));
    const rows = store.originalsOverview || [];
    return (
      <div>
        <Alert type="info" showIcon style={{marginBottom: 8}} message={
          <span>
            <b>初始来源</b>是各制度文件最初上传的原始文件与后续更换的来源记录，
            仅用于查阅、预览与下载，不是当前生效内容——最新生效内容以
            「当前生效文件」为准，日常编辑请在「草稿工作区」进行。原稿本体在
            对应文件首次发布并超过保留缓冲期前受保护；已按保留策略清理的
            记录仅保留来源元数据。
          </span>}/>
        <div style={{marginBottom: 8, display: 'flex', alignItems: 'center', gap: 8}}>
          {/* 隐藏 input 不得作为 Button/label 的嵌套子节点（嵌套会双触发
              或留死按钮），统一 ref 程序触发，见 handleInputChange */}
          <input ref={el => { this.fileInput = el; }} type="file"
            accept=".doc,.docx" multiple style={{display: 'none'}}
            onChange={this.handleInputChange}/>
          <AuthButton auth="institution.manual.upload" type="primary" size="small"
            loading={this.state.uploading}
            disabled={!canManageFiles}
            onClick={() => this.fileInput && this.fileInput.click()}>
            {rows.length
              ? '新增制度文件（.doc/.docx，可多选，每份各建一个制度文件）'
              : '上传文件（.doc/.docx，可多选，每份各建一个制度文件与草稿）'}
          </AuthButton>
          {!canManageFiles && (
            <span style={{color: '#999', fontSize: 12}}>
              新增制度文件与更换来源仅限手册所有者或制度管理员
            </span>
          )}
        </div>
        {canRebuildAnywhere && manual.has_versions && rows.length > 0 && (
          <div style={{marginBottom: 8}}>
            {this.state.advancedRecovery && (
              <Alert type="warning" showIcon style={{marginBottom: 8}} message={
                '高级恢复操作：「从原始上传文件重建草稿」会以原始文件替换当前草稿内容，' +
                '仅用于当前生效版本不含该文件或管理员明确要求从原始文件重新开始的场景；' +
                '日常恢复请进入草稿工作台「从当前生效版本恢复草稿」。'}/>
            )}
            <Button type="link" size="small" style={{paddingLeft: 0}}
              onClick={() =>
                this.setState(s => ({advancedRecovery: !s.advancedRecovery}))}>
              {this.state.advancedRecovery ? '收起高级恢复操作' : '高级恢复操作'}
            </Button>
          </div>
        )}
        {store.originalsOverviewError && (
          <Alert type="error" showIcon style={{marginBottom: 8}}
            message={store.originalsOverviewError}
            action={<Button size="small" type="primary"
              onClick={() => store.fetchOriginalsOverview(store.id)}>重试</Button>}/>
        )}
        {this.renderOverviewTable(manual, canManageFiles, rows)}
        <PreviewModal visible={!!this.state.preview} url={this.state.preview && this.state.preview.url}
          fileName={this.state.preview && this.state.preview.fileName}
          title={this.state.preview && this.state.preview.title}
          onClose={() => this.setState({preview: null})}/>
      </div>
    );
  }
}

export default OriginalsTab;
