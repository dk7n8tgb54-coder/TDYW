/**
 * Copyright (c) OpenSpug Organization. https://github.com/openspug
 * Released under the AGPL-3.0 License.
 *
 * Excel 上传版维护台账模板页（2026-09-28 试点；2026-10-14 交互改造；
 * 2026-10-21 新建流程配置前置 + 编辑视图统一观感）。
 *
 * 两种视图：
 * - 列表：唯一主操作「新建模板」——名称/台账类型/适用系统/生成周期/
 *   源文件集中在弹窗内一次完成（2026-10-21 配置前置：选择文件不立即
 *   创建模板或上传，「创建并进入模板编辑」统一缺项校验后一次提交，
 *   适用系统与生成周期随创建同请求保存，缺项在对应位置提示；季维护
 *   自动设置并显示「每航季」，切换台账类型清除不兼容周期）；下载样例
 *   随流程内提供；行操作按状态显示「编辑草稿 / 上传源文件 / 查看模板」，
 *   待配置模板（缺适用系统或生成周期）提供行内「补全配置」入口
 *   （2026-10-21，不做自动推断），版本记录与停用/删除收进行内「更多」
 *   菜单（停用=逻辑停用，删除=物理删除，del 权限门禁）；在用/已停用
 *   双视图 + 关键词/类型过滤 + 分页（2026-10-19）；
 *   页面底部提供前往正式周月/季维护台账的填写入口；
 * - 绑定工作区（2026-10-21 统一观感）：顶部返回入口/名称/类型/状态与
 *   全部操作，信息行集中展示台账类型、源文件、绑定字段数、当前版本与
 *   生成配置（未配置显示"待配置"并提供「配置」入口）；「字段绑定 /
 *   打印预览」两个视图（默认字段绑定）——字段绑定视图左侧为可收起的
 *   字段绑定面板（单字段属性 + 批量绑定 + 已绑定字段导航），中央表格
 *   与台账填写界面同一套纸张观感（灰底白纸/页边距/分页参考线/适合
 *   页宽与原始尺寸/多工作表切换，共用 PaperSheetArea，分页信息优先取
 *   草稿统一打印计划 print_plan）；打印预览视图当前页面内 iframe 展示
 *   真实生成的 PDF（同一模板预览服务，已保存参数），标注页数/纸张与
 *   参数来源，草稿在预览后变更提示刷新；发布禁用原因独立一行说明；
 *   替换源文件选定文件后先弹确认（提示将清空的绑定数与打印参数重置）；
 *   已停用模板仅供查看（替换/发布/打印设置/选格编辑与导航定位冻结，
 *   后端独立校验兜底）；字段名称自动生成、混合批量选区、拖拽选区禁
 *   文字选择、Escape 取消等交互保持不变（实现见 TemplateWorkspace
 *   与 store）；
 * - 历史版本（2026-10-21）：打开模板固定进入当前草稿（不回退到最新
 *   发布版本），信息行显示草稿更新时间/人与内容关系（identical/
 *   modified/unknown 由后端按内容签名判定，无法确认时如实显示）；
 *   版本记录抽屉每行可「查看内容」——只读查看器（VersionViewerDrawer）
 *   用版本自身快照渲染版式/绑定/打印参数与真实 PDF 预览（与模板编辑
 *   同一套纸张展示层），并提供「复制为新草稿」（二次确认明确替换当前
 *   草稿/绑定/打印参数，历史版本不修改、不自动发布，成功后刷新详情，
 *   失败保留现状不提示成功）。
 *
 * 不支持的文件特性（公式/图表/图片/外部链接/透视表）由后端显式拒绝，
 * 错误信息逐项列出（公共拦截器提示，不静默导入）。
 */
import React from 'react';
import {observer} from 'mobx-react';
import {
  Alert, Button, Card, Drawer, Dropdown, Empty, Input, Menu,
  Modal, Popconfirm, Radio, Select, Space, Spin, Table, Tag, Upload,
  message,
} from 'antd';
import {
  ArrowLeftOutlined, CheckCircleOutlined, DeleteOutlined, DownOutlined,
  DownloadOutlined, FileExcelOutlined, HistoryOutlined, PrinterOutlined,
  StopOutlined, UploadOutlined,
} from '@ant-design/icons';
import {hasPermission, history} from 'libs';

import excelTemplateStore, {LIST_PAGE_SIZE} from './excelTemplateStore';
import excelVersionStore from './excelVersionStore';
import {draftRelationText} from './excelVersionView';
import PdfParamsDrawer, {PreviewInfoAlert} from './PdfParamsDrawer';
import {PERM_L} from '../constants';
import {TemplateWorkspaceBody} from './components/TemplateWorkspace';
import VersionViewerDrawer from './components/VersionViewerDrawer';
import './ExcelTemplateWorkspace.less';

