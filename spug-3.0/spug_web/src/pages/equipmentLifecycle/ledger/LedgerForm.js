/**
 * Copyright (c) OpenSpug Organization. https://github.com/openspug
 * Released under the AGPL-3.0 License.
 */
/**
 * 运维台账录入/编辑表单（步骤 3.2）：
 * - 通过模板生成（可多系统多模板）或临时直接新建；
 * - 明细按系统分组表格录入，一张台账一次提交全部系统明细；
 * - 数值项按正常范围自动建议结果，改判须填写修正原因；
 * - 正常项支持批量确认，异常项要求填写异常说明。
 * 提交成功后重新获取后端真实数据，不做乐观更新。
 */
import React from 'react';
import {observer} from 'mobx-react';
import {
  Modal, Form, Input, InputNumber, Select, DatePicker, Button, Table, Collapse,
  Checkbox, Tag, Tooltip, Space, Divider, message,
} from 'antd';
import {PlusOutlined, DeleteOutlined} from '@ant-design/icons';
import {http} from 'libs';
import {
  API_PREFIX_L, CYCLE_TEXT, LEDGER_TYPE, LEDGER_TYPE_TEXT, PERM_L,
  RESULT_COLOR, RESULT_TEXT,
} from './constants';
import {getLedgerStore} from './store';

const {Panel} = Collapse;
const {Option} = Select;

let CLIENT_SEQ = 0;
function newClientKey() {
  CLIENT_SEQ += 1;
  return `k${Date.now()}_${CLIENT_SEQ}`;
}

function autoJudge(row) {
  if (row.input_type !== 'number') return null;
  if (row.value_number === null || row.value_number === undefined) return null;
  if (row.number_min === null && row.number_max === null) return null;
  if (row.number_min !== null && row.value_number < row.number_min) return 'abnormal';
  if (row.number_max !== null && row.value_number > row.number_max) return 'abnormal';
  return 'normal';
}

const VALUE_DEFAULTS = {
  text: '', number: null, choice: '', multi_choice: [], boolean: null, attachment: '',
};

function makeRow(base) {
  return Object.assign({
    client_key: newClientKey(),
    id: undefined,
    system_id: undefined,
    template_item_id: undefined,
    inspection_point_id: undefined,
    location: '',
    item_name: '',
    standard: '',
    input_type: 'text',
    unit: '',
    normal_range: '',
    choices: [],
    number_min: null,
    number_max: null,
    is_required: false,
    value_text: '',
    value_number: null,
    value_bool: null,
    result: '',
    correction_reason: '',
    abnormal_desc: '',
    na_reason: '',
    onsite_action: '',
    executor_name: '',
    executed_at: null,
    is_temporary: false,
  }, base || {});
}

@observer
class LedgerForm extends React.Component {
  state = {
    loading: false,
    createdFrom: 'template',
    systems: [],
    templateEntries: [],       // [{system_id, template_id}]
    templateOptions: {},       // system_id -> [template]
    pointsMap: {},             // system_id -> [point]
    rows: [],
    cycle: undefined,
    header: {
      executed_date: null,
      executed_start: null,
      executed_end: null,
      shift: '',
      location_scope: '',
      executor_names: '',
      collaborator_names: '',
      summary: '',
      entry_note: '',
    },
    version: undefined,
  };

  componentDidMount() {
    const record = this.props.store.record || {};
    http.get(`${API_PREFIX_L}/systems/`, {params: {page: 1, page_size: 999}})
      .then(res => {
        this.setState({systems: res.data});
      })
      .catch(() => {});
    if (record.id) {
      // 编辑草稿：从后端获取最新数据回填
      this.setState({loading: true});
      http.get(`${API_PREFIX_L}/ledgers/${record.id}/`)
        .then(res => {
          const rows = (res.items || []).map(item => makeRow({
            id: item.id,
            system_id: item.system,
            template_item_id: item.template_item,
            inspection_point_id: item.inspection_point,
            location: item.location || '',
            item_name: item.item_name,
            standard: item.standard || '',
            input_type: item.input_type,
            unit: item.unit || '',
            normal_range: item.normal_range || '',
            choices: item.choices || [],
            number_min: item.number_min,
            number_max: item.number_max,
            is_required: item.is_required,
            value_text: item.value_text || '',
            value_number: item.value_number,
            value_bool: item.value_bool,
            result: item.result,
            correction_reason: item.correction_reason || '',
            abnormal_desc: item.abnormal_desc || '',
            na_reason: item.na_reason || '',
            onsite_action: item.onsite_action || '',
            executor_name: item.executor_name || '',
            is_temporary: item.is_temporary,
          }));
          this.setState({
            rows,
            version: res.version,
            createdFrom: res.created_from === 'manual' ? 'manual' : this.state.createdFrom,
            cycle: res.maintenance_cycle || undefined,
            header: {
              executed_date: res.executed_date,
              executed_start: res.executed_start,
              executed_end: res.executed_end,
              shift: res.shift || '',
              location_scope: res.location_scope || '',
              executor_names: res.executor_names || '',
              collaborator_names: res.collaborator_names || '',
              summary: res.summary || '',
              entry_note: res.entry_note || '',
            },
          });
        })
        .finally(() => this.setState({loading: false}));
    }
  }

