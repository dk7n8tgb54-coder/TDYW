/**
 * Copyright (c) OpenSpug Organization. https://github.com/openspug/spug
 * Released under the AGPL-3.0 License.
 */
import React from 'react';
import { observer } from 'mobx-react';
import { Button, Breadcrumb as AntdBreadcrumb, Badge, Radio, Dropdown, Menu, message, Tooltip } from 'antd';
import { UploadOutlined, CloudUploadOutlined, FolderAddOutlined, AppstoreOutlined, UnorderedListOutlined, DownOutlined, ReloadOutlined, ArrowLeftOutlined, ProfileOutlined, CheckSquareOutlined } from '@ant-design/icons';
import Explorer from './Explorer';
import UploadPanel, { MiniBar } from './UploadPanel';
import FolderTree from './FolderTree';
import SearchBox from './components/SearchBox';
import DiskStatus from './components/DiskStatus';
import KeyboardShortcuts from './components/KeyboardShortcuts';
import UploadConflictModal from './components/UploadConflictModal';
import DocumentErrorBoundary from './components/DocumentErrorBoundary';
import DocumentDropUploadLayer from './components/DocumentDropUploadLayer';
import { isEmptyFolderBatch, isPlainFilesOnly, MAX_DROP_ENTRIES, MAX_DROP_DEPTH } from './utils/dropUpload';
import navigationStore from './stores/navigation';
import uploadUIStore from './stores/upload/ui';
import { uploadCoreStore } from './stores';
import { hasPermission, http } from 'libs';
import { setSystemFolder, PARTY_BUILDING_DOCUMENTS_CODE } from 'libs/systemFolderContext';
import styles from './DocumentLayout.module.less';
import './Explorer.module.less';