const LEDGER_TYPE_TEXT = {week_month: '周月维护', seasonal: '季维护'};
const TEMPLATE_STATUS = {
  draft: {text: '草稿', color: 'default'},
  published: {text: '已发布', color: 'blue'},
  used: {text: '已使用', color: 'green'},
  deleted: {text: '已停用', color: 'red'},
};

/** 生成配置展示：适用系统（待配置标注）与生成周期文本。 */
function systemColumn(record) {
  if (!record.system) return <Tag data-testid="tpl-system-unset">待配置</Tag>;
  return `${record.system_name}（${record.system_code}）`;
}

@observer
class ExcelTemplatePage extends React.Component {
  state = {versionTarget: null};  // 版本抽屉归属模板 {id, name, isActive}

  get store() {
    return this.props.store || excelTemplateStore;
  }

  get versionStore() {
    return this.props.versionStore || excelVersionStore;
  }

  componentDidMount() {
    this.store.fetchList().catch(() => {});
    // 拖拽矩形选区在表格任意位置松开鼠标即结束；鼠标离开窗口/取消拖拽
    // （Escape）同样结束，并恢复表格正常文字选择
    this._handleMouseUp = () => this.store.endDrag();
    document.addEventListener('mouseup', this._handleMouseUp);
    this._handleMouseLeave = () => this.store.endDrag();
    document.addEventListener('mouseleave', this._handleMouseLeave);
    this._handleKeyDown = event => {
      if (event.key === 'Escape' && this.store.isDragging) {
        this.store.resetSelection();
      }
    };
    document.addEventListener('keydown', this._handleKeyDown);
  }

  componentWillUnmount() {
    [['mouseup', '_handleMouseUp'], ['mouseleave', '_handleMouseLeave'],
      ['keydown', '_handleKeyDown']].forEach(([eventName, key]) => {
      if (this[key]) {
        document.removeEventListener(eventName, this[key]);
        this[key] = null;
      }
    });
  }

  /** 创建并进入模板编辑：store 统一校验后一次提交；成功关闭弹窗并进入
   * 绑定工作区（失败弹窗保持打开可修正重试，公共拦截器已提示）。 */
  handleCreateSubmit = () => {
    this.store.submitCreate()
      .then(detail => {
        if (!detail) return;
        this.store.closeCreateModal();
        message.success('模板创建成功，请绑定可填写单元格');
      })
      .catch(() => {});
  };

  /** 替换源文件：只校验扩展名并登记待确认文件，确认弹窗通过后才上传。 */
  pickReuploadFile = file => {
    if (!/\.xlsx$/i.test(file.name)) {
      message.error('仅支持 .xlsx 文件');
      return false;
    }
    this.store.requestReupload(file);
    return false;
  };

  handlePublish = () => {
    const store = this.store;
    if (!store.bindings.length) {
      message.warning('请先绑定至少一个可填写字段再发布');
      return;
    }
    store.publish().catch(() => {});
  };

  /** 发布禁用原因：与真实发布条件一致（warning 不视为阻断）。 */
  publishBlockReason() {
    const store = this.store;
    if (!store.current.is_active) return '模板已停用';
    if (!store.draft) return '尚未上传源文件';
    if (!store.bindings.length) return '尚未绑定可填写字段';
    const compat = store.compatibility;
    if (compat && compat.status === 'error') return '兼容性检查存在问题';
    return '';
  }

  /** 工作区「版本记录」：记录归属模板后打开抽屉（查看内容/复制入口可用）。 */
  showVersions = () => {
    const current = this.store.current;
    this.setState({versionTarget: current
      ? {id: current.id, name: current.name, isActive: current.is_active}
      : null});
    this.store.showVersionsFor(current).catch(() => {});
  };

  /** 列表行「版本记录」：按行取数打开抽屉，不改动当前模板详情；此时
   * 只提供只读查看（复制入口仅在打开同一模板详情时出现）。 */
  showRowVersions = record => {
    this.setState({versionTarget: record
      ? {id: record.id, name: record.name, isActive: record.is_active}
      : null});
    this.store.showVersionsFor(record).catch(() => {});
  };

  /** 版本抽屉行「查看内容」：拉取该版本快照并打开只读查看抽屉。 */
  handleViewVersion = row => {
    const target = this.state.versionTarget;
    if (!target) return;
    this.versionStore.open(target.id, target.name, row.version_no,
                           target.isActive).catch(() => {});
  };

