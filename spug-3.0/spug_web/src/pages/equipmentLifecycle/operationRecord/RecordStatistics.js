/**
 * Copyright (c) OpenSpug Organization. https://github.com/openspug/spug
 * Released under the AGPL-3.0 License.
 */
/**
 * 设备全生命周期——运行与故障记录只读统计视图（2026-10-11 合并改造）。
 * 统计统一主表三类记录：可按记录类型筛选（未选时统计全部类型）。
 * 展示：总数/跟进中/处置中故障卡片、长期未关闭（仅跟进中超期）、
 * 平均处理时长（异常事件录入到首次完成跟进）、状态维度、类型维度、
 * 系统维度、时间趋势（按自然日）。统计只使用统一记录数据
 * （巡视、维护、配置变更、升级不进入本统计）；时间范围用发生时间起止筛选。
 */
import React from 'react';
import {observer} from 'mobx-react';
import {DatePicker, Table, Tag, Card, Spin, Statistic, Row, Col, Empty, Button, Select} from 'antd';
import store from './store';
import {
  RECORD_STATUS_TEXT, RECORD_STATUS_COLOR,
  RECORD_TYPE_OPTIONS, RECORD_TYPE_TEXT, RECORD_TYPE_COLOR,
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
  title: '处置中故障',
  dataIndex: 'handling_fault',
  width: 100,
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
  title: '其中正式故障',
  dataIndex: 'fault',
  width: 120,
}];

function TotalsCards({totals}) {
  return (
    <Row gutter={12}>
      <Col span={4}>
        <Card size="small"><Statistic title="记录总数" value={totals.total}/></Card>
      </Col>
      <Col span={4}>
        <Card size="small"><Statistic title="跟进中" value={totals.following_up}/></Card>
      </Col>
      <Col span={4}>
        <Card size="small"><Statistic title="处置中故障" value={totals.handling_fault}/></Card>
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
            placeholder="记录类型（默认全部）"
            style={{width: 180, marginRight: 8}}
            value={store.f_stats_record_type}
            onChange={v => {
              store.f_stats_record_type = v;
              store.fetchStatistics();
            }}
          >
            {RECORD_TYPE_OPTIONS.map(item => (
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
                  <Tag key={status} color={RECORD_STATUS_COLOR[status]}>
                    {RECORD_STATUS_TEXT[status] || status}：{count}
                  </Tag>
                ))
              ) : <span>无记录</span>}
            </Card>
            <Card size="small" title="类型维度" style={{marginTop: 12}}>
              {Object.keys(stats.by_type || {}).length ? (
                Object.entries(stats.by_type).map(([recordType, count]) => (
                  <Tag key={recordType} color={RECORD_TYPE_COLOR[recordType]}>
                    {RECORD_TYPE_TEXT[recordType] || recordType}：{count}
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
                locale={{emptyText: '所选范围内无记录'}}
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