  get isWeekMonth() {
    return this.props.store.ledgerType === LEDGER_TYPE.WEEK_MONTH;
  }

  setHeader = (key, value) => {
    this.setState(prev => ({header: {...prev.header, [key]: value}}));
  };

  setRow = (clientKey, patch) => {
    this.setState(prev => ({
      rows: prev.rows.map(r => (r.client_key === clientKey ? {...r, ...patch} : r)),
    }));
  };

  addTemplateEntry = () => {
    this.setState(prev => ({
      templateEntries: [...prev.templateEntries, {system_id: undefined, template_id: undefined}],
    }));
  };

  setTemplateEntry = (index, patch) => {
    this.setState(prev => ({
      templateEntries: prev.templateEntries.map((t, i) => (i === index ? {...t, ...patch} : t)),
    }));
  };

  removeTemplateEntry = (index) => {
    this.setState(prev => ({templateEntries: prev.templateEntries.filter((t, i) => i !== index)}));
  };

  fetchTemplates = (systemId) => {
    const {store} = this.props;
    let url = `${API_PREFIX_L}/ledger-templates/available/?ledger_type=${store.ledgerType}`;
    if (this.isWeekMonth && this.state.cycle) url += `&maintenance_cycle=${this.state.cycle}`;
    if (systemId) url += `&system=${systemId}`;
    return http.get(url).then(res => res.data).catch(() => []);
  };

  loadPoints = (systemId) => {
    if (!systemId || this.state.pointsMap[systemId]) return;
    http.get(`${API_PREFIX_L}/inspection-points/`, {params: {system: systemId, is_active: 'true'}})
      .then(res => {
        this.setState(prev => ({pointsMap: {...prev.pointsMap, [systemId]: res.data}}));
      })
      .catch(() => {});
  };

  generatePreview = () => {
    const {templateEntries, cycle} = this.state;
    const {store} = this.props;
    const entries = templateEntries.filter(t => t.system_id && t.template_id);
    if (!entries.length) {
      message.error('请先选择系统和模板');
      return;
    }
    this.setState({loading: true});
    http.post(`${API_PREFIX_L}/ledgers/preview/`, {
      ledger_type: store.ledgerType,
      maintenance_cycle: this.isWeekMonth ? (cycle || '') : '',
      entries,
    }).then(res => {
      const rows = [];
      (res.data || []).forEach(entry => {
        (entry.items || []).forEach(item => {
          rows.push(makeRow({
            system_id: entry.system.id,
            template_item_id: item.id,
            inspection_point_id: item.inspection_point,
            location: '',
            item_name: item.name,
            standard: item.standard || '',
            input_type: item.input_type,
            unit: item.unit || '',
            normal_range: item.normal_range || '',
            choices: item.choices || [],
            number_min: item.number_min,
            number_max: item.number_max,
            is_required: item.is_required,
            value_text: item.default_value || '',
            result: '',
          }));
        });
      });
      if (!rows.length) {
        message.warning('所选模板没有与本次周期匹配的项目');
      }
      this.setState({rows});
    }).finally(() => this.setState({loading: false}));
  };

  addManualRow = (systemId) => {
    this.loadPoints(systemId);
    this.setState(prev => ({
      rows: [...prev.rows, makeRow({system_id: systemId, is_temporary: true})],
    }));
  };

  removeRow = (clientKey) => {
    this.setState(prev => ({rows: prev.rows.filter(r => r.client_key !== clientKey)}));
  };