  /**
   * 「复制为新草稿」：二次确认明确替换范围（当前草稿/绑定/打印参数被
   * 整体替换；历史版本不修改、不自动发布），确认后才调用复制接口；
   * 成功后以服务端返回刷新模板详情并回到草稿编辑视图；失败保留当前
   * 状态（确认弹窗保持打开，错误由公共拦截器提示，不提示成功）。
   */
  handleCopyVersion = () => {
    const versionStore = this.versionStore;
    const version = versionStore.version;
    if (!version || versionStore.copying) return;
    Modal.confirm({
      title: `把 v${version.version_no} 复制为当前草稿？`,
      content: (
        <div data-testid="tpl-copy-confirm">
          <p style={{color: '#fa541c'}}>
            当前草稿将被 v{version.version_no} 的内容整体替换：
          </p>
          <ul style={{paddingLeft: 20, margin: '8px 0'}}>
            <li>当前草稿源文件将被替换</li>
            <li>现有字段绑定将被替换</li>
            <li>当前打印参数将被替换</li>
          </ul>
          <p>
            历史版本（包括本版本）不会被修改，复制后<b>不会自动发布</b>，
            需要发布时请手动操作。
          </p>
        </div>
      ),
      okText: '复制并替换草稿', okType: 'danger', cancelText: '取消',
      onOk: async () => {
        const detail = await versionStore.copyToDraft();
        this.store.applyDetail(detail);
        versionStore.close();
        message.success(`已把 v${version.version_no} 复制为当前草稿`);
        return detail;
      },
    });
  };

  /** 行停用确认（Modal.confirm）：保留引用台账数提示与 del 权限门禁。 */
  confirmStopTemplate = record => {
    Modal.confirm({
      title: '停用模板',
      content: record.ledgers_count > 0
        ? `该模板已被 ${record.ledgers_count} 个台账引用：停用后将停止新台账使用，历史台账仍可查看与导出。确定停用吗？`
        : '停用后将停止该模板使用，历史台账仍可查看，确定停用吗？',
      okText: '停用', okType: 'danger', cancelText: '取消',
      onOk: () => this.store.deactivateTemplate(record.id),
    });
  };

  /** 行重新启用确认（2026-10-19）：停用的逆操作，恢复新台账使用与自动生成。 */
  confirmActivateTemplate = record => {
    Modal.confirm({
      title: '重新启用模板',
      content: `重新启用后「${record.name}」将恢复用于新台账与本期应填台账自动生成，历史台账不受影响。确定重新启用吗？`,
      okText: '重新启用', cancelText: '取消',
      onOk: () => this.store.activateTemplate(record.id),
    });
  };

  /** 行删除确认（2026-10-16 拆分）：物理删除模板与全部版本；
   * 引用关系由后端删除时重新检查（被引用时拒绝）。 */
  confirmDestroyTemplate = record => {
    Modal.confirm({
      title: '删除模板',
      content: (
        <div>
          <p style={{color: '#f5222d'}}>
            删除后模板、全部已发布版本与源文件将被移除，且不可恢复。
          </p>
          {record.ledgers_count > 0 && (
            <p>该模板已被 {record.ledgers_count} 个台账引用，删除将被拒绝；如需停止使用请改为停用。</p>
          )}
        </div>
      ),
      okText: '删除', okType: 'danger', cancelText: '取消',
      onOk: () => this.store.destroyTemplate(record.id),
    });
  };

