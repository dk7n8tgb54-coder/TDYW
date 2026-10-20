/**
 * Copyright (c) OpenSpug Organization. https://github.com/openspug
 * Released under the AGPL-3.0 License.
 *
 * Excel 上传版维护台账模板页（2026-09-28 试点；2026-10-14 交互改造）。
 *
 * 两种视图：
 * - 列表：唯一主操作「新建模板」——名称/类型/上传集中在弹窗内完成
 *   （下载样例随流程内提供，页面不再重复出现）；行操作按状态显示
 *   「编辑草稿 / 上传源文件 / 查看模板」，版本记录与停用/删除收进行内
 *   「更多」菜单（2026-10-16 拆分：停用=逻辑停用，启用模板可用；
 *   删除=物理删除，无台账引用的模板可用，引用关系后端删除时复查，
 *   del 权限门禁，Modal.confirm 二次确认）；列表展示适用系统与
 *   生成周期（2026-10-14，未配置显示"待配置"，不自动推断）；
 *   在用/已停用双视图（2026-10-19）：默认进入在用视图，已停用模板
 *   集中在已停用视图（可查看内容/版本/关联台账，del 权限可重新启用，
 *   停用成功后立即从在用视图移出）；两视图分别支持关键词搜索
 *   （名称/说明/适用系统）、维护类型筛选与分页，切换视图时数量与
 *   分页结果准确；
 *   页面底部提供前往正式周月/季维护台账的填写入口；
 * - 绑定工作区（2026-10-19 借鉴原生台账编辑工作台布局）：顶部集中展示
 *   返回入口、名称/类型/状态与全部操作，发布禁用原因在操作区下方独立
 *   一行说明；信息行展示源文件、绑定字段数、当前版本与生成配置（适用
 *   系统/生成周期，2026-10-14，未停用模板提供「配置」入口）；主按钮
 *   「发布版本」（无草稿/无绑定/兼容性 error 时禁用，warning 不阻断）+
 *   次级「预览空白打印稿」+「更多操作」菜单（版本记录/打印设置/替换
 *   源文件）；替换源文件选定文件后先弹确认（提示将清空的绑定数与打印
 *   参数重置），确认后才上传，取消不请求；左侧为字段属性面板与已绑定
 *   字段导航（支持搜索，点击跨工作表定位并选中单元格），右侧为版式
 *   预览；字段名称自动生成（2026-10-19）：新绑定默认「工作表 · 坐标」、
 *   批量每格各生成一个，前缀可选，留空保存回退默认名，已有自定义
 *   名称保持不变；混合批量选区（2026-10-19）：已绑定与未绑定格可同选区
 *   （拖拽可从已绑定格开始），面板显示选中总数/已绑定/未绑定，批量保存
 *   只更新明确修改过的属性并保留已有 field_id 与名称，批量解绑独立确认；
 *   拖拽选区期间表格禁止文字选择，松开/离开窗口/Escape 取消后恢复；
 *   多工作表时提供工作表切换（Tabs，复用 store.setSheet，
 *   切换即清空单格与批量选区）；已停用模板仅供查看，替换/发布/打印设置/
 *   选格编辑与导航定位全部冻结（后端独立校验兜底）；
 *   兼容性检查提示（error=须处理后才能发布，warning=可能有格式差异）；
 *   填写区尺寸提示（2026-10-14）与 PDF 参数抽屉保持不变。
 *
 * 不支持的文件特性（公式/图表/图片/外部链接/透视表）由后端显式拒绝，
 * 错误信息逐项列出（公共拦截器提示，不静默导入）。
 */
import React from 'react';
import {observer} from 'mobx-react';
import {
  Alert, Button, Card, Drawer, Dropdown, Empty, Input, Menu,
  Modal, Popconfirm, Radio, Select, Space, Spin, Table, Tabs, Tag, Upload,
  message,
} from 'antd';
import {
  ArrowLeftOutlined, CheckCircleOutlined, DeleteOutlined, DownOutlined,
  DownloadOutlined, FilePdfOutlined, HistoryOutlined, PrinterOutlined,
  StopOutlined, UploadOutlined,
} from '@ant-design/icons';
import {hasPermission, history} from 'libs';

