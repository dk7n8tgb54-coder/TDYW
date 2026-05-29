/**
 * Copyright (c) OpenSpug Organization. https://github.com/openspug/spug
 * Copyright (c) <spug.dev@gmail.com>
 * Released under the AGPL-3.0 License.
 */
import React, { useEffect, useCallback, useRef } from 'react';
import { observer } from 'mobx-react';
import { 
  Card, 
  Table, 
  Button, 
  Space, 
  Input, 
  Select, 
  Badge, 
  Tooltip, 
  Statistic,
  Row,
  Col,
  Alert,
  Empty,
  Breadcrumb as AntBreadcrumb
} from 'antd';
import { 
  RedoOutlined, 
  DeleteOutlined, 
  UndoOutlined,
  WarningOutlined,
  HistoryOutlined,
  DatabaseOutlined,
  ClockCircleOutlined,
  ArrowLeftOutlined,
  FolderOpenOutlined
} from '@ant-design/icons';
import { Breadcrumb } from 'components';
import RestoreModal from './RestoreModal';
import DeleteModal from './DeleteModal';
import DeleteProgressModal from './DeleteProgressModal';
import store from './store';
import * as service from './service';
import styles from './index.module.less';

const { Option } = Select;
const { Search } = Input;

const RecycleBinIndex = observer(function () {
  // 初始化加载数据
  useEffect(() => {
    store.refresh();
    return () => {
      store.reset();
    };
  }, []);

  // 处理进入文件夹
  const handleEnterFolder = useCallback((record) => {
    if (record.type === 'folder') {
      store.enterFolder(record);
    }
  }, []);

  // 处理返回上级
  const handleGoBack = useCallback(() => {
    store.goToParentFolder();
  }, []);

  // 处理返回回收站根目录
  const handleExitFolder = useCallback(() => {
    store.exitFolder();
  }, []);

  // 主列表表格列定义
  const mainColumns = [
    {
      title: '名称',
      dataIndex: 'name',
      key: 'name',
      ellipsis: true,
      render: (text, record) => {
        const isFolder = record.type === 'folder';
        return (
          <Space>
            {isFolder ? (
              <span className={styles.folderIcon}>📁</span>
            ) : (
              service.FileIconMap[service.getFileIcon(record.file_type, record.name)] || service.FileIconMap.file
            )}
            <div className={styles.fileName}>
              <div className={styles.displayName} title={text}>
                {isFolder ? (
                  <Button 
                    type="link" 
                    className={styles.folderNameButton}
                    onClick={() => handleEnterFolder(record)}
                  >
                    <strong>{text}</strong>
                  </Button>
                ) : (
                  record.display_name || text
                )}
              </div>
              {!isFolder && (
                <div className={styles.originalName} title={record.name}>{record.name}</div>
              )}
            </div>
          </Space>
        );
      },
    },
    {
      title: '原位置',
      dataIndex: 'original_folder',
      key: 'original_folder',
      width: 150,
      ellipsis: true,
      render: (folder, record) => {
        const isFolder = record.type === 'folder';
        const location = isFolder ? record.original_parent : folder;
        return location ? (
          <Tooltip title={location.name}>
            <span className={styles.folderPath}>{location.name}</span>
          </Tooltip>
        ) : (
          <span className={styles.rootFolder}>根目录</span>
        );
      },
    },
    {
      title: '空间',
      dataIndex: 'space',
      key: 'space',
      width: 100,
      render: (space) => (
        <Badge 
          status={space === 'private' ? 'default' : 'processing'} 
          text={space === 'private' ? '私有空间' : '公共空间'} 
        />
      ),
    },
    {
      title: '大小',
      dataIndex: 'file_size',
      key: 'file_size',
      width: 120,
      render: (size, record) => {
        const isFolder = record.type === 'folder';
        const displaySize = isFolder ? record.total_size : size;
        return service.formatFileSize(displaySize);
      },
    },
    {
      title: '内容统计',
      key: 'content_stats',
      width: 120,
      render: (_, record) => {
        if (record.type !== 'folder') return '-';
        return (
          <Tooltip title={`${record.file_count || 0} 个文件`}>
            <span className={styles.contentStats}>
              {record.file_count > 0 ? `${record.file_count} 个文件` : '空文件夹'}
            </span>
          </Tooltip>
        );
      },
    },
    {
      title: '删除时间',
      dataIndex: 'deleted_at',
      key: 'deleted_at',
      width: 180,
      render: (time) => {
        if (!time) return '-';
        const date = new Date(time);
        if (isNaN(date.getTime())) return '-';
        return (
          <Space size="small">
            <HistoryOutlined />
            {date.toLocaleString('zh-CN')}
          </Space>
        );
      },
    },
    {
      title: '剩余天数',
      dataIndex: 'retention_days_left',
      key: 'retention_days_left',
      width: 120,
      render: (days) => {
        const isUrgent = days <= 7;
        return (
          <Tooltip title={isUrgent ? '即将自动清理' : `${days}天后自动清理`}>
            <Space size="small">
              {isUrgent && <WarningOutlined style={{ color: '#ff4d4f' }} />}
              <span className={isUrgent ? styles.urgentDays : styles.normalDays}>
                {days} 天
              </span>
            </Space>
          </Tooltip>
        );
      },
    },
    {
      title: '操作',
      key: 'action',
      width: 180,
      fixed: 'right',
      render: (_, record) => (
        <Space size="small">
          {record.type === 'folder' && (
            <Tooltip title="查看内容">
              <Button
                type="text"
                icon={<FolderOpenOutlined />}
                onClick={() => handleEnterFolder(record)}
              />
            </Tooltip>
          )}
          <Tooltip title="恢复">
            <Button
              type="text"
              icon={<UndoOutlined />}
              onClick={() => handleSingleRestore(record)}
            />
          </Tooltip>
          <Tooltip title="彻底删除">
            <Button
              type="text"
              danger
              icon={<DeleteOutlined />}
              onClick={() => handleSingleDelete(record)}
            />
          </Tooltip>
        </Space>
      ),
    },
  ];

  // 文件夹内容表格列定义
  const folderContentColumns = [
    {
      title: '名称',
      dataIndex: 'name',
      key: 'name',
      ellipsis: true,
      render: (text, record) => {
        const isFolder = record.type === 'folder';
        return (
          <Space>
            {isFolder ? (
              <span className={styles.folderIcon}>📁</span>
            ) : (
              service.FileIconMap[service.getFileIcon(record.file_type, record.name)] || service.FileIconMap.file
            )}
            <div className={styles.fileName}>
              <div className={styles.displayName} title={text}>
                {isFolder ? (
                  <Button 
                    type="link" 
                    className={styles.folderNameButton}
                    onClick={() => store.enterSubFolder(record)}
                  >
                    <strong>{text}</strong>
                  </Button>
                ) : (
                  record.display_name || text
                )}
              </div>
              {!isFolder && (
                <div className={styles.originalName} title={record.name}>{record.name}</div>
              )}
            </div>
          </Space>
        );
      },
    },
    {
      title: '类型',
      dataIndex: 'type',
      key: 'type',
      width: 100,
      render: (type, record) => {
        if (type === 'folder') {
          const subCount = record.subfolder_count || 0;
          const fileCount = record.file_count || 0;
          return (
            <Tooltip title={`${subCount} 个子文件夹, ${fileCount} 个文件`}>
              <span>文件夹</span>
            </Tooltip>
          );
        }
        // 使用格式化函数显示友好的文件类型
        const formattedType = service.formatFileType(record.file_type, record.name);
        return <span>{formattedType}</span>;
      },
    },
    {
      title: '大小',
      dataIndex: 'file_size',
      key: 'file_size',
      width: 120,
      render: (size, record) => {
        if (record.type === 'folder') return '-';
        return service.formatFileSize(size);
      },
    },
    {
      title: '删除时间',
      dataIndex: 'deleted_at',
      key: 'deleted_at',
      width: 180,
      render: (time) => {
        if (!time) return '-';
        const date = new Date(time);
        if (isNaN(date.getTime())) return '-';
        return (
          <Space size="small">
            <HistoryOutlined />
            {date.toLocaleString('zh-CN')}
          </Space>
        );
      },
    },
    {
      title: '操作',
      key: 'action',
      width: 180,
      fixed: 'right',
      render: (_, record) => (
        <Space size="small">
          {record.type === 'folder' && (
            <Tooltip title="进入文件夹">
              <Button
                type="text"
                icon={<FolderOpenOutlined />}
                onClick={() => store.enterSubFolder(record)}
              />
            </Tooltip>
          )}
          <Tooltip title="恢复">
            <Button
              type="text"
              icon={<UndoOutlined />}
              onClick={() => handleSingleRestore(record)}
            />
          </Tooltip>
          <Tooltip title="彻底删除">
            <Button
              type="text"
              danger
              icon={<DeleteOutlined />}
              onClick={() => handleSingleDelete(record)}
            />
          </Tooltip>
        </Space>
      ),
    },
  ];

  // 搜索防抖
  const searchTimerRef = useRef(null);
  
  const handleSearch = useCallback((value) => {
    store.setKeyword(value);
    
    if (searchTimerRef.current) {
      clearTimeout(searchTimerRef.current);
    }
    
    searchTimerRef.current = setTimeout(() => {
      store.doSearch();
    }, 300);
  }, []);
  
  useEffect(() => {
    return () => {
      if (searchTimerRef.current) {
        clearTimeout(searchTimerRef.current);
      }
    };
  }, []);

  const handleSpaceChange = useCallback((value) => {
    store.setSpace(value);
  }, []);

  const handleRefresh = useCallback(() => {
    if (store.currentFolder) {
      store.fetchFolderContent();
    } else {
      store.refresh();
    }
  }, []);

  const handleBatchRestore = useCallback(() => {
    store.showRestoreModal();
  }, []);

  const handleBatchDelete = useCallback(() => {
    store.showDeleteModal();
  }, []);

  const handleSingleRestore = useCallback((record) => {
    store.setSelectedRows([record.id], [record]);
    store.showRestoreModal();
  }, []);

  const handleSingleDelete = useCallback((record) => {
    store.setSelectedRows([record.id], [record]);
    store.showDeleteModal();
  }, []);

  // 行选择配置
  const rowSelection = {
    selectedRowKeys: store.selectedRowKeys,
    onChange: store.setSelectedRows,
    preserveSelectedRowKeys: true,
  };

  // 主列表分页配置
  const mainPagination = {
    current: store.page,
    pageSize: store.pageSize,
    total: store.total,
    showSizeChanger: true,
    showQuickJumper: true,
    showTotal: (total) => `共 ${total} 条`,
    pageSizeOptions: ['10', '20', '50', '100'],
    onChange: (page) => {
      store.setPage(page);
      store.refresh();
    },
    onShowSizeChange: (current, size) => {
      store.setPageSize(size);
      store.refresh();
    },
  };

  // 文件夹内容分页配置
  const folderPagination = {
    current: store.folderContentPage,
    pageSize: store.folderContentPageSize,
    total: store.folderContentTotal,
    showSizeChanger: true,
    showQuickJumper: true,
    showTotal: (total) => `共 ${total} 条`,
    pageSizeOptions: ['20', '50', '100'],
    onChange: (page) => {
      store.setFolderContentPage(page);
      store.fetchFolderContent();
    },
  };

  // 是否在文件夹浏览模式
  const isInFolder = !!store.currentFolder;

  // 渲染面包屑导航（文件夹浏览模式）
  const renderFolderBreadcrumb = () => {
    if (!isInFolder) return null;
    
    const items = [
      <AntBreadcrumb.Item key="root">
        <Button type="link" onClick={handleExitFolder} className={styles.breadcrumbLink}>
          回收站
        </Button>
      </AntBreadcrumb.Item>
    ];
    
    // 父级链
    if (store.currentFolder.parent_chain) {
      store.currentFolder.parent_chain.forEach((parent, index) => {
        items.push(
          <AntBreadcrumb.Item key={`parent-${index}`}>
            <Button 
              type="link" 
              onClick={() => {
                // 构建新的parent_chain（截断到当前父级）
                const newChain = store.currentFolder.parent_chain.slice(0, index);
                store.currentFolder = {
                  ...store.currentFolder,
                  id: parent.id,
                  name: parent.name,
                  parent_chain: newChain,
                };
                store.folderContentPage = 1;
                store.fetchFolderContent();
              }}
              className={styles.breadcrumbLink}
            >
              {parent.name}
            </Button>
          </AntBreadcrumb.Item>
        );
      });
    }
    
    // 当前文件夹
    items.push(
      <AntBreadcrumb.Item key="current">
        <strong>{store.currentFolder.name}</strong>
      </AntBreadcrumb.Item>
    );
    
    return (
      <div className={styles.folderBreadcrumb}>
        <AntBreadcrumb separator=">">{items}</AntBreadcrumb>
      </div>
    );
  };

  return (
    <div className={styles.container}>
      <Breadcrumb extra={
        <Space>
          {!isInFolder && (
            <Search
              placeholder="搜索文件名"
              allowClear
              style={{ width: 250 }}
              onSearch={handleSearch}
            />
          )}
          {!isInFolder && (
            <Select
              value={store.space || 'all'}
              onChange={handleSpaceChange}
              style={{ width: 120 }}
            >
              <Option value="all">全部空间</Option>
              <Option value="private">私有空间</Option>
              <Option value="public">公共空间</Option>
            </Select>
          )}
          <Button
            icon={<RedoOutlined />}
            onClick={handleRefresh}
            loading={store.loading}
          >
            刷新
          </Button>
        </Space>
      }>
        <Breadcrumb.Item>资料库</Breadcrumb.Item>
        <Breadcrumb.Item>回收站</Breadcrumb.Item>
      </Breadcrumb>

      {/* 文件夹浏览模式的面包屑和返回按钮 */}
      {isInFolder && (
        <Card size="small" className={styles.folderHeaderCard}>
          <Space direction="vertical" style={{ width: '100%' }}>
            <Space>
              <Button 
                icon={<ArrowLeftOutlined />} 
                onClick={handleGoBack}
              >
                返回上级
              </Button>
              <Button onClick={handleExitFolder}>
                返回回收站
              </Button>
            </Space>
            {renderFolderBreadcrumb()}
            {store.currentFolder && (
              <div className={styles.folderStats}>
                <Space size="large">
                  <span>
                    <strong>{store.currentFolder.name}</strong>
                  </span>
                  <span>
                    文件数: <strong>{store.currentFolder.total_files || 0}</strong>
                  </span>
                  <span>
                    文件夹数: <strong>{store.currentFolder.total_folders || 0}</strong>
                  </span>
                  <span>
                    总大小: <strong>{service.formatFileSize(store.currentFolder.total_size || 0)}</strong>
                  </span>
                </Space>
              </div>
            )}
          </Space>
        </Card>
      )}

      {/* 统计卡片 - 仅在根目录显示 */}
      {!isInFolder && (
        <Row gutter={16} className={styles.statsRow}>
          <Col span={6}>
            <Card loading={store.statsLoading} size="small">
              <Statistic
                title="总文件数"
                value={store.stats.total_count}
                prefix={<DatabaseOutlined />}
                valueStyle={{ fontSize: 24 }}
              />
            </Card>
          </Col>
          <Col span={6}>
            <Card loading={store.statsLoading} size="small">
              <Statistic
                title="总占用空间"
                value={service.formatFileSize(store.stats.total_size)}
                valueStyle={{ fontSize: 24 }}
              />
            </Card>
          </Col>
          <Col span={6}>
            <Card loading={store.statsLoading} size="small">
              <Statistic
                title="即将清理"
                value={store.stats.expiring_soon}
                prefix={<ClockCircleOutlined />}
                valueStyle={{ 
                  fontSize: 24, 
                  color: store.stats.expiring_soon > 0 ? '#ff4d4f' : undefined 
                }}
                suffix="个"
              />
            </Card>
          </Col>
          <Col span={6}>
            <Card loading={store.statsLoading} size="small">
              <Statistic
                title="保留期限"
                value={store.stats.retention_days}
                suffix="天"
                valueStyle={{ fontSize: 24 }}
              />
            </Card>
          </Col>
        </Row>
      )}

      {/* 提示信息 */}
      {!isInFolder && store.stats.expiring_soon > 0 && (
        <Alert
          message={`注意：有 ${store.stats.expiring_soon} 个文件将在7天内被自动清理，请及时恢复或备份重要文件`}
          type="warning"
          showIcon
          closable
          className={styles.alert}
        />
      )}

      {/* 表格卡片 */}
      <Card className={styles.tableCard}>
        {/* 批量操作栏 */}
        {store.hasSelected && (
          <div className={styles.batchBar}>
            <Space>
              <span className={styles.selectedInfo}>
                已选择 <strong>{store.selectedCount}</strong> 项
                （共 {service.formatFileSize(store.selectedTotalSize)}）
              </span>
              <Button
                type="primary"
                icon={<UndoOutlined />}
                onClick={handleBatchRestore}
              >
                批量恢复
              </Button>
              <Button
                danger
                icon={<DeleteOutlined />}
                onClick={handleBatchDelete}
              >
                彻底删除
              </Button>
            </Space>
          </div>
        )}

        {/* 数据表格 */}
        <Table
          rowKey="id"
          columns={isInFolder ? folderContentColumns : mainColumns}
          dataSource={isInFolder ? store.folderContent : store.items}
          loading={store.loading}
          pagination={isInFolder ? folderPagination : mainPagination}
          rowSelection={rowSelection}
          scroll={{ x: 1200 }}
          locale={{
            emptyText: (
              <Empty
                image={Empty.PRESENTED_IMAGE_SIMPLE}
                description={
                  isInFolder ? (
                    <span>
                      该文件夹为空<br />
                      没有已删除的文件或子文件夹
                    </span>
                  ) : (
                    <span>
                      回收站为空<br />
                      删除的文件将在这里保留{store.stats.retention_days}天
                    </span>
                  )
                }
              />
            ),
          }}
        />
      </Card>

      {/* 恢复弹窗 */}
      <RestoreModal />

      {/* 删除弹窗 */}
      <DeleteModal />

      {/* 删除进度弹窗 */}
      <DeleteProgressModal />
    </div>
  );
});

export default RecycleBinIndex;
