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
    const errorCount = (r.results || []).filter((x) => x.status === 'error').length;
    const allPass = r.total_problems === 0 && errorCount === 0;
    return (
      <Alert
        type={allPass ? 'success' : 'warning'}
        showIcon
        icon={allPass ? <CheckCircleOutlined /> : <CloseCircleOutlined />}
        message={
          allPass
            ? `全部通过（${r.passed}/${r.total_checks} 项检查正常）`
            : `发现 ${r.total_problems} 个问题（通过 ${r.passed}/${r.total_checks} 项，异常 ${r.failed} 项，执行失败 ${errorCount} 项）`
        }
        description={`检查时间：${r.checked_at}`}
        style={{ marginBottom: 16 }}
      />
    );
  };

  renderCheckCard = (check) => {
    const isPass = check.status === 'pass';
    const isError = check.status === 'error';
    const details = check.details || [];
    const columns = [
      { title: '类型', dataIndex: 'model', key: 'model', width: 140 },
      { title: 'ID', dataIndex: 'id', key: 'id', width: 80 },
      { title: '名称', dataIndex: 'name', key: 'name', ellipsis: true },
      {
        title: '文件路径',
        dataIndex: 'file_path',
        key: 'file_path',
        width: 360,
        ellipsis: true,
        render: (value, record) => {
          const path = value || record.rel_path || '-';
          return path === '-' ? path : (
            <Text ellipsis={{ tooltip: path }} copyable={{ text: path }}>
              {path}
            </Text>
          );
        },
      },
      { title: '问题描述', dataIndex: 'issue', key: 'issue' },
    ];
    return (
      <Card
        key={check.check}
        size="small"
        style={{ marginBottom: 12 }}
        title={
          <Space>
            <Tag color={isPass ? 'success' : isError ? 'warning' : 'error'} style={{ margin: 0 }}>
              {isPass ? '通过' : isError ? '执行失败' : '异常'}
            </Tag>
            <Text strong>{check.check}</Text>
          </Space>
        }
        extra={
          <Text type="secondary">
            {check.description || ''}
            {check.count > 0 && `（共 ${check.count} 条）`}
            {check.checked != null && ` · 采样 ${check.checked} 条`}
          </Text>
        }
      >
        {isError ? (
          <Alert
            type="error"
            showIcon
            message="检查执行失败"
            description={check.error || '未知错误'}
          />
        ) : !isPass && details.length > 0 ? (
          <Table
            size="small"
            columns={columns}
            dataSource={details}
            rowKey={(r, index) => `${r.model}-${r.id || r.file_path || r.rel_path || index}`}
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
