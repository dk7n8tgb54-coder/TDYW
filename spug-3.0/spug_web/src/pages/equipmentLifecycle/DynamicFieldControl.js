/**
 * Copyright (c) OpenSpug Organization. https://github.com/openspug/spug
 * Copyright (c) <spug.dev@gmail.com>
 * Released under the AGPL-3.0 License.
 */
/**
 * 设备全生命周期——动态配置字段控件。
 * 按字段类型渲染文本/长文本/数字/日期/单选/多选/布尔/附件/明细表控件，
 * 供新增/编辑系统表单填写字段值；附件类型依赖系统 ID（新增系统时
 * 附件需待系统创建后在编辑页面上传）。
 */
import React, { useState, useEffect, useRef } from 'react';
import moment from 'moment';
import {
  Input, InputNumber, Select, DatePicker, Button, Table, Popconfirm, Divider, Upload,
} from 'antd';
import { PlusOutlined, UploadOutlined } from '@ant-design/icons';
import store from './store';
import { API_PREFIX } from './constants';

const {TextArea} = Input;

export function parseChoices(choices) {
  try {
    const data = typeof choices === 'string' ? JSON.parse(choices) : choices;
    return Array.isArray(data) ? data.map(String) : [];
  } catch (e) {
    return [];
  }
}

export function parseDetailColumns(raw) {
  try {
    const data = typeof raw === 'string' ? JSON.parse(raw) : raw;
    return Array.isArray(data) ? data.filter(c => c && c.code) : [];
  } catch (e) {
    return [];
  }
}

function AttachmentControl({value, systemId, disabled, onChange}) {
  const ids = Array.isArray(value) ? value : [];
  const [attachments, setAttachments] = useState(null);
  const [uploading, setUploading] = useState(false);
  const mountedRef = useRef(true);
  useEffect(() => () => { mountedRef.current = false; }, []);

  useEffect(() => {
    if (!systemId) return;
    store.fetchSystemAttachments(systemId)
      .then(res => {
        if (mountedRef.current) setAttachments(res.data || []);
      })
      .catch(() => {
        if (mountedRef.current) setAttachments([]);
      });
  }, [systemId]);

  if (!systemId) {
    return <Input disabled placeholder="附件需待系统创建后在编辑页面上传"/>;
  }
  const list = (attachments || []).filter(a => ids.includes(a.id));
  return (
    <div>
      <Table
        size="small"
        rowKey="id"
        pagination={false}
        loading={attachments === null}
        dataSource={list}
        columns={[{
          title: '文件名', dataIndex: 'file_name', ellipsis: true,
        }, {
          title: '大小', dataIndex: 'file_size', width: 90,
          render: s => `${Math.max(1, Math.round((s || 0) / 1024))} KB`,
        }, {
          title: '操作', width: 130,
          render: (text, att) => (
            <span>
              <a href={`${API_PREFIX}/systems/${systemId}/config/attachments/${att.id}/download/`}
                 target="_blank" rel="noopener noreferrer">下载</a>
              <Divider type="vertical"/>
              <Popconfirm
                title="删除该附件？"
                disabled={disabled}
                onOk={() => {
                  store.deleteSystemAttachment(systemId, att.id)
                    .then(() => onChange(ids.filter(x => x !== att.id)))
                    .catch(() => {});
                }}
              >
                <a disabled={disabled}>删除</a>
              </Popconfirm>
            </span>
          ),
        }]}
        locale={{emptyText: '暂无附件'}}
      />
      <Upload
        showUploadList={false}
        disabled={disabled}
        beforeUpload={(file) => {
          setUploading(true);
          store.uploadSystemAttachment(systemId, file)
            .then(res => {
              if (mountedRef.current) setUploading(false);
              onChange([...ids, res.id]);
            })
            .catch(() => {
              if (mountedRef.current) setUploading(false);
            });
          return false;
        }}
      >
        <Button size="small" loading={uploading} disabled={disabled} icon={<UploadOutlined/>}>
          上传附件
        </Button>
      </Upload>
    </div>
  );
}

