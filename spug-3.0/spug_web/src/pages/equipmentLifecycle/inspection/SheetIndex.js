/**
 * Copyright (c) OpenSpug Organization. https://github.com/openspug
 * Released under the AGPL-3.0 License.
 */
/**
 * 设备全生命周期——巡检单记录查询（今日巡检改造）。
 * 浏览全部值班巡检单（按值班日范围/状态/编号筛选），详情只读展示
 * 值班人员与四轮检查内容回显；历史已转故障/已转工单的处置状态只读展示
 * （转单功能已下线，故障/工单在对应模块创建）。
 * 列表页三个导出（列表 Excel/批量 Excel/批量 PDF）先弹日期范围选择框，
 * 确认后才下载；详情抽屉单条导出保持直接下载。
 * 超级管理员（is_supper）可对"已提交"巡检单执行"退回整改"：仅超管显示
 * 按钮，后端独立校验身份；退回原因必填，成功后刷新详情与列表。
 */
import React, {useState} from 'react';
import {observer} from 'mobx-react';
import {
  Button, DatePicker, Descriptions, Drawer, Form, Input, message, Modal, Select, Spin, Tag,
} from 'antd';
import {ExportOutlined} from '@ant-design/icons';
import {AuthButton, AuthDiv, Breadcrumb, ExportButton, SearchForm} from 'components';
import {exportFile, http} from 'libs';
import store, {defaultDutyRange} from './store';
import DutyRangeExportModal from './DutyRangeExportModal';
import {API_PREFIX, PERM_I, ROUND_TEXT, SHEET_STATUS_COLOR, SHEET_STATUS_TEXT} from './constants';
import {withProjectSpans} from './tableUtils';

const DISPOSITION_TEXT = {
  none: '未处置',
  converted_fault: '已转故障',
  converted_work_order: '已转工单',
  target_cancelled: '目标已作废',
};

// 超级管理员判断：与项目现有方式一致（登录时写入 sessionStorage.is_supper）；
// 后端对退回接口独立校验 request.user.is_supper，前端仅控制按钮显隐
function checkIsSupper() {
  return sessionStorage.getItem('is_supper') === 'true';
}

function buildBrowseParams() {
  const params = {
    page: store.browsePage,
    page_size: store.browsePageSize,
  };
  if (store.f_duty_range && store.f_duty_range.length === 2) {
    params.duty_from = store.f_duty_range[0].format('YYYY-MM-DD');
    params.duty_to = store.f_duty_range[1].format('YYYY-MM-DD');
  }
  if (store.f_status) params.status = store.f_status;
  if (store.f_keyword) params.keyword = store.f_keyword;
  return params;
}

// 导出参数 = 当前筛选条件（不含分页参数，后端导出筛选范围内全部数据）
function buildExportParams() {
  const {page, page_size, ...filters} = buildBrowseParams();
  return filters;
}

// 列表页三个导出入口（端点 + 默认文件名）；确认日期后经 exportFile 下载
const LIST_EXPORT_KINDS = {
  list: {url: `${API_PREFIX}/inspection-sheets/export/`, filename: '巡检单记录.xlsx'},
  batch_xlsx: {url: `${API_PREFIX}/inspection-sheets/batch-export/xlsx/`, filename: '巡检单详情批量.xlsx'},
  batch_pdf: {url: `${API_PREFIX}/inspection-sheets/batch-export/pdf/`, filename: '巡检单详情批量.pdf'},
};

@observer
class SheetTable extends React.Component {
  componentDidMount() {
    store.fetchBrowse(buildBrowseParams());
  }

