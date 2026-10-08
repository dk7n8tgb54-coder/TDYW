/**
 * Copyright (c) OpenSpug Organization. https://github.com/openspug/spug
 * Released under the AGPL-3.0 License.
 */
/**
 * 设备全生命周期——运行记录只读统计视图（2026-10 第二版；2026-10-07
 * 起支持按记录类型筛选：未选择时后端默认统计 abnormal（原有异常统计
 * 口径保持不变），可选择日常运行查看 routine 口径。
 * 系统维度 / 状态维度 / 时间趋势 / 转故障数量 /
 * 长期未关闭（仅统计跟进中：已记录留痕为合法稳定状态，不计入积压）/
 * 平均处理时长。统计只使用运行记录数据（巡视、维护、配置变更、升级不进入
 * 本统计）；时间范围用发生时间起止筛选（后端 __gte/__lt）。
 * 状态维度由后端返回四状态原值计数（已记录/跟进中/已完成/已转故障；
 * 历史旧状态已由迁移 0007 归一）。
 * "重复问题"统计卡片已于 2026-10-05 随重复问题功能下线移除，duplicated
 * 统计键已随后端清理（2026-10-06）一并删除。"重要记录"卡片与系统维度
 * "重要"列已随标记重要字段删除移除（2026-10-06）。
 */
import React from 'react';
import { observer } from 'mobx-react';
import { DatePicker, Table, Tag, Card, Spin, Statistic, Row, Col, Empty, Button, Select } from 'antd';
import store from './store';
import {
  RUNTIME_STATUS_TEXT, RUNTIME_STATUS_COLOR,
  RUNTIME_RECORD_TYPE_OPTIONS,
} from '../constants';

const {RangePicker} = DatePicker;

const STATS_STALE_DAYS_DEFAULT = 7;

const systemColumns = [{
  title: '系统',
  dataIndex: 'system_name',
  width: 200,
  ellipsis: true,
}, {
  title: '记录总数',
  dataIndex: 'total',
  width: 100,
  sorter: (a, b) => a.total - b.total,
}, {
  title: '跟进中',
  dataIndex: 'following_up',
  width: 90,
}, {
  title: '转故障',
  dataIndex: 'converted_fault',
  width: 90,
}];

const trendColumns = [{
  title: '日期',
  dataIndex: 'date',
  width: 140,
}, {
  title: '记录数',
  dataIndex: 'total',
  width: 100,
}, {
  title: '其中转故障',
  dataIndex: 'converted_fault',
  width: 120,
}];

function TotalsCards({totals}) {
  return (
    <Row gutter={12}>
      <Col span={4}>
        <Card size="small"><Statistic title="运行记录总数" value={totals.total}/></Card>
      </Col>
      <Col span={4}>
        <Card size="small"><Statistic title="跟进中" value={totals.following_up}/></Card>
      </Col>
      <Col span={4}>
        <Card size="small"><Statistic title="转故障" value={totals.converted_fault}/></Card>
      </Col>
      <Col span={4}>
        <Card size="small">
          <Statistic
            title="长期未关闭（跟进中）"
            value={totals.stale_open}
            suffix={`/ ${totals.stale_days || STATS_STALE_DAYS_DEFAULT}天`}
          />
        </Card>
      </Col>
      <Col span={24} style={{marginTop: 12}}>
        <Card size="small">
          <Statistic
            title="平均处理时长（小时，录入到首次完成跟进）"
            value={totals.avg_resolve_hours === null || totals.avg_resolve_hours === undefined
              ? '-' : totals.avg_resolve_hours}
          />
        </Card>
      </Col>
    </Row>
  );
}

@observer
class RecordStatistics extends React.Component {
  componentDidMount() {
    store.fetchStatistics();
  }

  render() {
    const stats = store.statistics;
    return (
      <Spin spinning={store.isStatisticsFetching}>
        <div style={{marginBottom: 12}}>
          <Select
            allowClear
            placeholder="记录类型（默认异常事件）"
            style={{width: 180, marginRight: 8}}
            value={store.f_stats_record_type}
            onChange={v => {
              store.f_stats_record_type = v;
              store.fetchStatistics();
            }}
          >
            {RUNTIME_RECORD_TYPE_OPTIONS.map(item => (
              <Select.Option value={item.value} key={item.value}>{item.label}</Select.Option>
            ))}
          </Select>
          <RangePicker
            showTime={{format: 'HH:mm'}}
            format="YYYY-MM-DD HH:mm"
            style={{width: 380, marginRight: 8}}
            value={store.f_stats_range}
            onChange={v => store.f_stats_range = v}
            placeholder={['发生时间起', '发生时间止']}
          />
          <Button type="primary" onClick={() => store.fetchStatistics()}>查询</Button>
        </div>
        {!stats ? (
          <Empty description="暂无统计数据"/>
        ) : (
          <div>
            <TotalsCards totals={stats.totals}/>
            <Card size="small" title="状态维度" style={{marginTop: 12}}>
              {Object.keys(stats.by_status || {}).length ? (
                Object.entries(stats.by_status).map(([status, count]) => (
                  <Tag key={status} color={RUNTIME_STATUS_COLOR[status]}>
                    {RUNTIME_STATUS_TEXT[status] || status}：{count}
                  </Tag>
                ))
              ) : <span>无记录</span>}
            </Card>
            <Card size="small" title="系统维度" style={{marginTop: 12}}>
              <Table
                rowKey="system"
                size="small"
                pagination={false}
                dataSource={stats.by_system || []}
                columns={systemColumns}
                locale={{emptyText: '所选范围内无运行记录'}}
              />
            </Card>
            <Card size="small" title="时间趋势（按自然日）" style={{marginTop: 12}}>
              {stats.trend && stats.trend.length ? (
                <Table
                  rowKey="date"
                  size="small"
                  pagination={{pageSize: 10}}
                  dataSource={stats.trend}
                  columns={trendColumns}
                />
              ) : (
                <span>时间范围超出趋势展示限制（62 天）或范围内无记录</span>
              )}
            </Card>
          </div>
        )}
      </Spin>
    );
  }
}

export default observer(RecordStatistics);