function DetailTableControl({field, value, disabled, onChange}) {
  const rows = Array.isArray(value) ? value : [];
  const columns = field.detail_columns_parsed || parseDetailColumns(field.detail_columns);
  const updateRow = (idx, key, val) => {
    onChange(rows.map((row, i) => i === idx ? {...row, [key]: val} : row));
  };
  return (
    <div>
      <Table
        size="small"
        rowKey={(_, idx) => idx}
        pagination={false}
        dataSource={rows}
        columns={[
          ...columns.map(col => ({
            title: col.name,
            dataIndex: col.code,
            render: (text, row, idx) => (
              <Input
                size="small"
                value={(row && row[col.code]) || ''}
                disabled={disabled}
                onChange={e => updateRow(idx, col.code, e.target.value)}
              />
            ),
          })),
          {
            title: '操作', width: 60,
            render: (text, row, idx) => (
              <a disabled={disabled} onClick={() => onChange(rows.filter((_, i) => i !== idx))}>删除</a>
            ),
          },
        ]}
        locale={{emptyText: '暂无明细行'}}
      />
      <Button
        size="small"
        icon={<PlusOutlined/>}
        disabled={disabled}
        onClick={() => {
          const blank = {};
          columns.forEach(col => { blank[col.code] = ''; });
          onChange([...rows, blank]);
        }}
      >
        添加行
      </Button>
    </div>
  );
}

export default function DynamicFieldControl({field, value, onChange, disabled = false, systemId = 0}) {
  const choices = parseChoices(
    field.choices_parsed !== undefined ? field.choices_parsed : field.choices);
  switch (field.field_type) {
    case 'text':
      return (
        <Input
          maxLength={500}
          value={value}
          disabled={disabled}
          onChange={e => onChange(e.target.value)}
        />
      );
    case 'longtext':
      return (
        <TextArea
          rows={3}
          maxLength={10000}
          value={value}
          disabled={disabled}
          onChange={e => onChange(e.target.value)}
        />
      );
    case 'number': {
      const parsed = value === '' || value === null || value === undefined ? undefined : value;
      return (
        <InputNumber
          style={{width: '100%'}}
          min={field.number_min !== null && field.number_min !== undefined ? field.number_min : undefined}
          max={field.number_max !== null && field.number_max !== undefined ? field.number_max : undefined}
          value={parsed}
          disabled={disabled}
          onChange={v => onChange(v === undefined ? '' : v)}
        />
      );
    }
    case 'date':
      return (
        <DatePicker
          style={{width: '100%'}}
          value={value ? moment(value) : null}
          disabled={disabled}
          onChange={d => onChange(d ? d.format('YYYY-MM-DD') : '')}
        />
      );
    case 'choice':
      return (
        <Select
          allowClear
          style={{width: '100%'}}
          value={value || undefined}
          disabled={disabled}
          onChange={v => onChange(v === undefined ? '' : v)}
        >
          {choices.map(option => (
            <Select.Option value={option} key={option}>{option}</Select.Option>
          ))}
        </Select>
      );
    case 'multi_choice':
      return (
        <Select
          mode="multiple"
          style={{width: '100%'}}
          value={Array.isArray(value) ? value : []}
          disabled={disabled}
          onChange={v => onChange(v)}
        >
          {choices.map(option => (
            <Select.Option value={option} key={option}>{option}</Select.Option>
          ))}
        </Select>
      );
    case 'boolean':
      return (
        <Select
          allowClear
          style={{width: '100%'}}
          value={value === '' || value === null || value === undefined ? undefined : !!value}
          disabled={disabled}
          onChange={v => onChange(v === undefined ? '' : v)}
        >
          <Select.Option value={true}>是</Select.Option>
          <Select.Option value={false}>否</Select.Option>
        </Select>
      );
    case 'attachment':
      return <AttachmentControl value={value} systemId={systemId} disabled={disabled} onChange={onChange}/>;
    case 'detail_table':
      return <DetailTableControl field={field} value={value} disabled={disabled} onChange={onChange}/>;
    default:
      return <Input disabled value={value}/>;
  }
}