  render() {
    return (
      <table className="el-ins-recap-table" style={{width: '100%'}}>
        <thead>
        <tr>
          <th style={{width: 110}}>值班日</th>
          <th style={{width: 160}}>单号</th>
          <th style={{width: 160}}>模板</th>
          <th style={{width: 90}}>状态</th>
          <th style={{width: 80}}>异常数</th>
          <th style={{width: 150}}>提交时间</th>
          <th style={{width: 100}}>提交人</th>
          <th style={{width: 80}}>操作</th>
        </tr>
        </thead>
        <tbody>
        {store.browseRecords.map(record => (
          <tr key={record.id}>
            <td>{record.duty_date}</td>
            <td>{record.sheet_no}</td>
            <td>{record.template_name}</td>
            <td>
              <Tag color={SHEET_STATUS_COLOR[record.status]}>
                {SHEET_STATUS_TEXT[record.status] || record.status}
              </Tag>
            </td>
            <td>
              {record.abnormal_count > 0
                ? <span style={{color: 'red', fontWeight: 'bold'}}>{record.abnormal_count}</span>
                : record.abnormal_count}
            </td>
            <td>{record.submitted_at || '-'}</td>
            <td>{record.submitted_by_name || '-'}</td>
            <td>
              <AuthButton
                auth={PERM_I.VIEW}
                type="link"
                size="small"
                style={{padding: 0}}
                onClick={() => store.openBrowseDetail(record.id)}
              >
                详情
              </AuthButton>
            </td>
          </tr>
        ))}
        {!store.browseRecords.length && !store.isBrowseFetching && (
          <tr>
            <td colSpan={8} style={{color: '#999', textAlign: 'center', padding: 16}}>
              暂无巡检单记录
            </td>
          </tr>
        )}
        </tbody>
      </table>
    );
  }
}

/**
 * 超级管理员退回整改弹窗：退回原因必填（≤200 字，与后端限制一致）。
 * 成功提示以后端真实成功为准（HTTP 200 + error 由拦截器提示并 reject，
 * 不会走到 then）；成功后刷新详情与列表并关闭弹窗，失败恢复按钮状态。
 */
function ReturnSheetModal({visible, sheet, onClose}) {
  const [form] = Form.useForm();
  const [submitting, setSubmitting] = useState(false);

  // 关闭弹窗重置表单，下次打开为干净状态
  React.useEffect(() => {
    if (!visible) form.resetFields();
  }, [visible]);

  function handleOk() {
    form.validateFields().then(values => {
      if (submitting) return;
      setSubmitting(true);
      store.returnSheet(sheet.id, (values.return_reason || '').trim()).then(() => {
        message.success('巡检单已退回整改');
        // 刷新详情与列表（详情保持抽屉打开，状态实时更新为已退回）
        store.fetchSheet(sheet.id);
        store.fetchBrowse(buildBrowseParams());
        onClose();
      }).catch(() => {
        // 错误提示统一由 http 拦截器弹出，此处不重复提示
      }).finally(() => setSubmitting(false));
    }).catch(() => {});   // 表单校验失败：由 Form.Item 展示错误
  }

  return (
    <Modal
      title="退回整改"
      visible={visible}
      confirmLoading={submitting}
      onOk={handleOk}
      onCancel={() => {
        if (!submitting) onClose();
      }}
      okText="确认退回"
      cancelText="取消">
      <p style={{color: '#999', marginTop: 0}}>
        巡检单 {sheet ? sheet.sheet_no : ''} 将变为「已退回」，值班人员可整改后重新提交；
        已有巡检记录与故障/工单来源关系保留不变。
      </p>
      <Form form={form} layout="vertical">
        <Form.Item
          name="return_reason"
          label="退回原因"
          rules={[
            {required: true, whitespace: true, message: '退回原因不能为空'},
            {max: 200, message: '退回原因不能超过 200 字'},
          ]}>
          <Input.TextArea
            rows={4}
            maxLength={200}
            placeholder="请填写退回原因（必填，最多 200 字）"/>
        </Form.Item>
      </Form>
    </Modal>
  );
}

