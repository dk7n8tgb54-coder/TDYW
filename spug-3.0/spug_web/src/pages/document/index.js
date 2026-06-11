/**
 * Copyright (c) OpenSpug Organization. https://github.com/openspug/spug
 * Released under the AGPL-3.0 License.
 */
import React from 'react';
import { observer } from 'mobx-react';
import { Button, Breadcrumb as AntdBreadcrumb, Badge, Radio, Dropdown, Menu, message } from 'antd';
import { UploadOutlined, CloudUploadOutlined, FolderAddOutlined, AppstoreOutlined, UnorderedListOutlined, DownOutlined, ReloadOutlined, ArrowLeftOutlined, LeftOutlined, RightOutlined } from '@ant-design/icons';
import { Breadcrumb as SpugBreadcrumb } from 'components';
import Explorer from './Explorer';
import UploadPanel, { MiniBar } from './UploadPanel';
import FolderTree from './FolderTree';
import SearchBox from './components/SearchBox';
import DiskStatus from './components/DiskStatus';
import KeyboardShortcuts from './components/KeyboardShortcuts';
import DocumentErrorBoundary from './components/DocumentErrorBoundary';
import navigationStore from './stores/navigation';
import uploadUIStore from './stores/upload/ui';
import { uploadCoreStore } from './stores';
import styles from './DocumentLayout.module.less';
import './Explorer.module.less';

