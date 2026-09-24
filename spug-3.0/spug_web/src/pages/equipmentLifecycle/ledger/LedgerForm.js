/**
 * Copyright (c) OpenSpug Organization. https://github.com/openspug
 * Released under the AGPL-3.0 License.
 */
/**
 * 运维台账录入/编辑表单（步骤 3.2）：
 * - 通过模板生成（模板自动覆盖全部未停用电台）或临时直接新建；
 * - 明细按系统分组表格录入；新增提交按电台拆分立账：每个电台一条台账
 *   记录（独立编号、独立复核），client_token 按电台后缀保证重试幂等；
 * - 明细仅填写值：结果不强制选择（单选填"不正常"由后端记异常），异常说明选填；
 * - 表头仅保留维护周期（周月维护）、实际执行日期（新增默认当日）与执行人。
 * 提交成功后重新获取后端真实数据，不做乐观更新。
 */
import React from 'react';
import {observer} from 'mobx-react';
import {
  Modal, Form, Input, Select, Button, Collapse,
  Space, Divider, message,
} from 'antd';
import {PlusOutlined, DeleteOutlined} from '@ant-design/icons';
import {http} from 'libs';
import {
  API_PREFIX_L, LEDGER_TYPE, LEDGER_TYPE_TEXT,
} from './constants';
import {
  buildSubmitEntries, expandTemplateEntries, makeRow,
  rowsFromPreview, rowLooksAbnormal, todayStr,
} from './ledgerCommon';
import LedgerRowsTable from './LedgerRowsTable';
import {getLedgerStore} from './store';

const {Panel} = Collapse;
const {Option} = Select;