const SheetDetailDrawer = observer(function SheetDetailDrawer() {
  const d = store.detail;
  const [returnVisible, setReturnVisible] = useState(false);
  const rounds = ['r1', 'r2', 'r3', 'r4'];
  // 一行 = 检查项目（设备名称快照）× 检查内容，四轮取值横向展开；
  // 临时加项的设备名可能为空，检查项目归为"临时检查项"
  const itemMap = {};
  (d ? d.records : []).forEach(r => {
    const key = r.template_item ? `t_${r.template_item}` : `m_${r.client_key || r.id}`;
    const item = itemMap[key] || (itemMap[key] = {
      key,
      project: r.device_name || '临时检查项',
      content: r.item_name,
      displayOrder: r.display_order || 0,
      rounds: {},
    });
    item.rounds[r.round_no] = r;
  });
  const items = Object.values(itemMap).sort((a, b) => {
    if (a.project !== b.project) return a.project < b.project ? -1 : 1;
    if (a.displayOrder !== b.displayOrder) return a.displayOrder - b.displayOrder;
    return a.key < b.key ? -1 : a.key > b.key ? 1 : 0;
  });
  // 同一检查项目的连续行合并第一列单元格
  const rows = withProjectSpans(items);
  function cell(record) {
    if (!record) return <span style={{color: '#ddd'}}>—</span>;
    const color = record.result === 'abnormal' ? 'red' : 'inherit';
    const disp = record.disposition && record.disposition.status !== 'none'
      ? <Tag style={{marginLeft: 4}}>{DISPOSITION_TEXT[record.disposition.status]}</Tag>
      : null;
    return (
      <span>
        <span style={{color}}>
          {record.value_text || '—'}
          {record.onsite_action ? `（${record.onsite_action}）` : ''}
        </span>
        {disp}
      </span>
    );
  }
  return (
    <Drawer
      title={d ? `巡检单详情 - ${d.sheet_no}` : '巡检单详情'}
      visible={store.browseVisible}
      width={960}
      onClose={() => store.closeBrowseDetail()}
      destroyOnClose
      extra={d ? (
        <div>
          <ExportButton
            auth={PERM_I.EXPORT}
            url={`${API_PREFIX}/inspection-sheets/${d.id}/export/xlsx/`}
            filename={`巡检单_${d.sheet_no}.xlsx`}>
            导出 Excel
          </ExportButton>
          <ExportButton
            auth={PERM_I.EXPORT}
            style={{marginLeft: 8}}
            url={`${API_PREFIX}/inspection-sheets/${d.id}/export/pdf/`}
            filename={`巡检单_${d.sheet_no}.pdf`}>
            导出 PDF
          </ExportButton>
          {/* 退回整改：仅超级管理员 + 已提交状态可见（草稿/已退回/已作废不显示） */}
          {checkIsSupper() && d.status === 'submitted' && (
            <Button
              style={{marginLeft: 8}}
              onClick={() => setReturnVisible(true)}>
              退回整改
            </Button>
          )}
        </div>
      ) : null}
    >
      <Spin spinning={store.isDetailFetching}>
        {d && (
          <div>
            <Descriptions bordered size="small" column={2}>
              <Descriptions.Item label="单号">{d.sheet_no}</Descriptions.Item>
              <Descriptions.Item label="状态">
                <Tag color={SHEET_STATUS_COLOR[d.status]}>{SHEET_STATUS_TEXT[d.status]}</Tag>
              </Descriptions.Item>
              <Descriptions.Item label="值班日">{d.duty_date}</Descriptions.Item>
              <Descriptions.Item label="巡检模板">{d.template_name}</Descriptions.Item>
              <Descriptions.Item label="值班人员" span={2}>
                {d.persons && d.persons.length
                  ? d.persons.map(p => p.person_name).join('、') : '（未登记）'}
              </Descriptions.Item>
              <Descriptions.Item label="提交时间">
                {d.submitted_at || '-'}
                {d.submitted_by_name ? `（${d.submitted_by_name}）` : ''}
              </Descriptions.Item>
              <Descriptions.Item label="异常数">{d.abnormal_count}</Descriptions.Item>
              {d.status === 'void' && (
                <Descriptions.Item label="作废原因" span={2}>
                  {d.void_reason || '-'}
                  {d.voided_at ? `（${d.voided_at} ${d.voided_by_name || ''}）` : ''}
                </Descriptions.Item>
              )}
              {d.status === 'returned' && (
                <Descriptions.Item label="退回原因" span={2}>
                  {d.return_reason || '-'}
                  {d.returned_at ? `（${d.returned_at} ${d.returned_by_name || ''}）` : ''}
                </Descriptions.Item>
              )}
            </Descriptions>
            <div style={{marginTop: 12}}>
              <table className="el-ins-recap-table" style={{width: '100%'}}>
                <thead>
                <tr>
                  <th>检查项目</th>
                  <th>检查内容</th>
                  {rounds.map(r => <th key={r}>{ROUND_TEXT[r]}</th>)}
                </tr>
                </thead>
                <tbody>
                {rows.map(({item, isGroupStart, span}) => (
                  <tr key={item.key}>
                    {isGroupStart ? <td rowSpan={span}>{item.project}</td> : null}
                    <td>{item.content}</td>
                    {rounds.map(r => (
                      <td key={r}>{cell(item.rounds[r])}</td>
                    ))}
                  </tr>
                ))}
                </tbody>
              </table>
            </div>
          </div>
        )}
      </Spin>
      <ReturnSheetModal
        visible={returnVisible}
        sheet={d}
        onClose={() => setReturnVisible(false)}/>
    </Drawer>
  );
});

