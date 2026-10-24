/**
 * Copyright (c) OpenSpug Organization. https://github.com/openspug
 * Released under the AGPL-3.0 License.
 *
 * 数字表单台账模板管理页（2026-10-21，/el/form-ledger-templates）。
 *
 * 与"Excel台账模板"并列于维护台账模板管理区，每条模板明确标记
 * 类型"数字表单"；提供 创建 → 编辑表单（配置器抽屉）→ 预览 → 发布
 * 不可变版本 → 版本查看 的完整闭环；停用/启用/删除语义与 Excel 模板
 * 一致（删除仅限未被任何台账引用）。适用系统/生成周期在列表行内
 * "配置"弹窗维护（复用 Excel 同构语义，不影响已生成台账）。
 * 权限：ledger_template.view|add|edit|del（与 Excel 模板同权限域）。
 */
import React, {useEffect, useState} from 'react';
import {observer} from 'mobx-react';
import {
  Button, Drawer, Empty, Input, Modal, Radio, Select, Space, Table, Tag, Timeline,
} from 'antd';
import {AuthDiv, AuthButton} from 'components';
import FormFillRenderer, {useNarrowViewport} from './FormFillRenderer';
import FormTemplateCreateModal from './FormTemplateCreateModal';
import FormTemplateEditor from './FormTemplateEditor';
import {formTemplateStore as store} from './formTemplateStore';
import {LEDGER_TYPE_TEXT, PERM_L} from '../constants';
import {TEMPLATE_STATUS_TEXT} from './constants';

const DRAFT_STATE_TEXT = {
  no_draft: '尚未编辑表单',
  no_versions: '草稿未发布',
  identical: '与最新版本一致',
  modified: '草稿有修改未发布',
  unknown: '无法确认来源',
};

const STATUS_COLOR = {
  draft: 'default', published: 'blue', used: 'green', deleted: 'default',
};

/** 适用系统/生成周期配置弹窗（复用 Excel 同构语义：空=待配置）。 */
function GenerationConfigModal({template, visible, onCancel, onSaved}) {
  const [system, setSystem] = useState(undefined);
  const [period, setPeriod] = useState('');
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    if (!visible || !template) return;
    setSystem(template.system || undefined);
    setPeriod(template.generation_period || '');
    store.fetchCreateOptions().catch(() => {});
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [visible, template && template.id]);

  const options = store.createOptions;
  const periods = options && template
    ? (options.periods || {})[template.ledger_type] : null;

  const handleOk = () => {
    setSaving(true);
    store.saveGenerationConfig(template.id, {
      system: system === undefined ? '' : system,
      generation_period: period || '',
    }).then(() => {
      setSaving(false);
      onSaved();
    }).catch(() => setSaving(false));
  };

  return (
    <Modal title={`生成配置：${template ? template.name : ''}`} visible={visible}
           confirmLoading={saving} destroyOnClose
           okText="保存" cancelText="取消" onOk={handleOk} onCancel={onCancel}>
      <div style={{marginBottom: 8}}>适用系统（一模板对应一个系统）</div>
      <Select style={{width: '100%'}} allowClear value={system}
              placeholder="待配置（不参与本期自动生成）"
              loading={!options} onChange={v => setSystem(v)}>
        {(options ? options.systems : []).map(item => (
          <Select.Option key={item.id} value={item.id} disabled={!item.is_active}>
            {item.name}（{item.system_code}）{item.is_active ? '' : '（已停用）'}
          </Select.Option>
        ))}
      </Select>
      <div style={{margin: '12px 0 8px'}}>生成周期</div>
      <Select style={{width: '100%'}} allowClear value={period || undefined}
              placeholder="待配置" onChange={v => setPeriod(v || '')}>
        {(periods || []).map(item => (
          <Select.Option key={item.value} value={item.value}>{item.label}</Select.Option>
        ))}
      </Select>
    </Modal>
  );
}

/** 版本查看抽屉：版本时间线 + 选中版本只读渲染（窄屏传 narrow）。 */
function VersionDrawer() {
  const template = store.versionsTemplate;
  const detail = store.versionDetail;
  const narrow = useNarrowViewport(768);
  return (
    <Drawer title={`版本历史：${template ? template.name : ''}`}
            visible={store.versionsVisible} onClose={() => store.closeVersions()}
            width="70%" destroyOnClose>
      <div style={{display: 'flex', gap: 16}}>
        <div style={{width: 260, flexShrink: 0}}>
          <Timeline>
            {store.versions.map(version => (
              <Timeline.Item key={version.version_no}
                             dot={detail && detail.version_no === version.version_no
                               ? <span style={{color: '#1890ff'}}>●</span> : null}>
                <a data-testid={`version-item-${version.version_no}`}
                   onClick={() => store.fetchVersionDetail(template.id, version.version_no)}>
                  v{version.version_no}
                </a>
                <span style={{color: '#999', marginLeft: 6, fontSize: 12}}>
                  {version.field_count} 字段 · {String(version.published_at).slice(0, 19).replace('T', ' ')}
                </span>
              </Timeline.Item>
            ))}
          </Timeline>
        </div>
        <div style={{flex: 1, minWidth: 0}}>
          {detail ? (
            <FormFillRenderer form={detail.form} values={{}} editable={false}
                              narrow={narrow}/>
          ) : (
            <Empty description="选择左侧版本查看表单定义（不可变快照）"/>
          )}
        </div>
      </div>
    </Drawer>
  );
}

