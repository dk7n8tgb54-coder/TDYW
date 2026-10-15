/**
 * Copyright (c) OpenSpug Organization. https://github.com/openspug/spug
 * Released under the AGPL-3.0 License.
 */
/**
 * 设备全生命周期——运行处置记录只读统计视图（2026-10-11 合并改造）。
 * 统计统一主表三类记录：可按记录类型筛选（未选时统计全部类型）。
 * 2026-10-14 体验二轮：四个核心指标（记录总数/进行中/超期未关闭/平均处理
 * 时长）并排便于比较，进行中与平均处理时长附口径说明；时间趋势改为柱状
 * 可视化（柱顶标数值、悬停看逐日设备故障数，无数据/超范围有空态说明）；
 * 状态/类型维度与系统维度保留。不堆叠装饰性卡片。
 * 查询时机：由 index.handleTabChange 在切换到本页签时触发，页内筛选后
 * 点"查询"重新统计；加载失败显式提示并可重试（错误 toast 由 http 拦截器
 * 统一弹出）。统计只使用统一记录数据（巡视、维护、配置变更、升级不进入
 * 本统计）；时间范围用发生时间起止筛选（截止时间包含所选整分钟）。
 */
import React from 'react';
import {observer} from 'mobx-react';
import {DatePicker, Table, Tag, Card, Spin, Statistic, Row, Col, Empty,
  Button, Select, Alert, Tooltip} from 'antd';
import {QuestionCircleOutlined} from '@ant-design/icons';
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

// 时间趋势柱状图：纯 CSS 实现（不引入图表依赖），每根柱顶标当日记录数，
// 悬停提示该日设备故障数；范围内无记录或超过 62 天显示空态说明。
// 柱高按当日记录数/max 归一，0 记录显示浅灰底格
function TrendChart({trend}) {
  if (!trend || !trend.length) {
    return <span>时间范围超出趋势展示限制（62 天）或范围内无记录</span>;
  }
  const max = Math.max(...trend.map(item => item.total), 1);
  const labelStep = Math.max(1, Math.ceil(trend.length / 10));
  return (
    <div>
      <div style={{display: 'flex', alignItems: 'flex-end', gap: 2, height: 170}}>
        {trend.map(item => {
          const barHeight = item.total > 0
            ? Math.max(4, Math.round((item.total / max) * 130)) : 2;
          return (
            <div
              key={item.date}
              style={{flex: 1, minWidth: 5, textAlign: 'center'}}
              title={`${item.date}：共 ${item.total} 条（其中设备故障 ${item.fault} 条）`}
            >
              <div style={{fontSize: 12, lineHeight: '16px'}}>
                {item.total > 0 ? item.total : ''}
              </div>
              <div style={{
                height: barHeight,
                background: item.total > 0 ? '#5b8ff6' : '#f0f0f0',
                width: '70%',
                margin: '0 auto',
                borderRadius: 2,
              }}/>
            </div>
          );
        })}
      </div>
      <div style={{display: 'flex', gap: 2, marginTop: 4}}>
        {trend.map((item, idx) => (
          <div
            key={item.date}
            style={{
              flex: 1, minWidth: 5, fontSize: 11,
              color: 'rgba(0, 0, 0, 0.45)', textAlign: 'center',
              overflow: 'hidden', whiteSpace: 'nowrap',
            }}
          >
            {idx % labelStep === 0 ? item.date.slice(5) : ''}
          </div>
        ))}
      </div>
      <div style={{marginTop: 8, color: 'rgba(0, 0, 0, 0.45)', fontSize: 12}}>
        按自然日统计范围内每日新增记录数；悬停柱子查看该日设备故障数。
      </div>
    </div>
  );
}

