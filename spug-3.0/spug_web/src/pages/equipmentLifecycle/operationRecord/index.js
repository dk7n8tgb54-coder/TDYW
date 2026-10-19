/**
 * Copyright (c) OpenSpug Organization. https://github.com/openspug/spug
 * Released under the AGPL-3.0 License.
 */
/**
 * 设备全生命周期——运行处置记录中心页（2026-10-11 合并改造）。
 * 合并原"故障处置"与"运行记录"两个菜单为统一入口"运行处置记录"：
 * 一张统一主表承载 一般记录/异常事件/设备故障 三类记录。
 * 页签：全部记录 / 待办（跟进中+处置中故障）/ 统计（只读）。
 * 筛选（2026-10-14 体验二轮）：关键词/所属系统/状态为高频条件常驻，
 * 记录类型/异常类别/发生时间收入"更多筛选"；筛选、查询、重置、分页
 * 状态保持一致（任一变更即重置页码）。导出与当前筛选完全一致（后端
 * 同一筛选口径，截止时间包含所选整分钟）。
 * 列表（2026-10-14 体验二轮）：标题置首可直接打开详情（前置类型标签），
 * 编号可一键复制；故障影响程度并入状态列；登记人/持续时间收敛到详情，
 * 减少横向滚动。加载失败显式提示并可重试，不把旧结果冒充新查询结果。
 * 跨页跳转：?detail=<ID> 直达详情（系统档案页签、台账来源跳转入口）；
 * ?system=<系统ID> 预设所属系统筛选（系统档案页签"查看该系统全部记录"
 * 跳入，2026-10-15）。列表展示单元（状态/故障影响标签、标题、编号复制）
 * 与系统档案页签共用 shared.js 实现，避免两处复制展示规则。
 * 导出与查询口径（2026-10-15）：关键词输入为草稿（input_keyword），查询
 * 按钮/回车提交后才成为已执行条件（f_keyword）；导出参数与"导出范围"
 * 文案一律使用已执行条件，保证与表格所见一致（输入未查询/查询后/重置后/
 * 翻页均成立）。
 */
import React, {useEffect, useState} from 'react';
import {observer} from 'mobx-react';
import {Input, Select, Button, Table, DatePicker, Tabs, Alert} from 'antd';
import {PlusOutlined, DownOutlined, UpOutlined} from '@ant-design/icons';
import {SearchForm, AuthDiv, AuthButton, Breadcrumb, ExportButton} from 'components';
import RecordForm from './RecordForm';
import RecordDetail from './RecordDetail';
import RecordTodo from './RecordTodo';
import RecordStatistics from './RecordStatistics';
import store from './store';
import {
  RecordStatusTag, FaultImpactTag, RecordTitleCell, RecordNoCell,
  RecordAttachmentCountCell,
} from './shared';
import {
  PERM, RECORD_STATUS_OPTIONS,
  RECORD_CATEGORY_OPTIONS, RECORD_TYPE_OPTIONS,
  API_PREFIX,
} from '../constants';

const {RangePicker} = DatePicker;
const {TabPane} = Tabs;

@observer
class RecordTable extends React.Component {
  componentDidMount() {
    // 系统档案页签"查看该系统全部记录"跳入（?system=<ID>）：先应用系统
    // 筛选并回到第 1 页再首次取数，首屏即为本系统视图（不先拉全量再过滤）
    if (this.props.initialSystem) {
      store.f_system = this.props.initialSystem;
      store.page = 1;
    }
    store.fetchSystems();
    store.fetchRecords();
  }

