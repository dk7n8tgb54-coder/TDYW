/**
 * Copyright (c) OpenSpug Organization. https://github.com/openspug/spug
 * Copyright (c) <spug.dev@gmail.com>
 * Released under the AGPL-3.0 License.
 */
import React from 'react';
import { observer } from 'mobx-react';
import { Button, Space, Breadcrumb as AntdBreadcrumb, Badge, Popover, Radio, message } from 'antd';
import { ArrowLeftOutlined, UploadOutlined, CloudUploadOutlined, LeftOutlined, RightOutlined, FolderAddOutlined, AppstoreOutlined, UnorderedListOutlined } from '@ant-design/icons';
import { Breadcrumb as SpugBreadcrumb } from 'components';
import Explorer from './Explorer';
import UploadPanel from './UploadPanel';
import FolderTree from './FolderTree';
import SearchBox from './components/SearchBox';
import DiskStatus from './components/DiskStatus';
import navigationStore from './stores/navigation';
import uploadUIStore from './stores/upload/ui';
import { uploadCoreStore } from './stores';
import './Explorer.module.less';

const DocumentIndex = observer(function () {
  const fileInputRef = React.useRef(null);
  const folderInputRef = React.useRef(null);
  const explorerRef = React.useRef(null);
  const folderTreeRef = React.useRef(null);
  const [detailPanelExpanded, setDetailPanelExpanded] = React.useState(false);
  const [viewMode, setViewMode] = React.useState('list'); // list, grid
  const [searchState, setSearchState] = React.useState({
    isSearching: false,
    keyword: '',
    scope: 'current',
    results: []
  });

    try {
    const currentPath = navigationStore.getCurrentPath();

    // 获取空间前缀
    const spacePrefix = navigationStore.isPublic ? '公共共享库' : '我的文件';

    // 处理文件选择
    const handleFileSelect = (e) => {
      const files = Array.from(e.target.files);  // 转换为数组，避免引用丢失
      if (files.length > 0) {
        // 公共空间上传时显示提示
        if (navigationStore.isPublic) {
          message.info('文件将上传到公共共享库，所有用户均可查看下载');
        }
        uploadCoreStore.handleFileSelect(files);
      }
      // 重置 input，允许重复选择同一文件
      e.target.value = '';
    };

    // 处理文件夹选择
    const handleFolderSelect = (e) => {
      const files = Array.from(e.target.files);  // 转换为数组，避免引用丢失
      if (files.length > 0) {
        // 公共空间上传时显示提示
        if (navigationStore.isPublic) {
          message.info('文件夹将上传到公共共享库，所有用户均可查看下载');
        }
        uploadCoreStore.handleFolderSelect(files);
      }
      e.target.value = '';
    };

    // 处理刷新
    const handleRefresh = () => {
      if (folderTreeRef.current && folderTreeRef.current.refresh) {
        folderTreeRef.current.refresh();
      }
      if (explorerRef.current && explorerRef.current.fetchItems) {
        explorerRef.current.fetchItems();
      }
    };

    // 搜索开始
    const handleSearchStart = () => {
      setSearchState(prev => ({ ...prev, isSearching: true }));
    };

    // 搜索结果
    const handleSearchResult = (result) => {
      setSearchState({
        isSearching: true,
        keyword: result.keyword,
        scope: result.scope,
        results: result.items
      });
    };

    // 搜索错误
    const handleSearchError = (errorMsg) => {
      message.error(errorMsg);
      setSearchState(prev => ({ ...prev, isSearching: false }));
    };

    // 清空搜索
    const handleClearSearch = () => {
      setSearchState({
        isSearching: false,
        keyword: '',
        scope: 'current',
        results: []
      });
    };

    return (
      <>
        <SpugBreadcrumb extra={
          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', width: '100%' }}>
            <Space wrap>
              <DiskStatus isPublic={navigationStore.isPublic} />
              <SearchBox
                isPublic={navigationStore.isPublic}
                onSearchStart={handleSearchStart}
                onSearchResult={handleSearchResult}
                onSearchError={handleSearchError}
                onClearSearch={handleClearSearch}
              />
            </Space>
            <Space wrap>
              <input
                type="file"
                multiple
                style={{ display: 'none' }}
                ref={fileInputRef}
                onChange={handleFileSelect}
              />
              <input
                type="file"
                webkitdirectory="true"
                directory="true"
                multiple
                style={{ display: 'none' }}
                ref={folderInputRef}
                onChange={handleFolderSelect}
              />
              <Button icon={<FolderAddOutlined />} onClick={() => {
                if (explorerRef.current && explorerRef.current.handleAddFolder) {
                  explorerRef.current.handleAddFolder();
                }
              }}>
                新建文件夹
              </Button>
              <Button onClick={handleRefresh}>
                刷新
              </Button>
              <Button type="primary" icon={<UploadOutlined />} onClick={() => {
                if (fileInputRef.current) {
                  fileInputRef.current.click();
                }
              }}>
                上传文件
              </Button>
              <Button icon={<CloudUploadOutlined />} onClick={() => {
                if (folderInputRef.current) {
                  folderInputRef.current.click();
                }
              }}>
                上传文件夹
              </Button>
              <Popover
                content={<UploadPanel />}
                title={null}
                trigger="click"
                placement="bottomRight"
                visible={uploadUIStore.uploadPanelVisible}
                onVisibleChange={(vis) => {
                  if (!vis) uploadUIStore.hideUploadPanel();
                }}
                overlayStyle={{ padding: 0, backgroundColor: 'transparent', boxShadow: 'none' }}
                overlayInnerStyle={{ padding: 0, backgroundColor: 'transparent', boxShadow: 'none' }}
              >
                <Badge count={uploadCoreStore.currentUploadQueue.length} offset={[-5, 5]}>
                  <Button icon={<CloudUploadOutlined />} />
                </Badge>
              </Popover>
            </Space>
          </div>
        }>
          <SpugBreadcrumb.Item>首页</SpugBreadcrumb.Item>
          <SpugBreadcrumb.Item>资料库</SpugBreadcrumb.Item>
        </SpugBreadcrumb>

        <div style={{ display: 'flex', flexDirection: 'column', flex: 1, minHeight: 0, padding: '0 24px' }}>
          <div style={{ marginBottom: 12, display: 'flex', alignItems: 'center', justifyContent: 'space-between', width: '100%' }}>
            <div style={{ display: 'flex', alignItems: 'center', flex: 1, minWidth: 0 }}>
              {currentPath.length > 0 && (
                <Space style={{ marginRight: 12 }}>
                  <Button
                    type="text"
                    icon={<ArrowLeftOutlined />}
                    onClick={navigationStore.goUp}
                    style={{ color: '#1890ff' }}
                  >
                    返回上一级
                  </Button>
                  <span style={{ color: '#d9d9d9' }}>|</span>
                </Space>
              )}
              <AntdBreadcrumb separator=">">
                <AntdBreadcrumb.Item
                  onClick={() => navigationStore.navigateTo(-1)}
                  style={{ cursor: 'pointer', color: currentPath.length > 0 ? '#1890ff' : '#999' }}
                >
                  {spacePrefix}
                </AntdBreadcrumb.Item>
                {currentPath.map((item, index) => (
                  <AntdBreadcrumb.Item
                    key={item.id}
                    onClick={() => navigationStore.navigateTo(index)}
                    style={{ cursor: 'pointer', color: index === currentPath.length - 1 ? '#999' : '#1890ff' }}
                  >
                    {item.name}
                  </AntdBreadcrumb.Item>
                ))}
              </AntdBreadcrumb>
            </div>

            {/* 视图切换按钮 */}
            <Radio.Group
              value={viewMode}
              onChange={(e) => setViewMode(e.target.value)}
              size="small"
              style={{ marginRight: 8 }}
            >
              <Radio.Button value="list" title="列表视图">
                <UnorderedListOutlined />
              </Radio.Button>
              <Radio.Button value="grid" title="缩略图视图">
                <AppstoreOutlined />
              </Radio.Button>
            </Radio.Group>

            {/* 右上角展开/收起详情面板按钮 */}
            <Button
              type="text"
              icon={detailPanelExpanded ? <RightOutlined /> : <LeftOutlined />}
              onClick={() => {
                if (explorerRef.current && explorerRef.current.toggleDetailPanel) {
                  explorerRef.current.toggleDetailPanel((newState) => {
                    setDetailPanelExpanded(newState);
                  });
                }
              }}
              style={{ fontSize: 12, color: '#666' }}
            >
              {detailPanelExpanded ? '收起' : '展开'}
            </Button>
          </div>

          <div style={{ display: 'flex', flex: 1, overflow: 'hidden', width: '100%', minWidth: 0 }}>
            {/* 左侧树形菜单 */}
            <div style={{ width: 260, borderRight: '1px solid #f0f0f0', display: 'flex', flexDirection: 'column', overflow: 'hidden' }}>
              <FolderTree
                ref={folderTreeRef}
                isPublic={navigationStore.isPublic}
                onFolderChange={() => {}}
              />
            </div>

            {/* 主内容区 */}
            <div style={{ flex: 1, overflow: 'hidden', display: 'flex', flexDirection: 'column' }}>
              <Explorer
                folderId={navigationStore.currentFolderId}
                onFolderChange={() => {}}
                ref={explorerRef}
                viewMode={viewMode}
                isPublic={navigationStore.isPublic}
                searchState={searchState}
              />
            </div>
          </div>
        </div>
      </>
    );
  } catch (error) {
    return <div>渲染错误: {error.message}</div>;
  }
});

export default DocumentIndex;