import excelTemplateStore, {LIST_PAGE_SIZE} from './excelTemplateStore';
import PdfParamsDrawer, {PreviewInfoAlert} from './PdfParamsDrawer';
import {PERM_L} from '../constants';
import LayoutTable, {bindBlockReason} from './components/LayoutTable';
import FieldPanel from './components/FieldPanel';
import BatchBindingPanel from './BatchBindingPanel';
import {tightMergedTextBindings} from './utils';
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

function BindingNavigator({bindings, onSelect, disabled}) {
  const [query, setQuery] = React.useState('');
  const matches = bindings.filter(binding =>
    `${binding.field_name} ${binding.sheet_name} ${binding.cell_coordinate}`
      .toLowerCase().includes(query.trim().toLowerCase()));
  return (
    <section className="excel-workspace-section">
      <div className="excel-workspace-section-title">
        <strong>已绑定字段</strong><Tag>{bindings.length}</Tag>
      </div>
      <Input.Search data-testid="tpl-binding-search" aria-label="搜索字段或单元格"
                    placeholder="搜索字段或单元格"
                    value={query} onChange={event => setQuery(event.target.value)}/>
      <div className="excel-workspace-binding-list">
        {matches.length ? matches.map(binding => (
          <button type="button" key={binding.field_id}
                  data-testid="tpl-binding-item"
                  className="excel-workspace-binding-row" disabled={disabled}
                  onClick={() => onSelect(binding)}>
            <span className="excel-workspace-binding-name">{binding.field_name}</span>
            <span className="excel-workspace-binding-location">
              {binding.sheet_name} · {binding.cell_coordinate}
              {binding.is_required ? ' · 必填' : ''}
            </span>
          </button>
        )) : <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description={query ? '没有匹配字段' : '暂无绑定字段'}/>}
      </div>
    </section>
  );
}