function TotalsCards({totals}) {
  const inProgress = (totals.following_up || 0) + (totals.handling_fault || 0);
  return (
    <Row gutter={12}>
      <Col span={6}>
        <Card size="small"><Statistic title="记录总数" value={totals.total}/></Card>
      </Col>
      <Col span={6}>
        <Card size="small">
          <Statistic
            title={(
              <span>
                进行中
                <Tooltip title="跟进中的异常事件 + 处置中的设备故障，即待办口径">
                  <QuestionCircleOutlined style={{marginLeft: 4, color: 'rgba(0, 0, 0, 0.45)'}}/>
                </Tooltip>
              </span>
            )}
            value={inProgress}
            suffix={
              <span style={{fontSize: 12, color: 'rgba(0, 0, 0, 0.45)'}}>
                （跟进中 {totals.following_up || 0} / 处置中故障 {totals.handling_fault || 0}）
              </span>
            }
          />
        </Card>
      </Col>
      <Col span={6}>
        <Card size="small">
          <Statistic
            title={(
              <span>
                超期未关闭
                <Tooltip title="跟进中超过 stale_days 天仍未完成的异常事件（跨时间范围统计积压）">
                  <QuestionCircleOutlined style={{marginLeft: 4, color: 'rgba(0, 0, 0, 0.45)'}}/>
                </Tooltip>
              </span>
            )}
            value={totals.stale_open}
            suffix={`/ ${totals.stale_days || STATS_STALE_DAYS_DEFAULT}天`}
          />
        </Card>
      </Col>
      <Col span={6}>
        <Card size="small">
          <Statistic
            title={(
              <span>
                平均处理时长（小时）
                <Tooltip title="异常事件从录入到首次完成跟进的平均时长；重新跟进不重复计入">
                  <QuestionCircleOutlined style={{marginLeft: 4, color: 'rgba(0, 0, 0, 0.45)'}}/>
                </Tooltip>
              </span>
            )}
            value={totals.avg_resolve_hours === null || totals.avg_resolve_hours === undefined
              ? '-' : totals.avg_resolve_hours}
            suffix={
              totals.resolved_count ? (
                <span style={{fontSize: 12, color: 'rgba(0, 0, 0, 0.45)'}}>
                  {totals.resolved_count} 条参与
                </span>
              ) : null
            }
          />
        </Card>
      </Col>
    </Row>
  );
}

// 组件由文件末尾 export default observer(...) 统一包裹，不叠加装饰器
// （双重 observer 会触发 mobx 警告）
class RecordStatistics extends React.Component {
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
        {store.statsError && (
          <Alert
            type="warning"
            showIcon
            message="统计加载失败，以下可能为上次结果"
            action={
              <Button size="small" onClick={() => store.fetchStatistics()}>重试</Button>
            }
            style={{marginBottom: 12}}
          />
        )}
        {!stats ? (
          <Empty description={store.statsError ? '统计加载失败，请点击重试' : '暂无统计数据'}/>
        ) : (
          <div>
            <TotalsCards totals={stats.totals}/>
            <Row gutter={12} style={{marginTop: 12}}>
              <Col span={12}>
                <Card size="small" title="状态维度">
                  {Object.keys(stats.by_status || {}).length ? (
                    <div>
                      {Object.entries(stats.by_status).map(([status, count]) => (
                        <Tag key={status} color={RECORD_STATUS_COLOR[status]}>
                          {RECORD_STATUS_TEXT[status] || status}：{count}
                        </Tag>
                      ))}
                    </div>
                  ) : <span>无记录</span>}
                </Card>
              </Col>
              <Col span={12}>
                <Card size="small" title="类型维度">
                  {Object.keys(stats.by_type || {}).length ? (
                    <div>
                      {Object.entries(stats.by_type).map(([recordType, count]) => (
                        <Tag key={recordType} color={RECORD_TYPE_COLOR[recordType]}>
                          {RECORD_TYPE_TEXT[recordType] || recordType}：{count}
                        </Tag>
                      ))}
                    </div>
                  ) : <span>无记录</span>}
                </Card>
              </Col>
            </Row>
            <Card size="small" title="时间趋势（按自然日）" style={{marginTop: 12}}>
              <TrendChart trend={stats.trend}/>
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
          </div>
        )}
      </Spin>
    );
  }
}

export default observer(RecordStatistics);
