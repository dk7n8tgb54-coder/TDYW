/**
 * 数据质量巡检页面
 */
import React from 'react';
import { observer } from 'mobx-react';
import { Button, Card, Table, Tag, Typography, Space, Spin, Alert, Empty } from 'antd';
import { PlayCircleOutlined, CheckCircleOutlined, CloseCircleOutlined } from '@ant-design/icons';
import { AuthDiv, Breadcrumb } from 'components';
import store from './store';

const { Title, Text } = Typography;

@observer
class DataQualityIndex extends React.Component {
  componentDidMount() {
    store.runCheck();
  }

  renderSummary = () => {
    const r = store.results;
    if (!r) return null;
    const allPass = r.total_problems === 0;
    return (
      <Alert
        type={allPass ? 'success' : 'warning'}
        showIcon
        icon={allPass ? <CheckCircleOutlined /> : <CloseCircleOutlined />}
        message={
          allPass
            ? `全部通过（${r.passed}/${r.total_checks} 项检查）`
            : `发现 ${r.total_problems} 个问题（通过 ${r.passed}/${r.total_checks} 项，失败 ${r.failed} 项）`
        }
        description={`检查时间：${r.checked_at}`}
        style={{ marginBottom: 16 }}
      />
    );
  };

  renderCheckCard = (check) => {
    const isPass = check.status === 'pass';
    const details = check.details || [];
    const columns = [
      { title: '模型', dataIndex: 'model', key: 'model', width: 180 },
      { title: 'ID', dataIndex: 'id', key: 'id', width: 80 },
      { title: '名称', dataIndex: 'name', key: 'name', ellipsis: true },
      { title: '问题描述', dataIndex: 'issue', key: 'issue' },
    ];
    return (
      <Card
        key={check.check}
        size="small"
        style={{ marginBottom: 12 }}
        title={
          <Space>
            <Tag color={isPass ? 'success' : 'error'} style={{ margin: 0 }}>
              {isPass ? 'PASS' : 'FAIL'}
            </Tag>
            <Text strong>{check.check}</Text>
          </Space>
        }
        extra={
          <Text type="secondary">
            {check.description || ''}
            {check.count > 0 && ` (${check.count})`}
            {check.checked != null && ` · 采样 ${check.checked} 条`}
          </Text>
        }
      >
        {!isPass && details.length > 0 ? (
          <Table
            size="small"
            columns={columns}
            dataSource={details}
            rowKey={(r) => `${r.model}-${r.id}`}
            pagination={false}
            scroll={{ y: 300 }}
          />
        ) : (
          <Text type="secondary">无异常</Text>
        )}
        {check.truncated && (
          <Text type="secondary" style={{ display: 'block', marginTop: 8 }}>
            还有 {check.count - details.length} 条未显示...
          </Text>
        )}
      </Card>
    );
  };

  render() {
    const { loading, results } = store;
    return (
      <AuthDiv auth="system.alert.view">
        <Breadcrumb>
          <Breadcrumb.Item>运维管理</Breadcrumb.Item>
          <Breadcrumb.Item>数据质量巡检</Breadcrumb.Item>
        </Breadcrumb>
        <div style={{ marginBottom: 16 }}>
          <Space>
            <Button
              type="primary"
              icon={<PlayCircleOutlined />}
              loading={loading}
              onClick={() => store.runCheck()}
            >
              重新巡检
            </Button>
          </Space>
        </div>
        <Spin spinning={loading}>
          {results ? (
            <>
              {this.renderSummary()}
              {results.results.map((check) => this.renderCheckCard(check))}
            </>
          ) : !loading ? (
            <Empty description="点击上方按钮开始巡检" />
          ) : null}
        </Spin>
      </AuthDiv>
    );
  }
}

export default DataQualityIndex;