@observer
class SheetIndex extends React.Component {
  // 导出日期弹窗为局部状态：日期值是 store 筛选的副本，不回写列表筛选条件；
  // exportCount 为弹窗日期范围内的可导出条数（列表接口 total，仅作提示，
  // 最终能否导出由后端在确认时统一校验）
  state = {
    exportModalVisible: false,
    exportKind: 'list',    // LIST_EXPORT_KINDS 的键
    exportRange: [],       // 弹窗内日期范围 [moment, moment]
    exporting: false,
    exportCount: null,
    exportCountLoading: false,
  };

  // 连续变更日期时只应用最后一次统计结果
  exportCountSeq = 0;

  componentDidMount() {
    // 来源跳转直达详情（故障详情/工单详情/系统履历跳入：?detail=<巡检单ID>）
    const params = new URLSearchParams(this.props.location ? this.props.location.search : '');
    const detailId = params.get('detail');
    if (detailId && /^\d+$/.test(detailId)) {
      store.openBrowseDetail(parseInt(detailId, 10));
    }
  }

  openExportModal = (kind) => {
    // 默认值 = 当前列表筛选日期范围的副本；无有效范围时回退最近 30 个自然日
    const range = store.f_duty_range && store.f_duty_range.length === 2
      ? store.f_duty_range.slice()
      : defaultDutyRange();
    this.setState({exportKind: kind, exportRange: range, exportModalVisible: true});
    this.fetchExportCount(range);
  };

  handleExportRangeChange = (range) => {
    this.setState({exportRange: range});
    this.fetchExportCount(range);
  };

  // 按弹窗日期范围 + 当前列表筛选统计可导出条数（page_size=1 只取 total）
  fetchExportCount = (range) => {
    if (!range || range.length !== 2 || !range[0] || !range[1]) {
      this.exportCountSeq += 1;
      this.setState({exportCount: null, exportCountLoading: false});
      return;
    }
    const seq = ++this.exportCountSeq;
    const params = {
      ...buildExportParams(),
      duty_from: range[0].format('YYYY-MM-DD'),
      duty_to: range[1].format('YYYY-MM-DD'),
      page: 1,
      page_size: 1,
    };
    this.setState({exportCountLoading: true});
    http.get(`${API_PREFIX}/inspection-sheets/`, {params})
      .then(res => {
        if (seq !== this.exportCountSeq) return;
        this.setState({exportCount: res.total, exportCountLoading: false});
      })
      .catch(() => {
        if (seq !== this.exportCountSeq) return;
        this.setState({exportCount: null, exportCountLoading: false});
      });
  };

  handleExportCancel = () => {
    // 导出进行中不关闭弹窗，防止重复提交
    if (this.state.exporting) return;
    this.setState({exportModalVisible: false});
  };