  /**
   * 新建模板弹窗（列表页唯一主操作流程，2026-10-21 配置前置）：
   * 名称/台账类型/适用系统/生成周期/源文件一次填齐；选择文件只登记
   * 不上传，「创建并进入模板编辑」统一校验后一次提交；缺项在对应
   * 位置提示；下载样例随流程内提供。
   */
  _renderCreateModal() {
    const store = this.store;
    const errorLine = key => (store.createErrors[key] ? (
      <div className="excel-create-field-error"
           data-testid={`tpl-create-error-${key}`}>{store.createErrors[key]}</div>
    ) : null);
    return (
      <Modal title="新建 Excel 台账模板" visible={store.createVisible}
             width={560} confirmLoading={store.uploading}
             okText="创建并进入模板编辑"
             okButtonProps={{'data-testid': 'tpl-create-submit'}}
             cancelText="取消"
             onOk={this.handleCreateSubmit}
             onCancel={() => {
               if (!store.uploading) store.closeCreateModal();
             }}>
        <div style={{marginBottom: 12}}>
          <div style={{marginBottom: 4}}>模板名称</div>
          <Input data-testid="tpl-name" placeholder="如：信道维护记录表" maxLength={100}
                 value={store.uploadName}
                 onChange={e => store.setUploadField('uploadName', e.target.value)}/>
          {errorLine('name')}
        </div>
        <div style={{marginBottom: 12}}>
          <div style={{marginBottom: 4}}>台账类型</div>
          <Select data-testid="tpl-type" placeholder="请选择台账类型" style={{width: '100%'}}
                  value={store.uploadType}
                  onChange={value => store.setUploadField('uploadType', value)}>
            <Select.Option value="week_month">周月维护</Select.Option>
            <Select.Option value="seasonal">季维护</Select.Option>
          </Select>
          {errorLine('uploadType')}
        </div>
        <div style={{marginBottom: 12}}>
          <div style={{marginBottom: 4}}>适用系统（一个模板只对应一个系统）</div>
          <Select data-testid="tpl-system" showSearch optionFilterProp="children"
                  placeholder="请选择适用系统" style={{width: '100%'}}
                  value={store.uploadSystem}
                  onChange={value => store.setUploadField('uploadSystem', value)}>
            {store.createOptions.systems.map(s => (
              <Select.Option key={s.id} value={s.id}>
                {`${s.name}（${s.system_code}）${s.is_active ? '' : ' [已停用]'}`}
              </Select.Option>
            ))}
          </Select>
          {errorLine('uploadSystem')}
        </div>
        <div style={{marginBottom: 12}}>
          <div style={{marginBottom: 4}}>生成周期
            {store.uploadType === 'seasonal' && (
              <span style={{color: '#999', marginLeft: 8}}>季维护固定为每航季（已自动设置）</span>
            )}
          </div>
          <Select data-testid="tpl-period" placeholder="请选择生成周期"
                  style={{width: '100%'}}
                  value={store.uploadPeriod || undefined}
                  onChange={value => store.setUploadField('uploadPeriod', value || '')}>
            {store.createPeriodOptions.map(p => (
              <Select.Option key={p.value} value={p.value}>{p.label}</Select.Option>
            ))}
          </Select>
          {errorLine('uploadPeriod')}
        </div>
        <div style={{marginBottom: 12}}>
          <div style={{marginBottom: 4}}>模板文件</div>
          <Space wrap>
            <Upload accept=".xlsx" showUploadList={false}
                    beforeUpload={file => store.pickCreateFile(file)}>
              <Button data-testid="tpl-upload" icon={<UploadOutlined/>}>
                选择 .xlsx 文件
              </Button>
            </Upload>
            {store.uploadFileName ? (
              <span data-testid="tpl-file-name">
                <FileExcelOutlined/> {store.uploadFileName}
                <a data-testid="tpl-file-remove" style={{marginLeft: 8}}
                   onClick={() => store.removeCreateFile()}>移除</a>
              </span>
            ) : null}
            <Button data-testid="tpl-sample" icon={<DownloadOutlined/>}
                    onClick={() => store.downloadSample()}>
              下载样例
            </Button>
          </Space>
          {errorLine('file')}
        </div>
        <div style={{color: '#999'}}>
          请填齐全部信息后点击「创建并进入模板编辑」统一提交（选择文件不会
          立即上传）；仅支持固定行列、固定填写位置的 .xlsx，公式/图表等
          不支持特性会在创建时明确拒绝。
        </div>
      </Modal>
    );
  }

  /**
   * 预览反馈（2026-10-19）：打印设置抽屉「应用当前设置并预览」的反馈
   * （页数/纸张/参数来源），展示组件随抽屉拆分至 PdfParamsDrawer；
   * 打印预览视图自己的反馈在 TemplateWorkspace 内展示。
   */
  _renderPreviewInfoAlert() {
    return <PreviewInfoAlert info={this.store.previewInfo}/>;
  }

  /** 替换源文件确认弹窗：明确提示清空的绑定数，确认后才上传。 */
  _renderReuploadConfirmModal() {
    const store = this.store;
    const count = store.bindings.length;
    return (
      <Modal title={store.draft ? '替换源文件' : '上传源文件'}
             visible={store.reuploadConfirmVisible}
             confirmLoading={store.uploading}
             okText="确认替换" cancelText="取消"
             okButtonProps={{danger: true}}
             onOk={() => this.store.confirmReupload()}
             onCancel={() => store.cancelReupload()}>
        <p>即将上传新的 .xlsx 文件替换当前草稿：</p>
        <p style={{color: '#fa541c'}}>
          {count > 0
            ? `将清空现有 ${count} 个字段绑定，需要重新绑定。`
            : '当前暂无字段绑定，替换后需重新绑定。'}
          已配置的打印设置将恢复默认。
        </p>
        <p style={{color: '#999'}}>已发布的历史版本不受影响。</p>
      </Modal>
    );
  }

