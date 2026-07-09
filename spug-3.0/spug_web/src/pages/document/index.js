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
import { hasPermission, http } from 'libs';
import { setSystemFolder, INDUSTRY_RULES_CODE } from 'libs/systemFolderContext';
import styles from './DocumentLayout.module.less';
import './Explorer.module.less';

const DocumentIndex = observer(function ({ mode = 'normal', systemFolderCode = null, title = '资料库' }) {
  const isIndustryRules = mode === 'industryRules' && systemFolderCode === INDUSTRY_RULES_CODE;
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
  const [initError, setInitError] = React.useState(null);

  // 【2026-07-02 动态降级】资料库页面挂载时首次拉取服务器压力 + 启动轮询；
  //   卸载时停止轮询，避免离开页面后继续请求
  React.useEffect(() => {
    uploadCoreStore.initUploadPressure();
    uploadCoreStore.startPressurePolling();
    return () => {
      uploadCoreStore.stopPressurePolling();
    };
  }, []);

  // 【行业规章】进入页面时初始化系统目录上下文，离开时清理
  React.useLayoutEffect(() => {
    let cancelled = false;
    if (isIndustryRules) {
      setSystemFolder(systemFolderCode);
      // 拉取系统目录绑定，初始化导航到行业规章根目录
      (async () => {
        try {
          const res = await http.get('/api/document/system-folder/', {
            params: { code: systemFolderCode },
          });
          if (cancelled) return;
          navigationStore.initSystemFolder({
            code: systemFolderCode,
            folderId: res.folder_id,
            name: res.folder_name || title,
          });
        } catch (e) {
          if (!cancelled) {
            setInitError(e?.message || '行业规章初始化失败');
          }
        }
      })();
    } else {
      setSystemFolder(null);
      if (navigationStore.lockedRootFolderId || navigationStore.systemFolderCode) {
        navigationStore.clearSystemFolder();
      }
    }
    return () => {
      cancelled = true;
      if (isIndustryRules) {
        setSystemFolder(null);
        navigationStore.clearSystemFolder();
      }
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [isIndustryRules, systemFolderCode, title]);

  const currentPath = navigationStore.getCurrentPath();
  const rootFolderId = navigationStore.lockedRootFolderId;
  const rootFolderName = navigationStore.lockedRootFolderName || title;
  const breadcrumbPath = isIndustryRules && rootFolderId && currentPath[0]?.id === rootFolderId
    ? currentPath.slice(1)
    : currentPath;
  const breadcrumbPathIndexOffset = breadcrumbPath.length === currentPath.length ? 0 : 1;
  const canGoBack = isIndustryRules ? breadcrumbPath.length > 0 : currentPath.length > 0;
  // 行业规章锁定模式：面包屑根节点显示锁定根名称，否则显示空间前缀
  const spacePrefix = isIndustryRules
    ? rootFolderName
    : (navigationStore.isPublic ? '公共共享库' : '我的文件');

  // 行业规章模式下的权限前缀
  const permPrefix = isIndustryRules ? 'document.industry_rule' : 'document.document';
  const canUpload = hasPermission(`${permPrefix}.upload`);
  const canCreateFolder = hasPermission(`${permPrefix}.create_folder`);
  const isIndustryRulesReady = !isIndustryRules || !!navigationStore.lockedRootFolderId;
  const hasStaleSystemFolderState = !isIndustryRules
    && (navigationStore.lockedRootFolderId || navigationStore.systemFolderCode);
  const effectiveCurrentFolderId = hasStaleSystemFolderState ? null : navigationStore.currentFolderId;

  // 【2026-06-11 优化】智能面包屑省略
  // 路径 ≤ 3 级：完整显示
  // 路径 > 3 级：根 + 第 1 级 + "..." + 最后 1 级（省略中间）
  // hover "..." 显示被省略的完整路径（行业惯例：VSCode 资源管理器、macOS Finder）
  // 关键：避免路径过长时把"上传/新建文件夹/刷新"3 个按钮挤到右侧
  const renderBreadcrumbItems = () => {
    if (breadcrumbPath.length <= 2) {
      // 短路径（≤ 2 级子目录）：完整渲染
      return (
        <>
          <AntdBreadcrumb.Item
            onClick={() => navigationStore.navigateTo(-1)}
            style={{ cursor: 'pointer', color: breadcrumbPath.length > 0 ? '#1890ff' : '#666', fontWeight: 500 }}
          >
            {spacePrefix}
          </AntdBreadcrumb.Item>
          {breadcrumbPath.map((item, index) => (
            <AntdBreadcrumb.Item
              key={item.id}
              onClick={() => navigationStore.navigateTo(index + breadcrumbPathIndexOffset)}
              style={{ cursor: 'pointer', color: index === breadcrumbPath.length - 1 ? '#666' : '#1890ff' }}
            >
              {item.name}
            </AntdBreadcrumb.Item>
          ))}
        </>
      );
    }
    // 长路径（> 2 级子目录）：根 + 第 1 级 + "..." + 最后 1 级
    const first = breadcrumbPath[0];
    const last = breadcrumbPath[breadcrumbPath.length - 1];
    const omittedNames = breadcrumbPath.slice(1, -1).map((i) => i.name).join(' / ');
    return (
      <>
        <AntdBreadcrumb.Item
          onClick={() => navigationStore.navigateTo(-1)}
          style={{ cursor: 'pointer', color: '#1890ff', fontWeight: 500 }}
        >
          {spacePrefix}
        </AntdBreadcrumb.Item>
        <AntdBreadcrumb.Item
          onClick={() => navigationStore.navigateTo(breadcrumbPathIndexOffset)}
          style={{ cursor: 'pointer', color: '#1890ff' }}
        >
          {first.name}
        </AntdBreadcrumb.Item>
        <AntdBreadcrumb.Item
          style={{ cursor: 'default', color: '#8c8c8c' }}
          title={`已省略 ${breadcrumbPath.length - 2} 级：${omittedNames}`}
        >
          ...
        </AntdBreadcrumb.Item>
        <AntdBreadcrumb.Item
          onClick={() => navigationStore.navigateTo(breadcrumbPath.length - 1 + breadcrumbPathIndexOffset)}
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
      if (isIndustryRules) {
        message.info('文件将上传到行业规章，所有用户均可查看下载');
      } else if (navigationStore.isPublic) {
        message.info('文件将上传到公共共享库，所有用户均可查看下载');
      }
      // 【2026-07-02】开始上传前刷新一次服务器压力，确保按最新等级调度
      uploadCoreStore.refreshPressure();
      uploadCoreStore.handleFileSelect(files);
    }
    e.target.value = '';
  };

  const handleFolderSelect = (e) => {
    const files = Array.from(e.target.files);
    if (files.length > 0) {
      if (isIndustryRules) {
        message.info('文件夹将上传到行业规章，所有用户均可查看下载');
      } else if (navigationStore.isPublic) {
        message.info('文件夹将上传到公共共享库，所有用户均可查看下载');
      }
      // 【2026-07-02】开始上传前刷新一次服务器压力
      uploadCoreStore.refreshPressure();
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
            placeholder={isIndustryRules ? '搜索行业规章' : undefined}
            folderId={isIndustryRules ? navigationStore.lockedRootFolderId : undefined}
            onSearchStart={handleSearchStart}
            onSearchResult={handleSearchResult}
            onSearchError={handleSearchError}
            onClearSearch={handleClearSearch}
          />
        </div>
      }>
        <SpugBreadcrumb.Item>首页</SpugBreadcrumb.Item>
        <SpugBreadcrumb.Item>{title}</SpugBreadcrumb.Item>
      </SpugBreadcrumb>

      {initError && (
        <div style={{ padding: '12px 16px', color: '#ff4d4f' }}>{initError}</div>
      )}

      {!initError && !isIndustryRulesReady && (
        <div style={{ padding: '24px 16px', color: '#666' }}>行业规章初始化中...</div>
      )}

      {!initError && isIndustryRulesReady && <div className={styles.documentPage}>
        {/* 统一工具栏：左侧路径+操作，右侧视图切换+详情+上传 */}
        <div className={styles.toolBar}>
          <div className={styles.toolBarLeft}>
            {canGoBack && (
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
            {canUpload && (
              <Dropdown overlay={uploadMenu} placement="bottomLeft">
                <Button type="primary" icon={<CloudUploadOutlined />} size="small">
                  上传 <DownOutlined style={{ fontSize: 10, marginLeft: 2 }} />
                </Button>
              </Dropdown>
            )}
            {canCreateFolder && (
              <Button icon={<FolderAddOutlined />} onClick={() => {
                if (explorerRef.current && explorerRef.current.handleAddFolder) {
                  explorerRef.current.handleAddFolder();
                }
              }} size="small">
                新建文件夹
              </Button>
            )}
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
              lockedRoot={isIndustryRules}
              rootFolderId={isIndustryRules ? navigationStore.lockedRootFolderId : null}
              rootFolderName={isIndustryRules ? rootFolderName : undefined}
              autoExpandAll={isIndustryRules}
            />
          </div>
          <div className={styles.explorerArea}>
            <Explorer
              folderId={effectiveCurrentFolderId}
              onFolderChange={() => {}}
              ref={explorerRef}
              viewMode={viewMode}
              isPublic={navigationStore.isPublic}
              searchState={searchState}
              isIndustryRules={isIndustryRules}
              permPrefix={permPrefix}
            />
          </div>
        </div>
      </div>}

      {isIndustryRulesReady && uploadCoreStore.currentUploadQueue.length > 0 && !uploadUIStore.panel.expanded && (
        <MiniBar />
      )}
      {isIndustryRulesReady && <UploadPanel />}
      {isIndustryRulesReady && <KeyboardShortcuts />}
    </div>
  );
});

export default function DocumentIndexWrapper(props) {
  return (
    <DocumentErrorBoundary>
      <DocumentIndex {...props} />
    </DocumentErrorBoundary>
  );
}