  handleExportConfirm = async (range) => {
    if (this.state.exporting) return;
    const config = LIST_EXPORT_KINDS[this.state.exportKind] || LIST_EXPORT_KINDS.list;
    // 弹窗确认的日期覆盖 duty_from/duty_to，其余沿用当前列表筛选（不含分页参数）
    const params = {
      ...buildExportParams(),
      duty_from: range[0].format('YYYY-MM-DD'),
      duty_to: range[1].format('YYYY-MM-DD'),
    };
    this.setState({exporting: true});
    try {
      await exportFile({url: config.url, params, defaultFilename: config.filename});
    } catch (e) {
      // 导出失败提示由 http 拦截器/exportFile 兜底负责，这里仅吞掉拒绝避免未处理异常
    } finally {
      this.setState({exporting: false, exportModalVisible: false});
    }
  };

  render() {
    return (
      <AuthDiv>
        {/* embedded：被巡检中心页签嵌入时隐藏本页完整面包屑（由外壳统一显示） */}
        {!this.props.embedded && (
          <Breadcrumb>
            <Breadcrumb.Item>设备全生命周期管理</Breadcrumb.Item>
            <Breadcrumb.Item>巡检与维护</Breadcrumb.Item>
            <Breadcrumb.Item>巡检单记录</Breadcrumb.Item>
          </Breadcrumb>
        )}
        <SearchForm>
          <SearchForm.Item>
            <DatePicker.RangePicker
              value={store.f_duty_range}
              onChange={v => {store.f_duty_range = v || [];}}
              format="YYYY-MM-DD"
              placeholder={['值班日起', '值班日止']}
            />
          </SearchForm.Item>
          <SearchForm.Item>
            <Select
              allowClear
              style={{width: 140}}
              placeholder="状态"
              value={store.f_status}
              onChange={v => {store.f_status = v;}}
            >
              <Select.Option value="draft">草稿</Select.Option>
              <Select.Option value="submitted">已提交</Select.Option>
              <Select.Option value="returned">已退回</Select.Option>
              <Select.Option value="void">已作废</Select.Option>
            </Select>
          </SearchForm.Item>
          <SearchForm.Item>
            <Input
              allowClear
              placeholder="单号关键字"
              value={store.f_keyword}
              onChange={e => {store.f_keyword = e.target.value;}}
              onKeyPress={e => {
                if (e.key === 'Enter') {
                  store.browsePage = 1;
                  store.fetchBrowse(buildBrowseParams());
                }
              }}
            />
          </SearchForm.Item>
        </SearchForm>
        <div style={{marginBottom: 12}}>
          <Button
            type="primary"
            onClick={() => {
              store.browsePage = 1;
              store.fetchBrowse(buildBrowseParams());
            }}
          >
            查询
          </Button>
          {/* 三个列表导出均先选日期范围再下载；批量按钮不再依赖当前列表
              total 禁用——用户可为空列表重新选范围，无数据由后端统一提示 */}
          <AuthButton
            auth={PERM_I.EXPORT}
            icon={<ExportOutlined/>}
            style={{marginLeft: 8}}
            onClick={() => this.openExportModal('list')}>
            导出 Excel
          </AuthButton>
          <AuthButton
            auth={PERM_I.EXPORT}
            icon={<ExportOutlined/>}
            style={{marginLeft: 8}}
            onClick={() => this.openExportModal('batch_xlsx')}>
            {`批量导出 Excel（共 ${store.browseTotal} 条）`}
          </AuthButton>
          <AuthButton
            auth={PERM_I.EXPORT}
            icon={<ExportOutlined/>}
            style={{marginLeft: 8}}
            onClick={() => this.openExportModal('batch_pdf')}>
            {`批量导出 PDF（共 ${store.browseTotal} 条）`}
          </AuthButton>
        </div>
        <SheetTable/>
        <div style={{marginTop: 12, color: '#999'}}>
          共 {store.browseTotal} 条（第 {store.browsePage} 页）
        </div>
        <SheetDetailDrawer/>
        <DutyRangeExportModal
          visible={this.state.exportModalVisible}
          value={this.state.exportRange}
          exporting={this.state.exporting}
          count={this.state.exportCount}
          countLoading={this.state.exportCountLoading}
          onChange={this.handleExportRangeChange}
          onCancel={this.handleExportCancel}
          onConfirm={this.handleExportConfirm}
        />
      </AuthDiv>
    );
  }
}

export default SheetIndex;