  /** 工作区「更多操作」菜单：版本记录/打印设置/替换源文件（低频收进菜单）。 */
  _renderWorkspaceMoreMenu(deleted, draft) {
    const store = this.store;
    return (
      <Menu onClick={({key}) => {
        if (key === 'pdf-params') store.openPdfDrawer();
        if (key === 'versions') this.showVersions();
      }}>
        <Menu.Item key="versions" data-testid="tpl-versions-menu"
                   icon={<HistoryOutlined/>}>版本记录</Menu.Item>
        <Menu.Item key="pdf-params" data-testid="tpl-pdf-params"
                   icon={<PrinterOutlined/>} disabled={!draft || deleted}>
          打印设置
        </Menu.Item>
        <Menu.Item key="reupload" data-testid="tpl-reupload-menu" disabled={deleted}>
          <Upload accept=".xlsx" showUploadList={false} beforeUpload={this.pickReuploadFile}>
            <span data-testid="tpl-reupload" style={{display: 'inline-block'}}>
              {draft ? '替换源文件' : '上传源文件'}
            </span>
          </Upload>
        </Menu.Item>
      </Menu>
    );
  }

  /** 工作区操作区：主按钮「发布版本」+ 更多操作菜单（预览为独立视图）。 */
  _renderWorkspaceActions(deleted, blockReason) {
    const store = this.store;
    return (
      <div className="excel-workspace-actions">
        <Popconfirm title="发布后版本与源文件不可修改，确认发布当前草稿？"
                    onConfirm={this.handlePublish} okText="发布" cancelText="取消">
          <Button data-testid="tpl-publish" type="primary" loading={store.publishing}
                  disabled={!!blockReason}>
            发布版本
          </Button>
        </Popconfirm>
        <Dropdown overlay={this._renderWorkspaceMoreMenu(deleted, store.draft)}
                  trigger={['click']}>
          <Button data-testid="tpl-more-actions">
            更多操作 <DownOutlined/>
          </Button>
        </Dropdown>
      </div>
    );
  }

  /**
   * 绑定工作区（2026-10-21 统一观感）：头部/信息行/发布原因在页面层，
   * 「字段绑定 / 打印预览」双视图主体在 TemplateWorkspaceBody（与台账
   * 填写界面共用纸张展示层）；替换源文件/生成配置弹窗保持页面层挂载。
   */
  _renderWorkspace() {
    const store = this.store;
    const draft = store.draft;
    // 已停用模板仅供查看：禁用替换/发布/打印设置入口，选格编辑一并冻结
    const deleted = !store.current.is_active;
    const blockReason = this.publishBlockReason();
    // 草稿状态（2026-10-21）：后端按内容签名判定与发布版本的关系，
    // 无法可靠判断时前端原样展示"无法确认"，不做任何时间推断
    const draftState = store.current.draft_state || {};
    return (
      <div className="excel-template-workspace">
        <div className="excel-workspace-header">
          <div className="excel-workspace-heading">
            <Button data-testid="tpl-back" icon={<ArrowLeftOutlined/>}
                    onClick={() => store.applyDetail(null)}>返回模板列表</Button>
            <strong>{store.current.name}</strong>
            <Tag>{LEDGER_TYPE_TEXT[store.current.ledger_type] || store.current.ledger_type}</Tag>
            <Tag color={deleted ? 'red' : (store.current.latest_version_no ? 'blue' : 'default')}
                 data-testid={deleted ? 'tpl-deleted-tag' : 'tpl-status-tag'}>
              {deleted ? '已停用，仅供查看'
                : `${(TEMPLATE_STATUS[store.current.status] || TEMPLATE_STATUS.draft).text} · v${store.current.latest_version_no || 0}`}
            </Tag>
          </div>
          {this._renderWorkspaceActions(deleted, blockReason)}
        </div>
        {blockReason && (
          <div data-testid="tpl-publish-reason" className="excel-workspace-publish-reason">
            {blockReason}，暂不能发布
          </div>
        )}
        <div className="excel-workspace-meta">
          <span data-testid="tpl-editing-mode">当前编辑：草稿</span>
          <span data-testid="tpl-draft-updated">
            草稿更新：{draftState.updated_at || '—'}
            {draftState.updated_by ? ` · ${draftState.updated_by}` : ''}
          </span>
          <span data-testid="tpl-draft-relation">{draftRelationText(draftState)}</span>
          <span data-testid="tpl-source-file">
            源文件：{draft ? draft.source_filename : '未上传'}
          </span>
          <span data-testid="tpl-binding-count">绑定字段：{store.bindings.length} 个</span>
          <span data-testid="tpl-version-line">
            最新发布版本：v{store.current.latest_version_no || 0}
            （共 {store.current.versions_count || 0} 个）
          </span>
          <span data-testid="tpl-generation-config-line">
            适用系统：{store.current.system
              ? `${store.current.system_name}（${store.current.system_code}）`
              : '待配置'}　
            生成周期：{store.current.generation_period_text || '待配置'}
            {!deleted && (
              <a data-testid="tpl-config" style={{marginLeft: 8}}
                 onClick={() => store.openConfigModal().catch(() => {})}>
                配置
              </a>
            )}
          </span>
        </div>
        <Spin spinning={store.loading || store.uploading}
              tip={store.uploading ? `上传解析中 ${store.uploadProgress}%` : '加载中...'}>
          {this._renderPreviewInfoAlert()}
          {draft && draft.layout ? (
            <TemplateWorkspaceBody store={store} deleted={deleted}/>
          ) : (
            <Empty description="当前模板没有草稿源文件，请通过「更多操作 → 上传源文件」上传 .xlsx"
                   style={{padding: 60}}/>
          )}
        </Spin>
        {this._renderReuploadConfirmModal()}
        {this._renderConfigModal()}
      </div>
    );
  }