  batchConfirmNormal = (rows) => {
    const candidates = rows.filter(r => {
      if (r.result === 'abnormal') return false;
      if (r.result === 'normal') return false;
      const auto = autoJudge(r);
      return auto !== 'abnormal';
    });
    if (!candidates.length) {
      message.warning('没有可批量确认的明细');
      return;
    }
    this.setState(prev => ({
      rows: prev.rows.map(r => (candidates.some(c => c.client_key === r.client_key) ? {...r, result: 'normal'} : r)),
    }));
  };

  renderValueControl = (row) => {
    const disabled = false;
    switch (row.input_type) {
      case 'number':
        return (
          <InputNumber
            style={{width: '100%'}}
            value={row.value_number}
            onChange={v => this.setRow(row.client_key, {value_number: v})}/>
        );
      case 'choice':
        return (
          <Select
            style={{width: '100%'}} allowClear value={row.value_text || undefined}
            onChange={v => this.setRow(row.client_key, {value_text: v || ''})}>
            {(row.choices || []).map(c => <Option value={c} key={c}>{c}</Option>)}
          </Select>
        );
      case 'multi_choice':
        return (
          <Select
            mode="multiple" style={{width: '100%'}} value={row.value_text ? JSON.parse(row.value_text || '[]') : []}
            onChange={v => this.setRow(row.client_key, {value_text: JSON.stringify(v)})}>
            {(row.choices || []).map(c => <Option value={c} key={c}>{c}</Option>)}
          </Select>
        );
      case 'boolean':
        return (
          <Select
            style={{width: '100%'}} allowClear value={row.value_bool === null || row.value_bool === undefined ? undefined : !!row.value_bool}
            onChange={v => this.setRow(row.client_key, {value_bool: v === undefined ? null : v})}>
            <Option value={true}>是</Option>
            <Option value={false}>否</Option>
          </Select>
        );
      case 'attachment':
        return <Input disabled placeholder="保存台账后通过明细附件上传" value=""/>;
      default:
        return <Input value={row.value_text} onChange={e => this.setRow(row.client_key, {value_text: e.target.value})}/>;
    }
  };

  renderResultControl = (row) => {
    const auto = autoJudge(row);
    return (
      <Space size={4} direction="vertical" style={{width: '100%'}}>
        <Select
          style={{width: '100%'}}
          value={row.result || undefined}
          placeholder="请选择"
          onChange={v => this.setRow(row.client_key, {result: v || ''})}>
          {Object.keys(RESULT_TEXT).map(key => (
            <Option value={key} key={key}>{RESULT_TEXT[key]}</Option>
          ))}
        </Select>
        {auto && row.result && row.result !== auto && (
          <Input
            size="small"
            placeholder={`自动建议为${RESULT_TEXT[auto]}，须填修正原因`}
            value={row.correction_reason}
            onChange={e => this.setRow(row.client_key, {correction_reason: e.target.value})}/>
        )}
      </Space>
    );
  };