const DocumentIndex = observer(function ({ mode = 'normal', systemFolderCode = null, title = '资料库' }) {
  const isPartyBuildingDocuments = mode === 'partyBuildingDocuments' && systemFolderCode === PARTY_BUILDING_DOCUMENTS_CODE;
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
  // 【修复 2026-07-17】手动刷新只让刷新按钮显示 loading，列表不显示整表遮罩
  const [refreshing, setRefreshing] = React.useState(false);
  const [multiSelectMode, setMultiSelectMode] = React.useState(false);

  // 【2026-07-17 URL 一致性】普通模式挂载时从 URL 恢复完整导航路径，
  //   党建模式走 initSystemFolder 初始化锁定根，不调用 restoreFromUrl 以免越界到公共库。
  React.useEffect(() => {
    if (isPartyBuildingDocuments) return;
    navigationStore.restoreFromUrl();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // 【党建工作】进入页面时初始化系统目录上下文，离开时清理
  React.useLayoutEffect(() => {
    let cancelled = false;
    if (isPartyBuildingDocuments) {
      setSystemFolder(systemFolderCode);
      // 拉取系统目录绑定，初始化导航到党建工作根目录
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
            setInitError(e?.message || '党建工作初始化失败');
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
      if (isPartyBuildingDocuments) {
        setSystemFolder(null);
        navigationStore.clearSystemFolder();
      }
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [isPartyBuildingDocuments, systemFolderCode, title]);

  const currentPath = navigationStore.getCurrentPath();
  const rootFolderId = navigationStore.lockedRootFolderId;
  const rootFolderName = navigationStore.lockedRootFolderName || title;
  const breadcrumbPath = isPartyBuildingDocuments && rootFolderId && currentPath[0]?.id === rootFolderId
    ? currentPath.slice(1)
    : currentPath;
  const breadcrumbPathIndexOffset = breadcrumbPath.length === currentPath.length ? 0 : 1;
  const canGoBack = isPartyBuildingDocuments ? breadcrumbPath.length > 0 : currentPath.length > 0;
  // 党建工作锁定模式：面包屑根节点显示锁定根名称，否则显示空间前缀
  const spacePrefix = isPartyBuildingDocuments
    ? rootFolderName
    : (navigationStore.isPublic ? '公共共享库' : '我的文件');

  // 党建工作模式下的权限前缀
  const permPrefix = isPartyBuildingDocuments ? 'document.party_building_document' : 'document.document';
  const canUpload = hasPermission(`${permPrefix}.upload`);
  const canCreateFolder = hasPermission(`${permPrefix}.create_folder`);
  const isPartyBuildingDocumentsReady = !isPartyBuildingDocuments || !!navigationStore.lockedRootFolderId;
  const hasStaleSystemFolderState = !isPartyBuildingDocuments
    && (navigationStore.lockedRootFolderId || navigationStore.systemFolderCode);
  // 党建模式下：currentFolderId 为空时回退到 lockedRootFolderId，
  // 防止 useLayoutEffect 清理/重建间隙导致 parent_id=null
  const effectiveCurrentFolderId = hasStaleSystemFolderState
    ? null
    : (isPartyBuildingDocuments
        ? (navigationStore.currentFolderId || navigationStore.lockedRootFolderId)
        : navigationStore.currentFolderId);

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
      if (isPartyBuildingDocuments) {
        message.info('文件将上传到党建工作，所有用户均可查看下载');
      } else if (navigationStore.isPublic) {
        message.info('文件将上传到公共共享库，所有用户均可查看下载');
      }
      uploadCoreStore.handleFileSelect(files);
    }
    e.target.value = '';
  };

  const handleFolderSelect = (e) => {
    const files = Array.from(e.target.files);
    if (files.length > 0) {
      if (isPartyBuildingDocuments) {
        message.info('文件夹将上传到党建工作，所有用户均可查看下载');
      } else if (navigationStore.isPublic) {
        message.info('文件夹将上传到公共共享库，所有用户均可查看下载');
      }
      uploadCoreStore.handleFolderSelect(files);
    }
    e.target.value = '';
  };

  const handleRefresh = async () => {
    if (refreshing) return;
    setRefreshing(true);
    try {
      if (folderTreeRef.current && folderTreeRef.current.refresh) {
        folderTreeRef.current.refresh();
      }
      // fetchItems() 默认 refresh 模式：失效全部缓存 + 重新请求当前目录，不显示整表 loading
      if (explorerRef.current && explorerRef.current.fetchItems) {
        await explorerRef.current.fetchItems();
      }
    } finally {
      setRefreshing(false);
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

  // 【拖拽上传】目标目录显示文本（用于遮罩提示 + captureTargetContext）
  // 普通模式：'我的文件 / 子目录' 或 '公共共享库 / 子目录'
  // 党建模式：'党建工作 / 子目录'
  const targetPathLabel = [
    spacePrefix,
    ...breadcrumbPath.map(p => p.name),
  ].filter(Boolean).join(' / ');

  // 【拖拽上传】捕获不可变目标上下文（drop 时立即调用，固化为快照）
  // 党建模式显式传 systemFolderCode，避免离开党建路由后丢失
  const captureDropTargetContext = () => {
    return uploadCoreStore.captureUploadTargetContext({
      systemFolderCode: isPartyBuildingDocuments ? PARTY_BUILDING_DOCUMENTS_CODE : null,
      targetPathLabel,
    });
  };

  // 【拖拽上传】drop 回调：收集结果 → 区分普通文件/文件夹 → 进入现有 uploadCoreStore
  const handleDropUpload = (collected, targetContext) => {
    // 空文件夹
    if (isEmptyFolderBatch(collected)) {
      message.info('空文件夹无需上传');
      return;
    }
    // 截断/深度超限警告
    if (collected.truncated) {
      message.warning(`文件数量超过上限（${MAX_DROP_ENTRIES}），已截断，请分批上传`);
    }
    if (collected.depthExceeded) {
      message.warning(`目录深度超过上限（${MAX_DROP_DEPTH}层），部分文件未上传`);
    }
    // 解析错误提示
    if (collected.errors && collected.errors.length > 0) {
      message.warning(collected.errors[0]);
    }
    if (collected.files.length === 0) return;

    // 区分普通文件 vs 文件夹：
    //   - 全是普通文件（无文件夹）→ handleFileSelect（走普通/分片上传）
    //   - 包含文件夹 → handleFolderEntries（走 FolderStructureBuilder + 普通上传）
    // 两条路径都进入同一套 uploadCoreStore，不新增队列
    if (isPlainFilesOnly(collected)) {
      if (isPartyBuildingDocuments) {
        message.info('文件将上传到党建工作，所有用户均可查看下载');
      } else if (navigationStore.isPublic) {
        message.info('文件将上传到公共共享库，所有用户均可查看下载');
      }
      uploadCoreStore.handleFileSelect(collected.files, targetContext);
    } else {
      if (isPartyBuildingDocuments) {
        message.info('文件夹将上传到党建工作，所有用户均可查看下载');
      } else if (navigationStore.isPublic) {
        message.info('文件夹将上传到公共共享库，所有用户均可查看下载');
      }
      uploadCoreStore.handleFolderEntries(collected.entries, targetContext);
    }
  };

  return (
    <div className={styles.pageWrapper}>
      {/* 【2026-07-17 布局优化】紧凑顶部信息栏：站点面包屑 + 磁盘状态 + 搜索框 */}
      <div className={styles.topBar}>
        <div className={styles.topBarLeft}>
          <AntdBreadcrumb className={styles.siteBreadcrumb}>
            <AntdBreadcrumb.Item>首页</AntdBreadcrumb.Item>
            <AntdBreadcrumb.Item>{title}</AntdBreadcrumb.Item>
          </AntdBreadcrumb>
        </div>
        <div className={styles.topBarRight}>
          <DiskStatus isPublic={navigationStore.isPublic} />
          <SearchBox
            isPublic={navigationStore.isPublic}
            placeholder={isPartyBuildingDocuments ? '搜索党建工作' : undefined}
            folderId={isPartyBuildingDocuments ? navigationStore.lockedRootFolderId : undefined}
            systemFolderCode={isPartyBuildingDocuments ? PARTY_BUILDING_DOCUMENTS_CODE : null}
            onSearchStart={handleSearchStart}
            onSearchResult={handleSearchResult}
            onSearchError={handleSearchError}
            onClearSearch={handleClearSearch}
          />
        </div>
      </div>

      {initError && (
        <div style={{ padding: '12px 16px', color: '#ff4d4f' }}>{initError}</div>
      )}

      {!initError && !isPartyBuildingDocumentsReady && (
        <div style={{ padding: '24px 16px', color: '#666' }}>党建工作初始化中...</div>
      )}

      {!initError && isPartyBuildingDocumentsReady && <div className={styles.documentPage}>
        {/* 【2026-07-17 工具栏布局】左路径区(flex:1) + 右固定操作区(flex-shrink:0)。
            路径长短不改变右侧按钮横坐标；右侧分两组：文件操作(上传/新建/刷新) +
            视图操作(传输/列表网格/详情)，两组间克制竖向分隔线。 */}
        <div className={styles.toolBar}>
          <div className={styles.pathArea}>
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
          </div>
          <div className={styles.rightActions}>
            <input type="file" multiple style={{ display: 'none' }} ref={fileInputRef} onChange={handleFileSelect} />
            <input type="file" webkitdirectory="true" directory="true" multiple style={{ display: 'none' }} ref={folderInputRef} onChange={handleFolderSelect} />
            <div className={styles.fileActions}>
              {canUpload && (
                <Dropdown overlay={uploadMenu} placement="bottomRight">
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
              <Tooltip title="刷新当前目录">
                <Button
                  icon={<ReloadOutlined />}
                  onClick={handleRefresh}
                  loading={refreshing}
                  size="small"
                  className={styles.refreshBtn}
                >
                  <span className={styles.refreshText}>刷新</span>
                </Button>
              </Tooltip>
              <Tooltip title={multiSelectMode ? '退出多选' : '进入多选模式'}>
                <Button
                  icon={<CheckSquareOutlined />}
                  onClick={() => setMultiSelectMode(m => !m)}
                  size="small"
                  type={multiSelectMode ? 'primary' : 'default'}
                >
                  {multiSelectMode ? '退出多选' : '多选'}
                </Button>
              </Tooltip>
            </div>
            <div className={styles.actionDivider} />
            <div className={styles.viewActions}>
              <Badge count={uploadCoreStore.currentUploadQueue.length} offset={[-5, 5]}>
                <Button
                  type="text"
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
              <Tooltip title={detailPanelExpanded ? '收起详情面板' : '展开详情面板'}>
                <Button
                  type="text"
                  icon={<ProfileOutlined />}
                  onClick={() => {
                    if (explorerRef.current && explorerRef.current.toggleDetailPanel) {
                      explorerRef.current.toggleDetailPanel((newState) => {
                        setDetailPanelExpanded(newState);
                      });
                    }
                  }}
                  size="small"
                  className={detailPanelExpanded ? styles.detailBtnActive : styles.detailBtn}
                />
              </Tooltip>
            </div>
          </div>
        </div>

        {/* 主内容区 */}
        <div className={styles.mainContent}>
          <div className={styles.sidebarTree}>
            <FolderTree
              ref={folderTreeRef}
              isPublic={navigationStore.isPublic}
              onFolderChange={() => {}}
              lockedRoot={isPartyBuildingDocuments}
              rootFolderId={isPartyBuildingDocuments ? navigationStore.lockedRootFolderId : null}
              rootFolderName={isPartyBuildingDocuments ? rootFolderName : undefined}
            />
          </div>
          <div className={styles.explorerArea}>
            <DocumentDropUploadLayer
              canUpload={canUpload}
              isPartyBuildingDocuments={isPartyBuildingDocuments}
              isPartyBuildingDocumentsReady={isPartyBuildingDocumentsReady}
              isSearching={searchState.isSearching}
              targetPathLabel={targetPathLabel}
              captureTargetContext={captureDropTargetContext}
              onDrop={handleDropUpload}
            >
              <Explorer
                folderId={effectiveCurrentFolderId}
                onFolderChange={() => {}}
                ref={explorerRef}
                viewMode={viewMode}
                isPublic={navigationStore.isPublic}
                searchState={searchState}
                isPartyBuildingDocuments={isPartyBuildingDocuments}
                permPrefix={permPrefix}
                multiSelectMode={multiSelectMode}
              />
            </DocumentDropUploadLayer>
          </div>
        </div>
      </div>}

      {isPartyBuildingDocumentsReady && uploadCoreStore.currentUploadQueue.length > 0 && !uploadUIStore.panel.expanded && (
        <MiniBar />
      )}
      {isPartyBuildingDocumentsReady && <UploadPanel />}
      {isPartyBuildingDocumentsReady && <KeyboardShortcuts />}
      {isPartyBuildingDocumentsReady && <UploadConflictModal />}
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