  /**
   * 生成配置弹窗（2026-10-14；2026-10-21 支持行级补全）：适用系统
   * （一模板一系统）+ 生成周期（按台账类型收敛：周月维护=每周/每月，
   * 季维护=每航季）。空值显式清空回"待配置"，不做任何自动推断。
   */
  _renderConfigModal() {
    const store = this.store;
    if (!store.configTemplateId) return null;
    const fromWorkspace = store.current
      && store.current.id === store.configTemplateId;
    return (
      <Modal title={fromWorkspace || !store.configTemplateName
        ? '生成配置（本期应填台账）'
        : `生成配置：${store.configTemplateName}（本期应填台账）`}
             visible={store.configVisible}
             confirmLoading={store.configSaving}
             okText="保存" cancelText="取消"
             onOk={() => store.saveGenerationConfig().catch(() => {})}
             onCancel={() => store.closeConfigModal()}>
        <Alert
          type="info" showIcon style={{marginBottom: 16}}
          message="配置后可在周月/季维护台账列表一键生成本期应填台账"
          description="生成的台账固定引用最新发布版本并可直接填写。历史模板不自动推断配置。"/>
        <div style={{marginBottom: 4}}>适用系统（一个模板只对应一个系统）</div>
        <Select data-testid="tpl-config-system" showSearch optionFilterProp="children"
                placeholder="请选择适用系统" style={{width: '100%', marginBottom: 12}}
                allowClear
                value={store.configSystem}
                onChange={value => store.setConfigField('configSystem', value)}>
          {store.configSystems.map(s => (
            <Select.Option key={s.id} value={s.id}>
              {`${s.name}（${s.system_code}）${s.is_active ? '' : ' [已停用]'}`}
            </Select.Option>
          ))}
        </Select>
        <div style={{marginBottom: 4}}>生成周期</div>
        <Select data-testid="tpl-config-period" placeholder="请选择生成周期"
                style={{width: '100%'}} allowClear
                value={store.configPeriod || undefined}
                onChange={value => store.setConfigField('configPeriod', value || '')}>
          {store.configPeriodOptions.map(p => (
            <Select.Option key={p.value} value={p.value}>{p.label}</Select.Option>
          ))}
        </Select>
        <div style={{color: '#999', marginTop: 8}}>
          清空两项即回到"待配置"，该模板不再参与自动生成（不影响手工创建）。
        </div>
      </Modal>
    );
  }

