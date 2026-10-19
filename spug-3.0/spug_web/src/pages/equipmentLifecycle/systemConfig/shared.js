/**
 * Copyright (c) OpenSpug Organization. https://github.com/openspug/spug
 * Copyright (c) <spug.dev@gmail.com>
 * Released under the AGPL-3.0 License.
 */
/**
 * 系统配置共享展示单元（2026-10-19）。
 * 「系统详情 → 配置」只读页签与「设备管理 → 系统配置」维护入口共用同一套
 * 当前配置/变更历史列定义，避免两处表格口径漂移。
 */
import React from 'react';
import {Tag} from 'antd';
import {
  PARAM_TYPE_TEXT, PARAM_CATEGORY_TEXT,
  CONFIG_CHANGE_STATUS_TEXT, CONFIG_CHANGE_STATUS_COLOR,
  CONFIG_VERIFY_STATUS_TEXT, CONFIG_VERIFY_STATUS_COLOR,
} from '../constants';

// 当前值单元格：未设置显示中性 Tag，布尔显示 是/否
export function renderConfigValue(record) {
  if (record.display_value === '未设置') return <Tag>未设置</Tag>;
  if (record.data_type === 'bool') return record.value_bool === true ? '是' : '否';
  return record.display_value;
}

// 当前配置列（来源列区分"初始建档/配置变更 PZxxx"，未设置参数来源为空）
export function buildConfigColumns({showSource} = {}) {
  const columns = [{
    title: '参数名称',
    dataIndex: 'param_name',
    width: 160,
    render: (text, record) => (
      <span>
        {record.is_required && <Tag color="orange" style={{marginRight: 4}}>必填</Tag>}
        {text}
      </span>
    ),
  }, {
    title: '参数编码',
    dataIndex: 'param_code',
    width: 140,
  }, {
    title: '当前值',
    dataIndex: 'display_value',
    width: 120,
    render: (text, record) => renderConfigValue(record),
  }, {
    title: '单位',
    dataIndex: 'unit',
    width: 70,
    render: text => text || '-',
  }, {
    title: '数据类型',
    dataIndex: 'data_type',
    width: 80,
    render: text => PARAM_TYPE_TEXT[text] || text,
  }];
  if (showSource) {
    columns.push({
      title: '值来源',
      dataIndex: 'source_text',
      width: 150,
      render: text => text || '-',
    });
  }
  columns.push({
    title: '最后生效时间',
    dataIndex: 'effective_at',
    width: 140,
    render: text => text || '-',
  }, {
    title: '最后变更人',
    dataIndex: 'last_changed_by_name',
    width: 100,
    render: text => text || '-',
  });
  return columns;
}

// 配置变更历史列（onDetail：打开详情 Drawer）
export function buildChangeColumns(onDetail) {
  return [{
    title: '变更编号',
    dataIndex: 'change_no',
    width: 130,
  }, {
    title: '变更原因',
    dataIndex: 'reason',
    ellipsis: true,
  }, {
    title: '状态',
    dataIndex: 'status',
    width: 80,
    render: text => <Tag color={CONFIG_CHANGE_STATUS_COLOR[text]}>{CONFIG_CHANGE_STATUS_TEXT[text] || text}</Tag>,
  }, {
    title: '验证状态',
    dataIndex: 'verify_status',
    width: 90,
    render: (text) => (
      <Tag color={CONFIG_VERIFY_STATUS_COLOR[text || '']}>
        {CONFIG_VERIFY_STATUS_TEXT[text || ''] || '未验证'}
      </Tag>
    ),
  }, {
    title: '操作人',
    dataIndex: 'created_by_name',
    width: 100,
  }, {
    title: '变更时间',
    dataIndex: 'created_at',
    width: 140,
  }, {
    title: '操作',
    width: 60,
    render: (text, record) => <a onClick={() => onDetail(record.id)}>详情</a>,
  }];
}

// 参数分类 Tag（维护页参数定义表/建档信息共用）
export function renderCategoryTag(category) {
  const text = PARAM_CATEGORY_TEXT[category] || category;
  return <Tag color={category === 'hardware_spec' ? 'blue' : 'green'}>{text}</Tag>;
}