  // 列序（2026-10-14 体验二轮）：标题置首可直接打开详情（前置类型标签）；
  // 编号紧跟其后可一键复制（引用字段可查找、可复制，不挡在扫描列前）；
  // 设备故障影响程度并入状态列；登记人/持续时间收敛到详情展示，
  // 降低横向滚动宽度（1380 → 1140）。
  // 展示单元（2026-10-15）与系统档案页签共用 shared.js 同一实现
  columns = [{
    title: '标题',
    dataIndex: 'title',
    width: 250,
    ellipsis: true,
    render: (text, record) => (
      <RecordTitleCell record={record} onOpen={r => store.showDetail(r)}/>
    ),
  }, {
    title: '所属系统',
    dataIndex: 'system_name',
    width: 150,
    ellipsis: true,
  }, {
    title: '编号',
    dataIndex: 'record_no',
    width: 170,
    render: (text) => <RecordNoCell value={text}/>,
  }, {
    title: '状态',
    dataIndex: 'status',
    width: 130,
    render: (text, record) => (
      <span>
        <RecordStatusTag status={text}/>
        <FaultImpactTag record={record}/>
      </span>
    ),
  }, {
    title: '发生时间',
    dataIndex: 'occurred_at',
    width: 140,
  }, {
    // 最近更新：全部进展中处理时间最新的进展时间（后端按处理时间聚合最大值，
    // 非进展创建时间/ID 口径，不取主记录 updated_at）；无进展显示"-"
    title: '最近更新',
    dataIndex: 'latest_progress_at',
    width: 150,
    render: (text) => text || '-',
  }, {
    // 进展数：后端列表聚合统计（progress_count，只读）；
    // 点击数量打开详情并定位到进展时间线区块（2026-10-18 详情页签改分区）
    title: '进展数',
    dataIndex: 'progress_count',
    width: 80,
    render: (text, record) => (
      <a onClick={() => store.showDetail(record, 'progress')}>
        {record.progress_count ?? 0} 条
      </a>
    ),
  }, {
    title: '附件',
    dataIndex: 'attachment_count',
    width: 70,
    align: 'center',
    render: (count, record) => (
      <RecordAttachmentCountCell record={record} onOpen={store.showDetail}/>
    ),
  }, {
    title: '操作',
    width: 100,
    fixed: 'right',
    render: (text, record) => (
      <span>
        <AuthButton
          auth={PERM.OP_VIEW}
          type="link"
          size="small"
          style={{padding: 0}}
          onClick={() => store.showDetail(record)}
        >
          详情
        </AuthButton>
        {/* 一般记录恒可编辑；异常事件三状态可编辑；设备故障仅处置中可编辑
            （终态只读，后端同样拒绝；编辑按钮权限差异由详情页内收敛） */}
        {record.status !== 'closed' && record.status !== 'cancelled' && (
          <AuthButton
            auth={PERM.OP_EDIT}
            type="link"
            size="small"
            style={{padding: 0, marginLeft: 8}}
            onClick={() => store.showForm(record)}
          >
            编辑
          </AuthButton>
        )}
      </span>
    ),
  }];

  render() {
    return (
      <div>
        {/* 加载失败显式提示并保留旧数据供参考，提供重试入口（错误 toast
            已由 http 拦截器弹出，此处不重复弹出） */}
        {store.fetchError && (
          <Alert
            type="warning"
            showIcon
            message="列表加载失败，以下可能为上次查询结果"
            action={
              <Button size="small" onClick={() => store.fetchRecords()}>重试</Button>
            }
            style={{marginBottom: 12}}
          />
        )}
        <Table
          rowKey="id"
          loading={store.isFetching}
          scroll={{x: 1210}}
          pagination={{
            current: store.page,
            pageSize: store.pageSize,
            total: store.total,
            showSizeChanger: true,
            onChange: (page, pageSize) => {
              store.page = page;
              store.pageSize = pageSize;
              store.fetchRecords();
            },
            showTotal: total => `共 ${total} 条`,
          }}
          dataSource={store.records}
          columns={this.columns}
          locale={{emptyText: (
            <div style={{padding: '24px 0'}}>
              <div>{store.fetchError ? '列表加载失败' : '暂无记录'}</div>
              {!store.fetchError && (
                <div style={{color: 'rgba(0, 0, 0, 0.45)', fontSize: 12, marginTop: 4}}>
                  点击上方"新增记录"登记一般记录、异常事件或设备故障
                </div>
              )}
            </div>
          )}}
        />
      </div>
    );
  }
}