function FormTemplatePage() {
  const [createVisible, setCreateVisible] = useState(false);
  const [configTemplate, setConfigTemplate] = useState(null);

  useEffect(() => {
    store.fetchList().catch(() => {});
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const handleDelete = template => {
    Modal.confirm({
      title: `删除模板（${template.name}）`,
      content: '仅限未被任何台账引用的模板；被引用模板请改用停用。删除后不可恢复。',
      okText: '确认删除', okButtonProps: {danger: true}, cancelText: '取消',
      onOk: () => store.destroy(template.id).catch(() => {}),
    });
  };

  const columns = [
    {
      title: '模板名称', dataIndex: 'name', width: 200, ellipsis: true,
      render: (v, record) => (
        <span>
          <Tag color="purple">数字表单</Tag>
          <a onClick={() => store.openEditor(record)}>{v}</a>
        </span>
      ),
    },
    {
      title: '维护类型', dataIndex: 'ledger_type', width: 100,
      render: v => LEDGER_TYPE_TEXT[v] || v,
    },
    {title: '适用系统', dataIndex: 'system_name', width: 150, ellipsis: true,
     render: v => v || '待配置'},
    {title: '生成周期', dataIndex: 'generation_period_text', width: 90,
     render: v => v || '待配置'},
    {title: '说明', dataIndex: 'description', width: 180, ellipsis: true,
     render: v => v || '—'},
    {title: '版本', key: 'versions', width: 90,
     render: (v, record) => record.versions_count
       ? `v${record.latest_version_no}（共${record.versions_count}版）` : '—'},
    {title: '关联台账', dataIndex: 'ledgers_count', width: 90},
    {
      title: '状态', dataIndex: 'status', width: 90,
      render: v => <Tag color={STATUS_COLOR[v]}>{TEMPLATE_STATUS_TEXT[v] || v}</Tag>,
    },
    {
      title: '操作', key: 'actions', width: 300, align: 'center',
      render: (v, record) => (
        <span>
          <AuthButton auth={PERM_L.TPL_EDIT}
                      onClick={() => store.openEditor(record)}>编辑表单</AuthButton>
          <a style={{marginLeft: 8}} onClick={() => store.openVersions(record)}>版本</a>
          <a style={{marginLeft: 8}} onClick={() => setConfigTemplate(record)}>配置</a>
          {record.is_active ? (
            <AuthButton auth={PERM_L.TPL_DEL} style={{marginLeft: 8}}
                        onClick={() => {
                          Modal.confirm({
                            title: `停用模板（${record.name}）`,
                            content: '停用后不能用于新台账，历史版本与台账保留；可重新启用。',
                            okText: '确认停用', cancelText: '取消',
                            onOk: () => store.deactivate(record.id).catch(() => {}),
                          });
                        }}>停用</AuthButton>
          ) : (
            <AuthButton auth={PERM_L.TPL_DEL} style={{marginLeft: 8}}
                        onClick={() => store.activate(record.id).catch(() => {})}>启用</AuthButton>
          )}
          <AuthButton auth={PERM_L.TPL_DEL} style={{marginLeft: 8, color: '#f5222d'}}
                      onClick={() => handleDelete(record)}>删除</AuthButton>
        </span>
      ),
    },
  ];

  return (
    <AuthDiv auth={PERM_L.TPL_VIEW}>
      <div style={{marginBottom: 8, display: 'flex', gap: 8, flexWrap: 'wrap'}}>
        <AuthButton auth={PERM_L.TPL_ADD} type="primary" data-testid="form-tpl-create"
                    onClick={() => setCreateVisible(true)}>
          新建数字表单模板
        </AuthButton>
        <Input.Search allowClear placeholder="搜索模板名称" style={{width: 240}}
                      value={store.keyword}
                      onChange={e => store.setKeyword(e.target.value)}/>
        <Radio.Group value={store.ledgerTypeFilter} optionType="button" buttonStyle="solid"
                     onChange={e => store.setLedgerTypeFilter(e.target.value)}>
          <Radio.Button value="">全部</Radio.Button>
          <Radio.Button value="week_month">{LEDGER_TYPE_TEXT.week_month}</Radio.Button>
          <Radio.Button value="seasonal">{LEDGER_TYPE_TEXT.seasonal}</Radio.Button>
        </Radio.Group>
        <span style={{color: '#999', alignSelf: 'center'}}>
          数字表单模板：分组/字段/明细组/矩阵的结构化台账，发布不可变版本，与 Excel 模板路线并行
        </span>
      </div>
      <Table
        rowKey="id" loading={store.isFetching} columns={columns}
        dataSource={store.list} pagination={false}
        locale={{emptyText: <Empty description="暂无数字表单模板"/>}}/>
      <FormTemplateCreateModal visible={createVisible}
                               onCancel={() => setCreateVisible(false)}
                               onCreated={() => setCreateVisible(false)}/>
      <FormTemplateEditor store={store}/>
      <VersionDrawer/>
      <GenerationConfigModal
        template={configTemplate} visible={!!configTemplate}
        onCancel={() => setConfigTemplate(null)}
        onSaved={() => setConfigTemplate(null)}/>
    </AuthDiv>
  );
}

export default observer(FormTemplatePage);