  /**
   * 行操作可见性（2026-10-16 停用/删除拆分；2026-10-19 双视图+重新启用）：
   * - 补全配置：在用且缺适用系统或生成周期的模板（2026-10-21 待配置
   *   列表直接补全，不自动推断）；
   * - 停用：启用中的模板（del 权限）；重新启用：已停用模板（del 权限）；
   * - 删除：无任何台账引用的模板；被引用的模板只能停用（后端删除时
   *   仍会重新检查）。
   */
  _renderRowActions(record) {
    const openText = !record.is_active ? '查看模板'
      : (record.draft_source_filename ? '编辑草稿' : '上传源文件');
    const canStop = record.is_active && hasPermission(PERM_L.TPL_DEL);
    const canActivate = !record.is_active && hasPermission(PERM_L.TPL_DEL);
    const canDestroy = hasPermission(PERM_L.TPL_DEL) && !record.ledgers_count;
    const needsConfig = record.is_active
      && (!record.system || !record.generation_period);
    const menu = (
      <Menu onClick={({key}) => {
        if (key === 'versions') this.showRowVersions(record);
        if (key === 'stop') this.confirmStopTemplate(record);
        if (key === 'activate') this.confirmActivateTemplate(record);
        if (key === 'destroy') this.confirmDestroyTemplate(record);
      }}>
        <Menu.Item key="versions" data-testid="tpl-row-versions"
                   icon={<HistoryOutlined/>}>版本记录</Menu.Item>
        {canStop && (
          <Menu.Item key="stop" data-testid="tpl-stop" danger
                     icon={<StopOutlined/>}>停用模板</Menu.Item>
        )}
        {canActivate && (
          <Menu.Item key="activate" data-testid="tpl-activate"
                     icon={<CheckCircleOutlined/>}>重新启用</Menu.Item>
        )}
        {canDestroy && (
          <Menu.Item key="destroy" data-testid="tpl-destroy" danger
                     icon={<DeleteOutlined/>}>删除模板</Menu.Item>
        )}
      </Menu>
    );
    return (
      <Space size={4}>
        <Button type="link" size="small" data-testid="tpl-open"
                onClick={() => this.store.fetchDetail(record.id).catch(() => {})}>
          {openText}
        </Button>
        {needsConfig && (
          <Button type="link" size="small" data-testid="tpl-row-config"
                  onClick={() => this.store.openConfigModal(record).catch(() => {})}>
            补全配置
          </Button>
        )}
        <Dropdown overlay={menu} trigger={['click']}>
          <Button type="link" size="small" data-testid="tpl-more">
            更多 <DownOutlined/>
          </Button>
        </Dropdown>
      </Space>
    );
  }

  /** 列表过滤栏（2026-10-19 双视图）：视图切换（含准确数量）+ 关键词 + 维护类型。 */
  _renderListFilters() {
    const store = this.store;
    return (
      <Space style={{marginBottom: 12}} wrap>
        <Radio.Group data-testid="tpl-view-switch" value={store.listView}
                     onChange={event => store.setListView(event.target.value)}>
          <Radio.Button value="active">在用（{store.activeCount}）</Radio.Button>
          <Radio.Button value="disabled">已停用（{store.disabledCount}）</Radio.Button>
        </Radio.Group>
        <Input.Search data-testid="tpl-search" allowClear
                      placeholder="搜索名称 / 说明 / 适用系统" style={{width: 240}}
                      value={store.listKeyword}
                      onChange={event => store.setListFilter('listKeyword', event.target.value)}/>
        <Select data-testid="tpl-type-filter" allowClear placeholder="维护类型"
                style={{width: 140}} value={store.listType || undefined}
                onChange={value => store.setListFilter('listType', value || '')}>
          <Select.Option value="week_month">周月维护</Select.Option>
          <Select.Option value="seasonal">季维护</Select.Option>
        </Select>
      </Space>
    );
  }