// 筛选区（2026-10-14 体验二轮分层）：关键词/所属系统/状态为高频条件常驻，
// 记录类型/异常类别/发生时间收入"更多筛选"（折叠时显示活跃条件数）。
// 任一筛选变更即重置页码并刷新，查询/重置与筛选条件、分页状态保持一致
const RecordFilters = observer(function RecordFilters() {
  const [advancedOpen, setAdvancedOpen] = useState(false);
  const advancedCount = [
    store.f_record_type,
    store.f_category,
    store.f_occurred_range && store.f_occurred_range.length === 2,
  ].filter(Boolean).length;
  return (
    <SearchForm>
      <SearchForm.Item span={7} title="关键词">
        {/* 输入只写草稿（不触发查询）：查询按钮/回车提交后才成为已执行条件 */}
        <Input
          allowClear
          value={store.input_keyword}
          onChange={e => store.setKeywordInput(e.target.value)}
          placeholder="编号/标题/描述/系统名称"
          onPressEnter={() => store.commitKeyword()}
        />
      </SearchForm.Item>
      <SearchForm.Item span={7} title="所属系统">
        <Select
          allowClear
          showSearch
          optionFilterProp="children"
          style={{width: '100%'}}
          value={store.f_system}
          onChange={v => {store.f_system = v; store.page = 1; store.fetchRecords();}}
          placeholder="请选择系统"
        >
          {store.systems.map(s => (
            <Select.Option value={s.id} key={s.id}>
              {s.name}
            </Select.Option>
          ))}
        </Select>
      </SearchForm.Item>
      <SearchForm.Item span={4} title="状态">
        <Select
          allowClear
          style={{width: '100%'}}
          value={store.f_status}
          onChange={v => {store.f_status = v; store.page = 1; store.fetchRecords();}}
          placeholder="默认不含已撤销"
        >
          {RECORD_STATUS_OPTIONS.map(item => (
            <Select.Option value={item.value} key={item.value}>{item.label}</Select.Option>
          ))}
        </Select>
      </SearchForm.Item>
      <SearchForm.Item span={6}>
        {/* 查询/回车提交关键词草稿并刷新；其余筛选变更即刷新但不代提交草稿 */}
        <Button type="primary" onClick={() => store.commitKeyword()}>查询</Button>
        <Button style={{marginLeft: 8}} onClick={() => {store.resetFilter(); store.fetchRecords();}}>
          重置
        </Button>
        <a
          style={{marginLeft: 16, lineHeight: '32px', userSelect: 'none'}}
          onClick={() => setAdvancedOpen(!advancedOpen)}
        >
          {advancedOpen ? '收起筛选' : '更多筛选'}
          {!advancedOpen && advancedCount > 0 && `（${advancedCount}）`}
          {advancedOpen ? <UpOutlined style={{marginLeft: 4}}/> : <DownOutlined style={{marginLeft: 4}}/>}
        </a>
      </SearchForm.Item>
      {advancedOpen && (
        <React.Fragment>
          <SearchForm.Item span={4} title="记录类型">
            <Select
              allowClear
              style={{width: '100%'}}
              value={store.f_record_type}
              onChange={v => {store.f_record_type = v; store.page = 1; store.fetchRecords();}}
              placeholder="请选择"
            >
              {RECORD_TYPE_OPTIONS.map(item => (
                <Select.Option value={item.value} key={item.value}>{item.label}</Select.Option>
              ))}
            </Select>
          </SearchForm.Item>
          <SearchForm.Item span={4} title="异常类别">
            <Select
              allowClear
              style={{width: '100%'}}
              value={store.f_category}
              onChange={v => {store.f_category = v; store.page = 1; store.fetchRecords();}}
              placeholder="请选择"
            >
              {RECORD_CATEGORY_OPTIONS.map(item => (
                <Select.Option value={item.value} key={item.value}>{item.label}</Select.Option>
              ))}
            </Select>
          </SearchForm.Item>
          <SearchForm.Item span={8} title="发生时间">
            <RangePicker
              showTime={{format: 'HH:mm'}}
              format="YYYY-MM-DD HH:mm"
              style={{width: '100%'}}
              value={store.f_occurred_range}
              onChange={v => {store.f_occurred_range = v; store.page = 1; store.fetchRecords();}}
              placeholder={['发生时间起', '发生时间止']}
            />
          </SearchForm.Item>
        </React.Fragment>
      )}
    </SearchForm>
  );
});