const DocumentIndex = observer(function () {
  const fileInputRef = React.useRef(null);
  const folderInputRef = React.useRef(null);
  const explorerRef = React.useRef(null);
  const folderTreeRef = React.useRef(null);
  const [detailPanelExpanded, setDetailPanelExpanded] = React.useState(false);
  const [viewMode, setViewMode] = React.useState('list');
  const [searchState, setSearchState] = React.useState({
    isSearching: false,
    keyword: '',
    scope: 'current',
    results: []
  });

  const currentPath = navigationStore.getCurrentPath();
  const spacePrefix = navigationStore.isPublic ? '公共共享库' : '我的文件';

  // 【2026-06-11 优化】智能面包屑省略
  // 路径 ≤ 3 级：完整显示
  // 路径 > 3 级：根 + 第 1 级 + "..." + 最后 1 级（省略中间）
  // hover "..." 显示被省略的完整路径（行业惯例：VSCode 资源管理器、macOS Finder）
  // 关键：避免路径过长时把"上传/新建文件夹/刷新"3 个按钮挤到右侧
  const renderBreadcrumbItems = () => {
    if (currentPath.length <= 2) {
      // 短路径（≤ 2 级子目录）：完整渲染
      return (
        <>
          <AntdBreadcrumb.Item
            onClick={() => navigationStore.navigateTo(-1)}
            style={{ cursor: 'pointer', color: currentPath.length > 0 ? '#1890ff' : '#666', fontWeight: 500 }}
          >
            {spacePrefix}
          </AntdBreadcrumb.Item>
          {currentPath.map((item, index) => (
            <AntdBreadcrumb.Item
              key={item.id}
              onClick={() => navigationStore.navigateTo(index)}
              style={{ cursor: 'pointer', color: index === currentPath.length - 1 ? '#666' : '#1890ff' }}
            >
              {item.name}
            </AntdBreadcrumb.Item>
          ))}
        </>
      );
    }
    // 长路径（> 2 级子目录）：根 + 第 1 级 + "..." + 最后 1 级
    const first = currentPath[0];
    const last = currentPath[currentPath.length - 1];
    const omittedNames = currentPath.slice(1, -1).map((i) => i.name).join(' / ');
    return (
      <>
        <AntdBreadcrumb.Item
          onClick={() => navigationStore.navigateTo(-1)}
          style={{ cursor: 'pointer', color: '#1890ff', fontWeight: 500 }}
        >
          {spacePrefix}
        </AntdBreadcrumb.Item>
        <AntdBreadcrumb.Item
          onClick={() => navigationStore.navigateTo(0)}
          style={{ cursor: 'pointer', color: '#1890ff' }}
        >
          {first.name}
        </AntdBreadcrumb.Item>
        <AntdBreadcrumb.Item
          style={{ cursor: 'default', color: '#8c8c8c' }}
          title={`已省略 ${currentPath.length - 2} 级：${omittedNames}`}
        >
          ...
        </AntdBreadcrumb.Item>
        <AntdBreadcrumb.Item
          onClick={() => navigationStore.navigateTo(currentPath.length - 1)}
          style={{ cursor: 'pointer', color: '#666' }}
        >
          {last.name}
        </AntdBreadcrumb.Item>
      </>
    );
  };

  const handleUploadMenu = ({ key }) => {
    if (key === 'file' && fileInputRef.current) {
      fileInputRef.current.click();
    } else if (key === 'folder' && folderInputRef.current) {
      folderInputRef.current.click();
    }
  };

  // 上传下拉菜单
  const uploadMenu = (
    <Menu
      onClick={handleUploadMenu}
      items={[
        { key: 'file', icon: <UploadOutlined />, label: '上传文件' },
        { key: 'folder', icon: <CloudUploadOutlined />, label: '上传文件夹' },
      ]}
    />
  );

  const handleFileSelect = (e) => {
    const files = Array.from(e.target.files);
    if (files.length > 0) {
      if (navigationStore.isPublic) {
        message.info('文件将上传到公共共享库，所有用户均可查看下载');
      }
      uploadCoreStore.handleFileSelect(files);
    }
    e.target.value = '';
  };

  const handleFolderSelect = (e) => {
    const files = Array.from(e.target.files);
    if (files.length > 0) {
      if (navigationStore.isPublic) {
        message.info('文件夹将上传到公共共享库，所有用户均可查看下载');
      }
      uploadCoreStore.handleFolderSelect(files);
    }
    e.target.value = '';
  };

  const handleRefresh = () => {
    if (folderTreeRef.current && folderTreeRef.current.refresh) {
      folderTreeRef.current.refresh();
    }
    if (explorerRef.current && explorerRef.current.fetchItems) {
      explorerRef.current.fetchItems();
    }
  };

  const handleSearchStart = () => {
    setSearchState(prev => ({ ...prev, isSearching: true }));
  };

  const handleSearchResult = (result) => {
    setSearchState({
      isSearching: true,
      keyword: result.keyword,
      scope: result.scope,
      results: result.items
    });
  };

  const handleSearchError = (errorMsg) => {
    message.error(errorMsg);
    setSearchState(prev => ({ ...prev, isSearching: false }));
  };

  const handleClearSearch = () => {
    setSearchState({ isSearching: false, keyword: '', scope: 'current', results: [] });
  };

  return (
    <div className={styles.pageWrapper}>
      {/* 面包屑 + 磁盘状态 + 搜索 */}
      <SpugBreadcrumb extra={
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', width: '100%' }}>
          <DiskStatus isPublic={navigationStore.isPublic} />
          <SearchBox
            isPublic={navigationStore.isPublic}
            onSearchStart={handleSearchStart}
            onSearchResult={handleSearchResult}
            onSearchError={handleSearchError}
            onClearSearch={handleClearSearch}
          />
        </div>
      }>
        <SpugBreadcrumb.Item>首页</SpugBreadcrumb.Item>
        <SpugBreadcrumb.Item>资料库</SpugBreadcrumb.Item>
      </SpugBreadcrumb>

      <div className={styles.documentPage}>
        {/* 统一工具栏：左侧路径+操作，右侧视图切换+详情+上传 */}
        <div className={styles.toolBar}>
          <div className={styles.toolBarLeft}>
            {currentPath.length > 0 && (
              <Button
                type="text"
                icon={<ArrowLeftOutlined />}
                onClick={navigationStore.goUp}
                className={styles.backButton}
                size="small"
              />
            )}
            <AntdBreadcrumb separator=">" className={styles.breadcrumb}>
              {renderBreadcrumbItems()}
            </AntdBreadcrumb>
            <span className={styles.toolbarDivider} />
            <input type="file" multiple style={{ display: 'none' }} ref={fileInputRef} onChange={handleFileSelect} />
            <input type="file" webkitdirectory="true" directory="true" multiple style={{ display: 'none' }} ref={folderInputRef} onChange={handleFolderSelect} />
            <Dropdown overlay={uploadMenu} placement="bottomLeft">
              <Button type="primary" icon={<CloudUploadOutlined />} size="small">
                上传 <DownOutlined style={{ fontSize: 10, marginLeft: 2 }} />
              </Button>
            </Dropdown>
            <Button icon={<FolderAddOutlined />} onClick={() => {
              if (explorerRef.current && explorerRef.current.handleAddFolder) {
                explorerRef.current.handleAddFolder();
              }
            }} size="small">
              新建文件夹
            </Button>
            <Button icon={<ReloadOutlined />} onClick={handleRefresh} size="small">
              刷新
            </Button>
          </div>
          <div className={styles.toolBarRight}>
            <Badge count={uploadCoreStore.currentUploadQueue.length} offset={[-5, 5]}>
              <Button
                icon={<CloudUploadOutlined />}
                onClick={() => uploadUIStore.panel.toggle()}
                title="查看传输任务"
                size="small"
              />
            </Badge>
            <Radio.Group
              value={viewMode}
              onChange={(e) => setViewMode(e.target.value)}
              size="small"
            >
              <Radio.Button value="list" title="列表视图">
                <UnorderedListOutlined />
              </Radio.Button>
              <Radio.Button value="grid" title="缩略图视图">
                <AppstoreOutlined />
              </Radio.Button>
            </Radio.Group>
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
              size="small"
              title={detailPanelExpanded ? '收起详情' : '展开详情'}
            />
          </div>
        </div>

        {/* 主内容区 */}
        <div className={styles.mainContent}>
          <div className={styles.sidebarTree}>
            <FolderTree
              ref={folderTreeRef}
              isPublic={navigationStore.isPublic}
              onFolderChange={() => {}}
            />
          </div>
          <div className={styles.explorerArea}>
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

      {uploadCoreStore.currentUploadQueue.length > 0 && !uploadUIStore.panel.expanded && (
        <MiniBar />
      )}
      <UploadPanel />
      <KeyboardShortcuts />
    </div>
  );
});

export default function DocumentIndexWrapper() {
  return (
    <DocumentErrorBoundary>
      <DocumentIndex />
    </DocumentErrorBoundary>
  );
}