  submit = () => {
    const {store} = this.props;
    const {header, rows, createdFrom, cycle, version} = this.state;
    if (!header.executed_date) {
      message.error('请填写实际执行日期');
      return;
    }
    if (this.isWeekMonth && !cycle) {
      message.error('周月维护台账必须选择维护周期（周/月）');
      return;
    }
    if (createdFrom === 'manual' && !(header.entry_note || '').trim()) {
      message.error('临时补录必须填写补录说明');
      return;
    }
    if (!rows.length) {
      message.error('请至少录入一条台账明细');
      return;
    }
    const missingResult = rows.find(r => !r.result);
    if (missingResult) {
      message.error(`明细"${missingResult.item_name}"尚未选择结果`);
      return;
    }
    const missingAbnormal = rows.find(r => r.result === 'abnormal' && !(r.abnormal_desc || '').trim());
    if (missingAbnormal) {
      message.error(`异常明细"${missingAbnormal.item_name}"必须填写异常说明`);
      return;
    }
    // 按系统分组组装 entries
    const groupMap = {};
    for (const r of rows) {
      if (!r.system_id) {
        message.error('每条明细必须选择所属系统');
        return;
      }
      if (!groupMap[r.system_id]) groupMap[r.system_id] = [];
      groupMap[r.system_id].push(r);
    }
    const entries = Object.keys(groupMap).map(systemId => ({
      system_id: Number(systemId),
      items: groupMap[systemId].map(r => ({
        id: r.id,
        template_item_id: r.template_item_id || undefined,
        inspection_point_id: r.inspection_point_id || undefined,
        location: r.location,
        item_name: r.is_temporary || !r.id ? r.item_name : undefined,
        standard: r.is_temporary || !r.id ? r.standard : undefined,
        input_type: r.is_temporary || !r.id ? r.input_type : undefined,
        unit: r.is_temporary || !r.id ? r.unit : undefined,
        normal_range: r.is_temporary || !r.id ? r.normal_range : undefined,
        choices: r.is_temporary || !r.id ? r.choices : undefined,
        number_min: r.is_temporary || !r.id ? r.number_min : undefined,
        number_max: r.is_temporary || !r.id ? r.number_max : undefined,
        value_text: r.value_text,
        value_number: r.value_number,
        value_bool: r.value_bool,
        result: r.result,
        correction_reason: r.correction_reason,
        abnormal_desc: r.abnormal_desc,
        na_reason: r.na_reason,
        onsite_action: r.onsite_action,
        executor_name: r.executor_name,
      })),
    }));
    const payload = {
      ledger_type: store.ledgerType,
      // 巡检固定空周期；周月维护提交所选周期；季维护后端校验固定为 'season'
      maintenance_cycle: this.isWeekMonth
        ? cycle
        : (store.ledgerType === LEDGER_TYPE.SEASONAL ? 'season' : ''),
      created_from: createdFrom,
      entries,
      ...header,
    };
    this.setState({loading: true});
    const request = store.record.id
      ? http.put(`${API_PREFIX_L}/ledgers/${store.record.id}/`, {...payload, version})
      : http.post(`${API_PREFIX_L}/ledgers/`, payload);
    request.then(() => {
      store.formVisible = false;
      store.fetchRecords();
      // 成功提示等待后端真实成功后给出
      message.success('保存成功');
    }).catch(() => {
      // 业务错误提示由 http 拦截器统一弹出；不重复提示、不乐观关闭弹窗
    }).finally(() => this.setState({loading: false}));
  };

  renderHeader = () => {
    const {header, cycle, createdFrom} = this.state;
    const {store} = this.props;
    const isEdit = !!store.record.id;
    return (
      <Form layout="inline" style={{marginBottom: 8}} className="el-ledger-header-form">
        {this.isWeekMonth && (
          <Form.Item required label="维护周期">
            <Select
              style={{width: 100}} value={cycle} disabled={isEdit}
              placeholder="周/月"
              onChange={v => this.setState({cycle: v})}>
              <Option value="week">周</Option>
              <Option value="month">月</Option>
            </Select>
          </Form.Item>
        )}
        <Form.Item required label="实际执行日期">
          <Input
            style={{width: 130}}
            type="date"
            value={header.executed_date || ''}
            onChange={e => this.setHeader('executed_date', e.target.value)}/>
        </Form.Item>
        <Form.Item label="班次">
          <Input style={{width: 100}} value={header.shift} onChange={e => this.setHeader('shift', e.target.value)}/>
        </Form.Item>
        <Form.Item label="机房/区域">
          <Input style={{width: 150}} value={header.location_scope} onChange={e => this.setHeader('location_scope', e.target.value)}/>
        </Form.Item>
        <Form.Item label="执行人">
          <Input style={{width: 150}} value={header.executor_names} onChange={e => this.setHeader('executor_names', e.target.value)}/>
        </Form.Item>
        <Form.Item label="协作人">
          <Input style={{width: 150}} value={header.collaborator_names} onChange={e => this.setHeader('collaborator_names', e.target.value)}/>
        </Form.Item>
        <Form.Item required={createdFrom === 'manual'} label="补录说明">
          <Input style={{width: 200}} value={header.entry_note} onChange={e => this.setHeader('entry_note', e.target.value)}/>
        </Form.Item>
        <Form.Item label="总体说明">
          <Input.TextArea
            style={{width: 300}} rows={1} value={header.summary}
            onChange={e => this.setHeader('summary', e.target.value)}/>
        </Form.Item>
      </Form>
    );
  };

