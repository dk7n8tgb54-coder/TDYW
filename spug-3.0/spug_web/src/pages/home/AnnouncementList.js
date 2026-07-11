/**
 * 公告查询页（用户端）
 * 支持发布部门、发布时间范围、阅读状态、关键字筛选；点击标题查看详情（自动标记已读）。
 */
import React, { useState, useEffect, useCallback } from 'react';
import { Breadcrumb, SearchForm } from 'components';
import { Table, Input, Select, DatePicker, Button, Tag, Space } from 'antd';
import { http, history, hasPermission } from 'libs';
import AnnouncementDetail from './AnnouncementDetail';

const { RangePicker } = DatePicker;
const STATUS_TAG = {
  unpublished: { color: 'default', text: '未发布' },
  published: { color: 'green', text: '已发布' },
  expired: { color: 'red', text: '已过期' },
};

export default function AnnouncementList() {
  const [loading, setLoading] = useState(false);
  const [data, setData] = useState([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(20);

  const [keyword, setKeyword] = useState('');
  const [readStatus, setReadStatus] = useState('');
  const [range, setRange] = useState(null);
  const [departmentId, setDepartmentId] = useState(undefined);
  const [departments, setDepartments] = useState([]);

  const [detailId, setDetailId] = useState(null);
  const [detailVisible, setDetailVisible] = useState(false);

  const canManage = hasPermission('home.announcement.view');

  useEffect(() => {
    if (canManage) {
      http.get('/api/home/announcement/admin/departments/')
        .then(list => setDepartments(list || []))
        .catch(() => setDepartments([]));
    }
  }, [canManage]);

  const fetchData = useCallback(() => {
    setLoading(true);
    const params = { page, page_size: pageSize, keyword, read_status: readStatus };
    if (range && range[0] && range[1]) {
      params.start_at = range[0].format('YYYY-MM-DD');
      params.end_at = range[1].format('YYYY-MM-DD');
    }
    if (canManage && departmentId) params.publish_department_id = departmentId;
    http.get('/api/home/announcement/', { params })
      .then(res => {
        setData(res.results || []);
        setTotal(res.total || 0);
      })
      .catch(() => { setData([]); setTotal(0); })
      .finally(() => setLoading(false));
  }, [page, pageSize, keyword, readStatus, range, departmentId, canManage]);

  useEffect(() => { fetchData(); }, [fetchData]);

  const openDetail = (id) => {
    setDetailId(id);
    setDetailVisible(true);
  };

  const columns = [
    {
      title: '标题',
      dataIndex: 'title',
      key: 'title',
      render: (text, record) => (
        <Space size={4}>
          {!record.is_read && <span style={{ display: 'inline-block', width: 8, height: 8, borderRadius: '50%', background: '#ff4d4f' }} />}
          <a onClick={() => openDetail(record.id)}>{text}</a>
          {record.is_new && <Tag color="red">新</Tag>}
          {record.is_important && <Tag color="gold">重要</Tag>}
        </Space>
      ),
    },
    { title: '发布部门', dataIndex: 'publish_department_name', key: 'publish_department_name', width: 140 },
    { title: '发布时间', dataIndex: 'published_at', key: 'published_at', width: 170 },
    {
      title: '状态', dataIndex: 'computed_status', key: 'computed_status', width: 100,
      render: s => { const t = STATUS_TAG[s] || STATUS_TAG.unpublished; return <Tag color={t.color}>{t.text}</Tag>; },
    },
    {
      title: '阅读状态', dataIndex: 'is_read', key: 'is_read', width: 90,
      render: r => r ? <Tag color="blue">已读</Tag> : <Tag>未读</Tag>,
    },
    { title: '附件', dataIndex: 'attachment_count', key: 'attachment_count', width: 70 },
  ];

  return (
    <div>
      <Breadcrumb>
        <Breadcrumb.Item>首页</Breadcrumb.Item>
        <Breadcrumb.Item>系统公告</Breadcrumb.Item>
      </Breadcrumb>
      <SearchForm>
        <SearchForm.Item span={6} title="关键字">
          <Input allowClear value={keyword} placeholder="标题关键字" onChange={e => setKeyword(e.target.value)} />
        </SearchForm.Item>
        <SearchForm.Item span={6} title="发布时间">
          <RangePicker value={range} onChange={v => setRange(v)} style={{ width: '100%' }} />
        </SearchForm.Item>
        <SearchForm.Item span={4} title="阅读状态">
          <Select value={readStatus} allowClear onChange={v => setReadStatus(v)} placeholder="全部" style={{ width: '100%' }}>
            <Select.Option value="">全部</Select.Option>
            <Select.Option value="read">已读</Select.Option>
            <Select.Option value="unread">未读</Select.Option>
          </Select>
        </SearchForm.Item>
        {canManage && (
          <SearchForm.Item span={5} title="发布部门">
            <Select
              value={departmentId}
              allowClear
              showSearch
              optionFilterProp="children"
              onChange={v => setDepartmentId(v)}
              placeholder="全部部门"
              style={{ width: '100%' }}
            >
              {departments.map(d => <Select.Option key={d.id} value={d.id}>{d.name}</Select.Option>)}
            </Select>
          </SearchForm.Item>
        )}
        <SearchForm.Item span={3} title=" ">
          <Button type="primary" onClick={() => { setPage(1); fetchData(); }}>查询</Button>
        </SearchForm.Item>
      </SearchForm>
      <Table
        rowKey="id"
        loading={loading}
        columns={columns}
        dataSource={data}
        pagination={{
          current: page,
          pageSize,
          total,
          showSizeChanger: true,
          onChange: (p, ps) => { setPage(p); setPageSize(ps); },
        }}
      />
      <AnnouncementDetail
        visible={detailVisible}
        announcementId={detailId}
        onClose={() => setDetailVisible(false)}
        onAfterRead={fetchData}
      />
    </div>
  );
}