  _renderList() {
    const store = this.store;
    const columns = [
      {title: '模板名称', dataIndex: 'name'},
      {title: '维护类型', dataIndex: 'ledger_type',
       render: value => LEDGER_TYPE_TEXT[value] || value},
      {title: '适用系统', key: 'system', width: 180, ellipsis: true,
       render: (v, record) => systemColumn(record)},
      {title: '生成周期', dataIndex: 'generation_period_text', width: 90,
       render: (v, record) => v || <Tag>待配置</Tag>},
      {title: '说明', dataIndex: 'description', ellipsis: true},
      {title: '草稿源文件', dataIndex: 'draft_source_filename',
       render: (value, record) => value ? (
         <span>
           {value}
           {record.draft_updated_at ? (
             <span style={{color: '#999'}}>（{record.draft_updated_at}）</span>
           ) : null}
         </span>
       ) : <Tag>未上传</Tag>},
      {title: '版本', dataIndex: 'latest_version_no',
       render: (value, record) => `v${value || 0} / 共 ${record.versions_count || 0} 个`},
      {title: '关联台账', dataIndex: 'ledgers_count', width: 90,
       render: value => (value ? `${value} 个` : '—')},
      {title: '状态', dataIndex: 'status',
       render: value => {
         const conf = TEMPLATE_STATUS[value] || {text: value || '—'};
         return <Tag color={conf.color}>{conf.text}</Tag>;
       }},
      {title: '操作', key: 'actions', render: (_, record) => this._renderRowActions(record)},
    ];
    const rows = store.listView === 'disabled'
      ? store.disabledTemplates : store.activeTemplates;
    // 分页当前页不越界（停用/删除重取后行数变少时收敛到最后一页）
    const current = Math.min(store.listPage,
      Math.max(1, Math.ceil(rows.length / LIST_PAGE_SIZE)));
    return (
      <Card bordered={false}
            title="Excel 维护台账模板（WPS/Excel 上传）"
            extra={hasPermission(PERM_L.TPL_ADD) ? (
              <Button data-testid="tpl-create" type="primary" icon={<UploadOutlined/>}
                      onClick={() => store.openCreateModal()}>
                新建模板
              </Button>
            ) : null}>
        {this._renderListFilters()}
        <Table rowKey="id" columns={columns} dataSource={rows}
               loading={store.loading}
               pagination={{
                 current, pageSize: LIST_PAGE_SIZE, total: rows.length,
                 showTotal: total => `共 ${total} 条`,
                 onChange: page => store.setListFilter('listPage', page),
               }}/>
        <div style={{color: '#999', marginTop: 8}}>
          仅支持固定行列、固定填写位置的 .xlsx；公式、图表、图片、外部链接、
          透视表与宏会在创建时被明确拒绝，不会静默丢失。新建模板时即配置
          适用系统与生成周期；历史待配置模板在行内「补全配置」补齐，
          不做自动推断。已停用模板在「已停用」视图中集中管理，可重新启用
          （恢复新台账使用与自动生成）。
          在「周月/季维护台账」列表点击<a
            onClick={() => history.push('/el/week-month-ledgers')}
            style={{margin: '0 4px'}}>生成本期应填台账</a>可按模板配置
          （适用系统＋生成周期）批量生成可填写的应填台账，缺配置的模板
          会在预览中标注原因。
          如需手工临时补录，请前往<a
            onClick={() => history.push('/el/week-month-ledgers')}
            style={{marginLeft: 4}}>周月/季维护台账</a>。
        </div>
        {this._renderCreateModal()}
        {this._renderConfigModal()}
      </Card>
    );
  }

  _renderVersionsDrawer() {
    const store = this.store;
    const columns = [
      {title: '版本', dataIndex: 'version_no', render: v => `v${v}`},
      {title: '模板名称快照', dataIndex: 'template_name'},
      {title: '源文件', dataIndex: 'source_filename'},
      {title: 'SHA-256', dataIndex: 'source_hash',
       render: v => <span style={{fontFamily: 'monospace'}}>{String(v).slice(0, 16)}…</span>},
      {title: '字段数', dataIndex: 'field_count'},
      {title: '发布时间', dataIndex: 'published_at'},
      {title: '操作', key: 'view', width: 90,
       render: (_, record) => (
         <a data-testid="tpl-version-view"
            onClick={() => this.handleViewVersion(record)}>查看内容</a>
       )},
    ];
    return (
      <Drawer title={store.versionsOwner
        ? `已发布版本：${store.versionsOwner}` : '已发布版本（不可变）'}
              width={780} visible={store.versionsVisible}
              onClose={() => {
                store.versionsVisible = false;
              }}>
        <div style={{color: '#999', marginBottom: 8}}>
          已发布版本为不可变快照，仅供查看与追溯；如需继续使用某个旧版本，
          请点「查看内容」后选择「复制为新草稿」（不会修改历史版本、不会自动发布）。
        </div>
        <Table rowKey="id" columns={columns} dataSource={store.versions}
               pagination={false} size="small"/>
      </Drawer>
    );
  }

  /** 历史版本只读查看抽屉（复制入口仅在打开同一模板详情时可用）。 */
  _renderVersionViewer() {
    const target = this.state.versionTarget;
    const canCopy = !!(target && target.isActive
      && this.store.current && this.store.current.id === target.id
      && hasPermission(PERM_L.TPL_EDIT));
    return (
      <VersionViewerDrawer store={this.versionStore}
                           templateId={target ? target.id : null}
                           canCopy={canCopy}
                           onCopy={this.handleCopyVersion}/>
    );
  }

  /**
   * 临时预览数据区与预览反馈随打印设置抽屉拆分至 PdfParamsDrawer
   * （2026-10-19，控制主页面文件规模）；此处仅挂载。
   */
  _renderPdfParamsDrawer() {
    return <PdfParamsDrawer store={this.store}/>;
  }

  render() {
    const store = this.store;
    if (!store.current) {
      return (
        <div className="excel-template-page">
          {this._renderList()}
          {this._renderVersionsDrawer()}
          {this._renderVersionViewer()}
        </div>
      );
    }
    return (
      <div className="excel-template-page">
        {this._renderWorkspace()}
        {this._renderVersionsDrawer()}
        {this._renderVersionViewer()}
        {this._renderPdfParamsDrawer()}
      </div>
    );
  }
}

export default ExcelTemplatePage;