  renderTemplateSection = () => {
    const {templateEntries, systems, templateOptions} = this.state;
    const {store} = this.props;
    if (store.record.id) return null;
    return (
      <div style={{marginBottom: 12}}>
        <Divider orientation="left" style={{fontSize: 13, margin: '12px 0 8px'}}>通过模板生成</Divider>
        {templateEntries.map((entry, index) => (
          <Space key={index} style={{marginBottom: 8}}>
            <Select
              style={{width: 260}} placeholder="选择系统"
              value={entry.system_id}
              onChange={v => {
                this.setTemplateEntry(index, {system_id: v, template_id: undefined});
                this.loadPoints(v);
                this.fetchTemplates(v).then(list => {
                  this.setState(prev => ({templateOptions: {...prev.templateOptions, [v]: list}}));
                });
              }}>
              {systems.map(s => (
                <Option value={s.id} key={s.id}>{s.system_code}｜{s.name}｜{s.install_location}</Option>
              ))}
            </Select>
            <Select
              style={{width: 260}} placeholder="选择模板"
              value={entry.template_id}
              disabled={!entry.system_id}
              onChange={v => this.setTemplateEntry(index, {template_id: v})}>
              {(templateOptions[entry.system_id] || []).map(t => (
                <Option value={t.id} key={t.id}>{t.name}（{t.template_code}）</Option>
              ))}
            </Select>
            <Button icon={<DeleteOutlined/>} onClick={() => this.removeTemplateEntry(index)}/>
          </Space>
        ))}
        <div>
          <Button size="small" icon={<PlusOutlined/>} onClick={this.addTemplateEntry}>添加系统</Button>
          <Button size="small" type="primary" ghost style={{marginLeft: 8}} onClick={this.generatePreview}>
            生成台账明细
          </Button>
          <Button
            size="small" style={{marginLeft: 8}}
            onClick={() => this.setState({createdFrom: 'manual'})}>
            改为临时直接新建
          </Button>
        </div>
      </div>
    );
  };

  renderManualSection = () => {
    const {systems, rows} = this.state;
    const {store} = this.props;
    if (store.record.id) return null;
    return (
      <div style={{marginBottom: 8}}>
        <Divider orientation="left" style={{fontSize: 13, margin: '12px 0 8px'}}>临时增加检查/维护项</Divider>
        {systems.map(s => (
          <Button
            key={s.id} size="small" style={{marginRight: 8, marginBottom: 8}}
            onClick={() => this.addManualRow(s.id)}>
            + {s.system_code}｜{s.name}
          </Button>
        ))}
        {rows.length === 0 && (
          <div style={{color: '#999', fontSize: 12}}>
            点击上方系统按钮添加明细行；通过模板生成可切换到本方式混合补录。
          </div>
        )}
      </div>
    );
  };