// 操作区：新增记录 + 导出。导出请求携带与列表"已执行"完全一致的筛选参数
// （关键词草稿不参与；后端导出接口同一筛选口径），导出范围在按钮旁按
// 已执行条件逐项说明
const ActionBar = observer(function ActionBar() {
  return (
    <div style={{marginBottom: 12}}>
      {/* 一般记录/异常事件用"新增记录"；直接登记设备故障须单独授权
          （add_fault），两种入口统一走同一表单按类型校验 */}
      <AuthButton
        auth={PERM.OP_ADD}
        type="primary"
        icon={<PlusOutlined/>}
        onClick={() => store.showForm()}
      >
        新增记录
      </AuthButton>
      <ExportButton
        auth={PERM.OP_EXPORT}
        style={{marginLeft: 8}}
        url={`${API_PREFIX}/records/export/`}
        params={store.getExportParams()}
        filename="运行处置记录.xlsx"
      >
        导出
      </ExportButton>
      <span style={{marginLeft: 8, color: 'rgba(0, 0, 0, 0.45)', fontSize: 12}}>
        {store.exportScopeText}
      </span>
    </div>
  );
});

// 页签切换即取最新数据：操作（完成跟进/认定故障/结案等）后返回待办或统计
// 时看到最新结果；首次挂载的初始请求由各自组件发起，这里不重复
function handleTabChange(key) {
  if (key === 'todo') {
    store.fetchTodoRecords();
  } else if (key === 'statistics') {
    store.fetchStatistics();
  }
}

function RecordIndex(props) {
  // 跨页跳转参数（渲染期解析一次，供首次取数前生效）：
  // ?detail=<记录ID> 直达详情（系统档案页签、台账来源跳转入口）；
  // ?system=<系统ID> 预设"所属系统"筛选（系统档案页签"查看该系统全部
  // 记录"跳入），由 RecordTable 挂载时在首次请求前应用
  const search = props.location ? props.location.search : '';
  const initialSystem = React.useMemo(() => {
    const params = new URLSearchParams(search);
    const value = params.get('system');
    return value && /^\d+$/.test(value) ? parseInt(value, 10) : undefined;
    // 仅按挂载时的初始 URL 解析，后续导航不重复应用
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);
  useEffect(() => {
    const params = new URLSearchParams(search);
    const detailId = params.get('detail');
    if (detailId && /^\d+$/.test(detailId)) {
      store.showDetail(parseInt(detailId, 10));
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);
  return (
    <AuthDiv auth={PERM.OP_VIEW}>
      <Breadcrumb>
        <Breadcrumb.Item>首页</Breadcrumb.Item>
        <Breadcrumb.Item>设备管理</Breadcrumb.Item>
        <Breadcrumb.Item>运行处置记录</Breadcrumb.Item>
      </Breadcrumb>
      <Tabs defaultActiveKey="records" onChange={handleTabChange}>
        <TabPane tab="全部记录" key="records">
          <RecordFilters/>
          <ActionBar/>
          <RecordTable initialSystem={initialSystem}/>
        </TabPane>
        <TabPane tab="待办（跟进中+处置中）" key="todo">
          <RecordTodo/>
        </TabPane>
        <TabPane tab="统计" key="statistics">
          <RecordStatistics/>
        </TabPane>
      </Tabs>
      {store.formVisible && <RecordForm/>}
      {store.detailVisible && <RecordDetail/>}
    </AuthDiv>
  );
}

export default observer(RecordIndex);
