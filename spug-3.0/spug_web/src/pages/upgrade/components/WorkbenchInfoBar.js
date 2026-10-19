/**
 * Copyright (c) <spug.dev@gmail.com>
 * Released under the AGPL-3.0 License.
 */
/**
 * 工作台顶部信息栏（从 WorkbenchForm 迁出，2026-10 失败闭环改造时拆分文件）：
 * - RecordInfoBar：紧凑两行信息 + 打印/编辑入口 + 只读详细说明；
 * - EditBasicInfoPanel：编辑基本信息表单面板（保存/取消由 hooks.useBasicInfoEditor 编排）。
 */
import React, {useState} from 'react';
import {observer} from 'mobx-react';
import {
  Form, Input, Select, DatePicker, Button, Tag, Dropdown, Menu, Row, Col,
} from 'antd';
import {PrinterOutlined, DownOutlined, FormOutlined} from '@ant-design/icons';
import store from '../store';
import {STATUS_TAG_COLOR, UPGRADE_TYPE_OPTIONS, STATUS_OPTIONS} from '../shared';
import SystemSelect from './SystemSelect';
import styles from '../Workbench.module.less';

const {TextArea} = Input;
const {Option} = Select;

/** 只读详细说明块：查看用户也能阅读升级内容/影响范围/风险说明/回退摘要 */
const DETAIL_BLOCKS = [
  ['upgrade_content', '升级内容'],
  ['impact_scope', '影响范围'],
  ['risk_desc', '风险说明'],
  ['rollback_plan', '回退方案摘要'],
];

function DetailBlocks() {
  return (
    <div className={styles.detailBlocks}>
      {DETAIL_BLOCKS.map(([field, label]) => (
        <div key={field} className={styles.detailBlock}>
          <div className={styles.detailBlockTitle}>{label}</div>
          <div className={styles.detailBlockBody}>{store.record[field] || '—'}</div>
        </div>
      ))}
    </div>
  );
}

/** 编辑基本信息面板：表单字段与原折叠面板一致，面板内提供保存修改/取消 */
function EditBasicInfoPanel({form, saving, onSaveEdit, onCancelEdit}) {
  return (
    <div className={styles.editPanel}>
      <Form form={form} layout="vertical">
        <Row gutter={16}>
          <Col span={12}>
            <Form.Item name="title" label="标题">
              <Input placeholder="标题" />
            </Form.Item>
          </Col>
          <Col span={6}>
            <Form.Item name="system" label="系统">
              <SystemSelect placeholder="系统" />
            </Form.Item>
          </Col>
          <Col span={6}>
            <Form.Item name="upgrade_type" label="类型">
              <Select placeholder="类型">
                {UPGRADE_TYPE_OPTIONS.map(t => <Option key={t} value={t}>{t}</Option>)}
              </Select>
            </Form.Item>
          </Col>
          <Col span={6}>
            <Form.Item name="owner" label="负责人">
              <Input placeholder="请输入负责人" />
            </Form.Item>
          </Col>
          <Col span={6}>
            <Form.Item name="upgrade_time" label="计划升级时间">
              <DatePicker showTime style={{ width: '100%' }} placeholder="计划升级时间" />
            </Form.Item>
          </Col>
          <Col span={6}>
            <Form.Item name="status" label="状态">
              <Select placeholder="状态">
                {STATUS_OPTIONS.map(s => <Option key={s} value={s}>{s}</Option>)}
              </Select>
            </Form.Item>
          </Col>
          <Col span={24}>
            <Form.Item name="upgrade_content" label="升级内容">
              <TextArea rows={2} placeholder="升级内容" />
            </Form.Item>
          </Col>
          <Col span={12}>
            <Form.Item name="impact_scope" label="影响范围">
              <TextArea rows={2} placeholder="影响范围（选填）" />
            </Form.Item>
          </Col>
          <Col span={12}>
            <Form.Item name="risk_desc" label="风险说明">
              <TextArea rows={2} placeholder="风险说明（选填）" />
            </Form.Item>
          </Col>
          <Col span={24}>
            <Form.Item name="rollback_plan" label="回退方案摘要">
              <TextArea rows={2} placeholder="回退方案摘要（选填）" />
            </Form.Item>
          </Col>
        </Row>
      </Form>
      <div className={styles.editActions}>
        <Button type="primary" loading={saving} onClick={onSaveEdit}>保存修改</Button>
        <Button onClick={onCancelEdit}>取消</Button>
      </div>
    </div>
  );
}

/**
 * 顶部信息栏（紧凑两行）：
 * 第一行 = 升级标题 + 状态，右侧编辑/打印入口；
 * 第二行 = 系统/计划升级时间/负责人主字段，编号/升级类型为次要信息；
 * 详细说明默认收起，展开后只读展示四段说明。
 */
const RecordInfoBar = observer(function RecordInfoBar(
  {canEdit, form, editVisible, saving, onToggleEdit, onSaveEdit, onCancelEdit, onPrintBasicInfo, onPrintSteps}) {
  const [detailVisible, setDetailVisible] = useState(false);
  const info = store.record;
  return (
    <div className={styles.infoBar}>
      <div className={styles.infoRowMain}>
        <span className={styles.infoTitle}>{info.title || '（未命名）'}</span>
        <Tag color={STATUS_TAG_COLOR[info.status] || 'default'}>{info.status}</Tag>
        <span className={styles.infoActions}>
          <Button size="small" icon={<PrinterOutlined />} onClick={onPrintBasicInfo}>打印基本信息</Button>
          <Dropdown overlay={(
            <Menu>
              <Menu.Item key="all" onClick={() => onPrintSteps()} disabled={store.recordSteps.length === 0}>打印全部阶段</Menu.Item>
              <Menu.Divider />
              {(store.filterOptions.phases || []).map(p => (
                <Menu.Item key={p} onClick={() => onPrintSteps(p)}>只打印【{p}】</Menu.Item>
              ))}
            </Menu>
          )}>
            <Button size="small" icon={<PrinterOutlined />} disabled={store.recordSteps.length === 0}>
              打印步骤 <DownOutlined />
            </Button>
          </Dropdown>
          {canEdit && (
            <Button size="small" icon={<FormOutlined />} aria-expanded={!!editVisible}
              onClick={onToggleEdit}>编辑基本信息</Button>
          )}
        </span>
      </div>
      <div className={styles.infoRowSub}>
        <span><span className={styles.infoLabel}>系统</span>{info.system_name || '-'}</span>
        <span><span className={styles.infoLabel}>计划升级时间</span>{info.upgrade_time || '-'}</span>
        <span><span className={styles.infoLabel}>负责人</span>{info.owner || '-'}</span>
        <span className={styles.infoMinor}><span className={styles.infoLabel}>编号</span>{info.upgrade_no || '-'}</span>
        <span className={styles.infoMinor}><span className={styles.infoLabel}>升级类型</span>{info.upgrade_type || '-'}</span>
        <Button type="link" size="small" className={styles.detailToggle}
          aria-expanded={detailVisible}
          onClick={() => setDetailVisible(v => !v)}>
          {detailVisible ? '收起详细说明' : '详细说明'}
        </Button>
      </div>
      {detailVisible && <DetailBlocks />}
      {canEdit && editVisible && (
        <EditBasicInfoPanel
          form={form} saving={saving}
          onSaveEdit={onSaveEdit} onCancelEdit={onCancelEdit}/>
      )}
    </div>
  );
});

export default RecordInfoBar;