  renderRowTable = (groupRows) => {
    const {pointsMap} = this.state;
    const systemId = groupRows[0].system_id;
    const points = pointsMap[systemId] || [];
    const columns = [
      {
        title: '巡检点/位置', key: 'point', width: 150,
        render: (t, r) => r.template_item_id && !r.is_temporary ? (
          (r.inspection_point_name_snapshot || (r.inspection_point_id ? '' : ''))
          || <Input size="small" placeholder="维护位置" value={r.location} onChange={e => this.setRow(r.client_key, {location: e.target.value})}/>
        ) : (
          <Space size={4} direction="vertical" style={{width: '100%'}}>
            <Select
              size="small" style={{width: '100%'}} allowClear placeholder="选择巡检点"
              value={r.inspection_point_id || undefined}
              onChange={v => this.setRow(r.client_key, {inspection_point_id: v || undefined})}>
              {points.map(p => <Option value={p.id} key={p.id}>{p.name}</Option>)}
            </Select>
            <Input size="small" placeholder="或填写维护位置" value={r.location} onChange={e => this.setRow(r.client_key, {location: e.target.value})}/>
          </Space>
        ),
      },
      {
        title: '检查/维护项目', key: 'item', width: 180,
        render: (t, r) => (
          <Space size={2} direction="vertical" style={{width: '100%'}}>
            {(r.is_temporary || !r.id) && !r.template_item_id ? (
              <Input size="small" placeholder="项目名称" value={r.item_name} onChange={e => this.setRow(r.client_key, {item_name: e.target.value})}/>
            ) : <span>{r.item_name}</span>}
            {r.standard && <span style={{color: '#999', fontSize: 12}}>标准：{r.standard}</span>}
          </Space>
        ),
      },
      {title: '单位', dataIndex: 'unit', width: 60, render: v => v || '-'},
      {title: '正常范围', dataIndex: 'normal_range', width: 100, render: v => v || '-'},
      {title: '填写值', key: 'value', width: 130, render: (t, r) => this.renderValueControl(r)},
      {title: '结果', key: 'result', width: 150, render: (t, r) => this.renderResultControl(r)},
      {
        title: '异常说明', key: 'abnormal', width: 150,
        render: (t, r) => r.result === 'abnormal' ? (
          <Input.TextArea
            rows={1} placeholder="必填" className="el-ledger-abnormal-input"
            value={r.abnormal_desc}
            onChange={e => this.setRow(r.client_key, {abnormal_desc: e.target.value})}/>
        ) : r.result === 'not_applicable' ? (
          <Input size="small" placeholder="不适用原因（选填）" value={r.na_reason} onChange={e => this.setRow(r.client_key, {na_reason: e.target.value})}/>
        ) : '-',
      },
      {
        title: '现场处理', key: 'onsite', width: 130,
        render: (t, r) => (
          <Input.TextArea rows={1} value={r.onsite_action} onChange={e => this.setRow(r.client_key, {onsite_action: e.target.value})}/>
        ),
      },
      {
        title: '执行人', key: 'executor', width: 90,
        render: (t, r) => (
          <Input size="small" value={r.executor_name} onChange={e => this.setRow(r.client_key, {executor_name: e.target.value})}/>
        ),
      },
      {
        title: '操作', key: 'action', width: 50, align: 'center',
        render: (t, r) => (
          <Tooltip title="移除该明细">
            <a style={{color: '#f5222d'}} onClick={() => this.removeRow(r.client_key)}><DeleteOutlined/></a>
          </Tooltip>
        ),
      },
    ];
    return (
      <div>
        <div style={{marginBottom: 6}}>
          <Checkbox
            onChange={e => {
              if (e.target.checked) this.batchConfirmNormal(groupRows);
            }}>
            批量确认未判定项为正常
          </Checkbox>
        </div>
        <Table
          rowKey="client_key" size="small"
          columns={columns} dataSource={groupRows} pagination={false}
          rowClassName={r => (r.result === 'abnormal' ? 'el-ledger-abnormal-row' : '')}/>
      </div>
    );
  };

  render() {
    const {store} = this.props;
    const {rows, loading} = this.state;
    const groups = [];
    const groupMap = {};
    rows.forEach(r => {
      const system = this.state.systems.find(s => s.id === r.system_id);
      const key = String(r.system_id);
      if (!groupMap[key]) {
        groupMap[key] = {
          system_id: r.system_id,
          label: system ? `${system.name}（${system.system_code}｜${system.install_location}）` : `系统 #${r.system_id}`,
          rows: [],
        };
        groups.push(groupMap[key]);
      }
      groupMap[key].rows.push(r);
    });
    const isEdit = !!store.record.id;
    const title = `${isEdit ? '编辑' : '新增'}${LEDGER_TYPE_TEXT[store.ledgerType]}台账`;
    return (
      <Modal
        title={title}
        visible={store.formVisible}
        width={1180}
        confirmLoading={loading}
        maskClosable={false}
        onCancel={() => {
          store.formVisible = false;
        }}
        onOk={this.submit}
        okText="整表一次提交">
        {this.renderHeader()}
        {this.renderTemplateSection()}
        {isEdit && (
          <div style={{color: '#fa8c16', marginBottom: 8, fontSize: 12}}>
            编辑草稿：修改与新增明细将一次提交；被移除的明细行会从台账删除并记录变化。
          </div>
        )}
        {groups.length > 0 ? (
          <Collapse defaultActiveKey={groups.map(g => g.key || String(g.system_id))}>
            {groups.map(g => (
              <Panel
                header={g.label}
                key={String(g.system_id)}
                extra={
                  <span>
                    {g.rows.length} 项
                    {g.rows.some(r => r.result === 'abnormal') && (
                      <span style={{color: '#f5222d', marginLeft: 8}}>
                        异常 {g.rows.filter(r => r.result === 'abnormal').length}
                      </span>
                    )}
                  </span>
                }>
                {this.renderRowTable(g.rows)}
              </Panel>
            ))}
          </Collapse>
        ) : (
          !isEdit && this.renderManualSection()
        )}
      </Modal>
    );
  }
}

export default LedgerForm;
export {LedgerForm};