@observer
class ExcelTemplatePage extends React.Component {
  get store() {
    return this.props.store || excelTemplateStore;
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

  /** 新建模板流程（弹窗内）：守卫 → 上传 → 成功后关弹窗进入绑定工作区。 */
  handleUpload = file => {
    if (!/\.xlsx$/i.test(file.name)) {
      message.error('仅支持 .xlsx 文件（暂不支持 .xls 与 WPS 私有格式）');
      return false;
    }
    const store = this.store;
    if (!store.uploadName || !store.uploadType) {
      message.warning('请先填写模板名称并选择维护类型');
      return false;
    }
    store.upload({name: store.uploadName, ledger_type: store.uploadType}, file)
      .then(() => {
        store.closeCreateModal();
        message.success('模板解析成功，请绑定可填写单元格');
      })
      .catch(() => {});
    return false;
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

  showVersions = () => {
    this.store.showVersionsFor(this.store.current).catch(() => {});
  };

  /** 列表行「版本记录」：按行取数打开抽屉，不改动当前模板详情。 */
  showRowVersions = record => {
    this.store.showVersionsFor(record).catch(() => {});
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
   * 新建模板弹窗（列表页唯一主操作流程）：名称/类型/上传集中一处，
   * 下载样例只在此流程出现；上传成功后关闭弹窗并进入绑定工作区。
   */
  _renderCreateModal() {
    const store = this.store;
    return (
      <Modal title="新建 Excel 台账模板" visible={store.createVisible}
             width={520} footer={null}
             onCancel={() => store.closeCreateModal()}>
        <div style={{marginBottom: 12}}>
          <div style={{marginBottom: 4}}>模板名称</div>
          <Input data-testid="tpl-name" placeholder="如：信道维护记录表" maxLength={100}
                 value={store.uploadName}
                 onChange={e => store.setUploadField('uploadName', e.target.value)}/>
        </div>
        <div style={{marginBottom: 16}}>
          <div style={{marginBottom: 4}}>维护类型</div>
          <Select data-testid="tpl-type" placeholder="请选择维护类型" style={{width: '100%'}}
                  value={store.uploadType}
                  onChange={value => store.setUploadField('uploadType', value)}>
            <Select.Option value="week_month">周月维护</Select.Option>
            <Select.Option value="seasonal">季维护</Select.Option>
          </Select>
        </div>
        <Space wrap>
          <Upload accept=".xlsx" showUploadList={false} beforeUpload={this.handleUpload}>
            <Button data-testid="tpl-upload" type="primary" icon={<UploadOutlined/>}
                    loading={store.uploading}>
              上传 .xlsx 模板
            </Button>
          </Upload>
          <Button data-testid="tpl-sample" icon={<DownloadOutlined/>}
                  onClick={() => store.downloadSample()}>
            下载样例
          </Button>
        </Space>
        <div style={{color: '#999', marginTop: 8}}>
          请先填写名称并选择维护类型，再上传 .xlsx 源文件；解析成功后进入绑定工作区。
        </div>
      </Modal>
    );
  }

  /** 草稿兼容性检查提示（error=须处理后才能发布；warning=可能有格式差异）。 */
  _renderCompatibilityAlert() {
    const compat = this.store.compatibility;
    if (!compat || compat.status === 'ok') return null;
    const messages = [
      ...(compat.warnings || []),
      ...(compat.unsupported && compat.unsupported.length
        ? [`包含平台暂不支持的特性：${compat.unsupported.join('、')}，请处理后重新上传源文件`]
        : []),
    ];
    if (!messages.length) return null;
    return (
      <Alert data-testid="tpl-compat" showIcon style={{marginBottom: 12}}
             type={compat.status === 'error' ? 'error' : 'warning'}
             message={compat.status === 'error'
               ? '模板草稿存在问题，处理后才能发布'
               : '模板可能存在格式差异'}
             description={messages.join('；')}/>
    );
  }

  /**
   * 填写区尺寸提示（2026-10-14）：横向合并多列不会增加填写高度，只有
   * 一行默认高度的合并文本填写格在网页上填写区域较小；提示在 Excel/WPS
   * 中设置行高后重传。只提示不改模板、不阻断发布。
   */
  _renderSizeHintAlert() {
    const store = this.store;
    const sheet = store.currentSheet;
    if (!sheet) return null;
    const tight = tightMergedTextBindings(sheet, store.bindings);
    if (!tight.length) return null;
    const rowText = coord => coord.replace(/[A-Z]/g, '');
    return (
      <Alert data-testid="tpl-size-hints" showIcon type="info" style={{marginBottom: 12}}
             message="部分填写格只有一行高度，网页填写区域较小"
             description={(
               <div>
                 {tight.map(item => (
                   <div key={item.coordinate}>
                     「{item.field_name}」（{item.coordinate}）位于单行高的合并区域：
                     横向合并多列不会增加填写高度。如需更大的填写区域，请在 Excel/WPS
                     中选中第 {rowText(item.coordinate)} 行，右键选择「行高」设置更大的值
                     （如 40 磅以上），然后重新上传源文件并重新绑定（重传会清空现有绑定）。
                   </div>
                 ))}
               </div>
             )}/>
    );
  }

  /** 多工作表切换（复用 store.setSheet：切换即清空单格与批量选区）。 */
  _renderSheetTabs() {
    const store = this.store;
    const layout = store.layout;
    if (!layout || !layout.sheets || layout.sheets.length < 2) return null;
    const sheet = store.currentSheet;
    return (
      <Tabs data-testid="tpl-sheet-tabs" size="small" style={{marginBottom: 8}}
            activeKey={sheet ? sheet.name : undefined}
            onChange={name => store.setSheet(name)}>
        {layout.sheets.map(item => <Tabs.TabPane tab={item.name} key={item.name}/>)}
      </Tabs>
    );
  }

  /**
   * 预览反馈（2026-10-19）：页数/纸张来自后端真实生成的 PDF，提示为按
   * 本次实际参数的版式预检结果；参数来源标注已保存参数或当前未保存
   * 参数。展示组件随打印设置抽屉拆分至 PdfParamsDrawer（控制主页面
   * 文件规模），工作区与抽屉共用同一份 store 状态。
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

  /** 工作区操作区：唯一主按钮「发布版本」+ 次级预览 + 更多操作菜单。 */
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
        <Button data-testid="tpl-pdf-preview" icon={<FilePdfOutlined/>}
                disabled={!store.draft} loading={store.previewing}
                onClick={() => store.previewPdf().catch(() => {})}>
          预览空白打印稿（已保存参数）
        </Button>
        <Dropdown overlay={this._renderWorkspaceMoreMenu(deleted, store.draft)}
                  trigger={['click']}>
          <Button data-testid="tpl-more-actions">
            更多操作 <DownOutlined/>
          </Button>
        </Dropdown>
      </div>
    );
  }

  _selectBinding = binding => {
    const store = this.store;
    if (!store.current.is_active) return;
    if (store.activeSheet !== binding.sheet_name) store.setSheet(binding.sheet_name);
    store.clearSelection();
    if (store.selectedCell !== binding.cell_coordinate) store.selectCell(binding.cell_coordinate);
    setTimeout(() => {
      const sheet = this.workspaceSheetRef;
      const cell = sheet && sheet.querySelector(`[data-coord="${binding.cell_coordinate}"]`);
      if (cell && cell.scrollIntoView) cell.scrollIntoView({block: 'nearest', inline: 'nearest'});
    }, 0);
  };

  /** 右侧版式预览区：工作表切换 + 布局表格（拖拽选区/文字选择控制在此）。 */
  _renderSheetPane(deleted) {
    const store = this.store;
    return (
      <div className="excel-workspace-sheet" ref={node => { this.workspaceSheetRef = node; }}>
        {this._renderSheetTabs()}
        <LayoutTable
          sheet={store.currentSheet}
          bindingByCell={store.bindingByCell}
          fillMode={false}
          selectedCell={store.selectedCell}
          selectedCells={store.selectedCells}
          preventTextSelect={store.isDragging}
          onSelectCell={(coord, event) => {
            if (deleted) return;
            store.handleCellClick(coord, event);
          }}
          onCellMouseDown={(coord, event) => {
            if (deleted) return;
            store.beginDrag(coord, event);
            // 拖拽从可填写格（含已绑定）开始时阻断浏览器文字选择，
            // 只作用于模板编辑表格的 mousedown，不影响其他区域
            if (store.isDragging && event
                && typeof event.preventDefault === 'function') {
              event.preventDefault();
            }
          }}
          onCellMouseEnter={coord => store.extendDrag(coord)}/>
      </div>
    );
  }

  _renderWorkspace() {
    const store = this.store;
    const sheet = store.currentSheet;
    const draft = store.draft;
    // 已停用模板仅供查看：禁用替换/发布/打印设置入口，选格编辑一并冻结
    const deleted = !store.current.is_active;
    const blockReason = this.publishBlockReason();
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
          <span data-testid="tpl-source-file">
            源文件：{draft ? draft.source_filename : '未上传'}
          </span>
          <span data-testid="tpl-binding-count">绑定字段：{store.bindings.length} 个</span>
          <span data-testid="tpl-version-line">
            当前版本：v{store.current.latest_version_no || 0}（共 {store.current.versions_count || 0} 个）
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
          {this._renderCompatibilityAlert()}
          {this._renderSizeHintAlert()}
          {draft && draft.layout ? (
            <div className="excel-workspace-body">
              <aside className="excel-workspace-sidebar">
                <section className="excel-workspace-section">
                  <div className="excel-workspace-section-title">
                    <strong>{store.selectedCells.length ? '批量绑定' : '字段绑定'}</strong>
                    <Tag color="blue">{store.selectedCells.length
                      ? `已选 ${store.selectedCells.length} 格` : (store.selectedCell || '未选择')}</Tag>
                  </div>
                  {store.selectedCells.length > 0 ? (
                    <BatchBindingPanel selectedCells={store.selectedCells}
                                       sheetName={store.activeSheet}
                                       bindingByCell={store.bindingByCell}
                                       saving={store.saving}
                                       onSave={form => store.saveBatchBinding(form)}
                                       onUnbind={() => store.saveBatchUnbind()}
                                       onClear={() => store.clearSelection()}/>
                  ) : (
                    <FieldPanel
                      key={`${store.activeSheet}!${store.selectedCell}!${store.selectedBinding ? store.selectedBinding.field_id : 'none'}`}
                      coord={store.selectedCell}
                      binding={store.selectedBinding}
                      sheetName={store.activeSheet}
                      blockReason={store.selectedCell && !store.selectedBinding
                        ? bindBlockReason(sheet, store.selectedCell) : null}
                      saving={store.saving}
                      onSave={form => store.saveBinding(form)}
                      onRemove={() => store.selectedBinding
                        && store.removeBinding(store.selectedBinding.field_id)}/>
                  )}
                </section>
                <BindingNavigator bindings={store.bindings}
                                  disabled={deleted} onSelect={this._selectBinding}/>
              </aside>
              {this._renderSheetPane(deleted)}
            </div>
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
   * 生成配置弹窗（2026-10-14）：适用系统（一模板一系统）+ 生成周期
   * （按台账类型收敛：周月维护=每周/每月，季维护=每航季）。空值显式
   * 清空回"待配置"，不做任何自动推断。
   */
  _renderConfigModal() {
    const store = this.store;
    if (!store.current) return null;
    return (
      <Modal title="生成配置（本期应填台账）"
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
   * - 停用：启用中的模板（del 权限）——停用后移入已停用视图，不可用于新台账；
   * - 重新启用：已停用模板（del 权限）——恢复新台账使用与自动生成参与资格；
   * - 删除：无任何台账引用的模板（未发布或已发布无引用，含已停用无引用）；
   *   被引用的模板只能停用（后端删除时仍会重新检查）。
   */
  _renderRowActions(record) {
    const openText = !record.is_active ? '查看模板'
      : (record.draft_source_filename ? '编辑草稿' : '上传源文件');
    const canStop = record.is_active && hasPermission(PERM_L.TPL_DEL);
    const canActivate = !record.is_active && hasPermission(PERM_L.TPL_DEL);
    const canDestroy = hasPermission(PERM_L.TPL_DEL) && !record.ledgers_count;
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
          透视表与宏会在上传时被明确拒绝，不会静默丢失。已停用模板在
          「已停用」视图中集中管理，可重新启用（恢复新台账使用与自动生成）。
          在「周月/季维护台账」列表点击<a
            onClick={() => history.push('/el/week-month-ledgers')}
            style={{margin: '0 4px'}}>生成本期应填台账</a>可按模板配置
          （适用系统＋生成周期）批量生成可填写的应填台账；历史模板未配置的
          显示"待配置"，请在本页行内进入配置，不做自动推断。
          如需手工临时补录，请前往<a
            onClick={() => history.push('/el/week-month-ledgers')}
            style={{marginLeft: 4}}>周月/季维护台账</a>。
        </div>
        {this._renderCreateModal()}
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
    ];
    return (
      <Drawer title={store.versionsOwner
        ? `已发布版本：${store.versionsOwner}` : '已发布版本（不可变）'}
              width={720} visible={store.versionsVisible}
              onClose={() => {
                store.versionsVisible = false;
              }}>
        <Table rowKey="id" columns={columns} dataSource={store.versions}
               pagination={false} size="small"/>
      </Drawer>
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
        </div>
      );
    }
    return (
      <div className="excel-template-page">
        {this._renderWorkspace()}
        {this._renderVersionsDrawer()}
        {this._renderPdfParamsDrawer()}
      </div>
    );
  }
}

export default ExcelTemplatePage;