@observer
class LedgerForm extends React.Component {
  state = {
    loading: false,
    createdFrom: 'template',
    systems: [],
    templateEntries: [],       // [{template_id}]，展开时自动覆盖全部未停用电台
    templates: [],             // 当前类型全部启用模板
    rows: [],
    cycle: undefined,
    header: {
      executed_date: todayStr(),
      executed_start: null,
      executed_end: null,
      executor_names: '',
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
            item_name: item.item_name,
            input_type: item.input_type,
            unit: item.unit || '',
            choices: item.choices || [],
            is_required: item.is_required,
            value_text: item.value_text || '',
            value_number: item.value_number,
            value_bool: item.value_bool,
            // 结果仅用于已有异常行的角标/高亮显示，提交时不再上报
            result: item.result,
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
              executor_names: res.executor_names || '',
            },
          });
        })
        .finally(() => this.setState({loading: false}));
    } else if (!this.isWeekMonth) {
      // 新增模式：一次加载当前类型全部启用模板（周月维护待选周期后再加载）
      this.fetchTemplates().then(templates => this.setState({templates}));
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
      templateEntries: [...prev.templateEntries, {template_id: undefined}],
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

  fetchTemplates = (cycleOverride) => {
    const {store} = this.props;
    let url = `${API_PREFIX_L}/ledger-templates/available/?ledger_type=${store.ledgerType}`;
    const cycle = cycleOverride || this.state.cycle;
    if (this.isWeekMonth && cycle) url += `&maintenance_cycle=${cycle}`;
    return http.get(url).then(res => res.data).catch(() => []);
  };

  generatePreview = () => {
    const {templateEntries, systems, cycle} = this.state;
    const {store} = this.props;
    // 模板条目自动覆盖全部未停用系统：展开为 系统×模板 配对（预览接口契约不变）
    const entries = expandTemplateEntries(templateEntries, systems);
    if (!entries.length) {
      message.error(templateEntries.some(t => t.template_id)
        ? '系统档案中没有可用系统，请先维护系统'
        : '请先选择模板');
      return;
    }
    this.setState({loading: true});
    http.post(`${API_PREFIX_L}/ledgers/preview/`, {
      ledger_type: store.ledgerType,
      maintenance_cycle: this.isWeekMonth ? (cycle || '') : '',
      entries,
    }).then(res => {
      const rows = rowsFromPreview(res.data);
      if (!rows.length) {
        message.warning('所选模板没有与本次周期匹配的项目');
      }
      this.setState({rows});
    }).finally(() => this.setState({loading: false}));
  };

  addManualRow = (systemId) => {
    this.setState(prev => ({
      rows: [...prev.rows, makeRow({system_id: systemId, is_temporary: true})],
    }));
  };

  removeRow = (clientKey) => {
    this.setState(prev => ({rows: prev.rows.filter(r => r.client_key !== clientKey)}));
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
    if (!rows.length) {
      message.error('请至少录入一条台账明细');
      return;
    }
    // 按 系统+模板 分组组装 entries（同系统不同模板分列，后端逐条目校验快照来源）
    const built = buildSubmitEntries(rows);
    if (built.error) {
      message.error(built.error);
      return;
    }
    const entries = built.entries;
    const payload = {
      ledger_type: store.ledgerType,
      // 巡检固定空周期；周月维护提交所选周期；季维护后端校验固定为 'season'
      maintenance_cycle: this.isWeekMonth
        ? cycle
        : (store.ledgerType === LEDGER_TYPE.SEASONAL ? 'season' : ''),
      created_from: createdFrom,
      ...header,
    };
    this.setState({loading: true});
    let request;
    if (store.record.id) {
      // 编辑草稿：单条台账整体 PUT（历史台账可能跨系统，保持原接口）
      request = http.put(`${API_PREFIX_L}/ledgers/${store.record.id}/`, {...payload, entries, version});
    } else {
      // 按电台拆分立账：每个电台一条台账记录（独立编号/复核）；
      // client_token 按电台后缀，本次弹窗内重试时已建台账幂等返回
      if (!this.submitToken) {
        this.submitToken = `lf_${Date.now()}_${Math.random().toString(36).slice(2, 10)}`;
      }
      const entriesBySystem = {};
      entries.forEach(e => {
        (entriesBySystem[e.system_id] = entriesBySystem[e.system_id] || []).push(e);
      });
      const posts = Object.keys(entriesBySystem).map(systemId => http.post(`${API_PREFIX_L}/ledgers/`, {
        ...payload,
        client_token: `${this.submitToken}_s${systemId}`,
        entries: entriesBySystem[systemId],
      }));
      request = Promise.all(posts);
    }
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
    const {header, cycle} = this.state;
    const {store} = this.props;
    const isEdit = !!store.record.id;
    return (
      <Form layout="inline" style={{marginBottom: 8}} className="el-ledger-header-form">
        {this.isWeekMonth && (
          <Form.Item required label="维护周期">
            <Select
              style={{width: 100}} value={cycle} disabled={isEdit}
              placeholder="周/月"
              onChange={v => {
                this.setState({cycle: v});
                if (!isEdit) {
                  // 周期决定可用模板集合：切换后重新加载并清空已选模板
                  this.fetchTemplates(v).then(templates => this.setState({templates}));
                  this.setState(prev => ({
                    templateEntries: prev.templateEntries.map(t => ({...t, template_id: undefined})),
                  }));
                }
              }}>
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
        <Form.Item label="执行人">
          <Input style={{width: 150}} value={header.executor_names} onChange={e => this.setHeader('executor_names', e.target.value)}/>
        </Form.Item>
      </Form>
    );
  };

  renderTemplateSection = () => {
    const {templateEntries, templates} = this.state;
    const {store} = this.props;
    if (store.record.id) return null;
    return (
      <div style={{marginBottom: 12}}>
        <Divider orientation="left" style={{fontSize: 13, margin: '12px 0 8px'}}>通过模板生成</Divider>
        {templateEntries.map((entry, index) => {
          return (
            <div key={index} style={{marginBottom: 4}}>
              <Space style={{marginBottom: 4}} wrap>
                <Select
                  style={{width: 240}} placeholder="选择模板"
                  value={entry.template_id}
                  onChange={v => this.setTemplateEntry(index, {template_id: v})}>
                  {templates.map(t => (
                    <Option value={t.id} key={t.id}>{t.name}</Option>
                  ))}
                </Select>
                <Button icon={<DeleteOutlined/>} onClick={() => this.removeTemplateEntry(index)}/>
              </Space>
            </div>
          );
        })}
        <div>
          <Button size="small" icon={<PlusOutlined/>} onClick={this.addTemplateEntry}>添加模板条目</Button>
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
            + {s.name}
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

  renderRowTable = (groupRows) => (
    <LedgerRowsTable rows={groupRows} onSetRow={this.setRow} onRemoveRow={this.removeRow}/>
  );

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
          label: system ? `${system.name}（${system.install_location}）` : `系统 #${r.system_id}`,
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
                    {g.rows.some(r => rowLooksAbnormal(r)) && (
                      <span style={{color: '#f5222d', marginLeft: 8}}>
                        异常 {g.rows.filter(r => rowLooksAbnormal(r)).length}
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
