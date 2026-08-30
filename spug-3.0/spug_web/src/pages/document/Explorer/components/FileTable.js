/**
 * 文件表格组件
 * 【任务4.2】从Explorer组件拆分出来的子组件
 * 职责：封装Table的渲染逻辑
 *
 * 【修复 2026-07-17】取消整表 loading 灰色遮罩（antd Table loading 固定 false），
 *   改由 Explorer 顶部轻量进度条提示加载；interactionDisabled 时行降低透明度但保留内容可见。
 */
import React, { useMemo, useRef, useState, useEffect } from 'react';
import { Table, Empty } from 'antd';
import { useResizableColumns } from '@/components/resizableColumns';
import { resolveVisibleColumns } from './columnVisibility';

// 【2026-08-30 列宽拖动】接入 src/components/resizableColumns 公共能力：
// - 全部列（含文件名列）均为固定宽度列，可在表头拖动调整宽度；宽度保存在
//   公共组件的会话内存中（按 document_file 键分桶）：站内切页往返保留，
//   整页刷新/关标签页还原默认；拖动手柄双击可恢复该列默认宽度
// - 表尾填充列（FILLER_COLUMN）吸收容器剩余宽度，保证拖动精度
// - 主列表与搜索结果分组表格共用本组件与同一持久化键（列结构一致，宽度互通）
const FILE_TABLE_TKEY = 'document_file';

// 表尾填充列：无宽度、无内容，吸收容器剩余宽度（tableLayout:fixed 下，
// 剩余空间只会分给无宽度列——若没有填充列，就会被按比例摊给全部固定列，
// 导致拖动宽度失真）。antd 默认表格无竖向边框，填充列视觉不可见；
// 拦截行事件，避免点击表尾空白区误触行操作。
const FILLER_COLUMN = {
  title: '',
  dataIndex: '__column_fill__',
  key: '__column_fill__',
  onCell: () => ({
    onClick: (e) => e.stopPropagation(),
    onDoubleClick: (e) => e.stopPropagation(),
    onContextMenu: (e) => e.stopPropagation(),
  }),
};

/**
 * 文件表格组件
 * @param {Object} props - 组件属性
 * @param {Array} props.columns - 列配置
 * @param {Array} props.dataSource - 数据源
 * @param {boolean} props.interactionDisabled - 是否禁用行交互（目录切换未命中缓存时）
 * @param {Array} props.selectedRowKeys - 选中的行keys
 * @param {Function} props.onSelectChange - 选中变化回调
 * @param {boolean} props.isSearching - 是否搜索模式
 * @param {Object} props.pagination - 分页配置
 * @param {Function} props.onTableChange - 表格变化回调
 * @param {Function} props.onRow - 行事件处理
 * @param {boolean} props.showPagination - 是否显示分页
 * @param {boolean} props.showSelection - 是否显示选择列（多选模式）
 * @param {boolean} props.isPublic - 是否公共空间
 */
const FileTable = ({
  columns,
  dataSource,
  interactionDisabled = false,
  selectedRowKeys,
  onSelectChange,
  isSearching,
  pagination,
  onTableChange,
  onRow,
  showPagination = true,
  showSelection = true,
  isPublic = false,
}) => {
  // 安全的选中keys
  const safeSelectedRowKeys = useMemo(() =>
    Array.isArray(selectedRowKeys) ? selectedRowKeys : []
  , [selectedRowKeys]);

  // 表格分页配置
  const tablePagination = useMemo(() => {
    if (!showPagination) return false;
    
    return {
      current: pagination?.current || 1,
      pageSize: pagination?.pageSize || 20,
      total: pagination?.total || dataSource?.length || 0,
      showSizeChanger: !isSearching,
      showQuickJumper: !isSearching,
      pageSizeOptions: ['10', '20', '50', '100'],
      showTotal: (total, range) => `${range[0]}-${range[1]} 项 / 共 ${total} 项`,
      onChange: pagination?.onChange,
    };
  }, [showPagination, pagination, isSearching, dataSource]);

  // 空状态渲染
  const emptyText = useMemo(() => {
    if (isPublic) {
      return (
        <Empty
          description={
            <div>
              <div style={{ fontSize: 16, marginBottom: 8 }}>暂无公共共享文件</div>
              <div style={{ fontSize: 14, color: '#999' }}>快来上传第一个文件，与全平台用户共享吧</div>
            </div>
          }
        />
      );
    }
    return (
      <Empty
        description={
          <div>
            <div style={{ fontSize: 16, marginBottom: 8 }}>暂无文件</div>
            <div style={{ fontSize: 14, color: '#999' }}>点击上传按钮开始上传你的第一个文件</div>
          </div>
        }
      />
    );
  }, [isPublic]);

  // 【2026-08-16 响应式列显隐】监听容器宽度，窄容器时按次要程度隐藏列（见 columnVisibility.js），
  //   优先保证文件名列可读；容器测量失败（无 ResizeObserver）时保持全列展示
  const containerRef = useRef(null);
  const [containerWidth, setContainerWidth] = useState(null);

  useEffect(() => {
    if (typeof ResizeObserver === 'undefined' || !containerRef.current) return undefined;
    const observer = new ResizeObserver((entries) => {
      const entry = entries[0];
      if (entry && entry.contentRect) {
        setContainerWidth(entry.contentRect.width);
      }
    });
    observer.observe(containerRef.current);
    return () => observer.disconnect();
  }, []);

  // 【2026-08-30 列宽拖动】应用持久化宽度并挂载表头拖动手柄（含自定义 header cell）
  const { resizableColumns, components: resizableComponents } = useResizableColumns(
    FILE_TABLE_TKEY,
    columns
  );

  const visibleColumns = useMemo(
    () => resolveVisibleColumns(resizableColumns, containerWidth, showSelection ? 48 : 0),
    [resizableColumns, containerWidth, showSelection]
  );

  // 【2026-08-30 全列固定宽】表尾填充列：吸收容器剩余宽度。所有列均为固定
  //   宽度列后，若没有无宽度列，tableLayout:fixed 会把剩余空间按比例摊给
  //   全部列，导致拖动宽度失真；填充列无宽度、无内容，antd 默认表格无竖向
  //   边框，视觉不可见。拦截行事件，避免点击表尾空白区误触行操作。
  const tableColumns = useMemo(
    () => [...visibleColumns, FILLER_COLUMN],
    [visibleColumns]
  );

  // 横向滚动兜底：可见列总宽超过容器时出横向滚动条（弹性列时代的固定 640 兜底
  // 改为按实际总宽计算，拖宽列后窄容器下依然可完整横向滚动查看）
  const scrollX = useMemo(() => {
    const total = visibleColumns.reduce(
      (sum, col) => sum + (typeof col.width === 'number' ? col.width : 0),
      showSelection ? 48 : 0
    );
    return Math.max(640, total);
  }, [visibleColumns, showSelection]);

  return (
    <div ref={containerRef}>
      <Table
      columns={tableColumns}
      components={resizableComponents}
      dataSource={dataSource}
      // 【修复 2026-07-17】取消整表 loading 灰色遮罩
      // 加载提示改由 Explorer 顶部轻量进度条承担，避免整张表变灰闪烁
      loading={false}
      rowKey="key"
      // 【2026-08-30 全列固定宽 + 可拖动】
      //   - 所有列（含文件名列）均为固定宽度列，宽度可拖动调整并持久化
      //     （见 columnVisibility.js 顶部说明与 useColumns 各列定义）
      //   - 表尾填充列吸收容器剩余宽度，保证拖动精度且视觉无感
      //   - sticky：文件较多时表头粘性固定，内容滚动，表头保持可见
      //   - 响应式列显隐：容器放不下全部列时按 创建人→大小→类型→路径 顺序
      //     隐藏次要列（见 columnVisibility.js），正常窄屏不出滚动条
      //   - scroll.x 按可见列总宽动态计算：次要列全部隐藏后仍放不下时，
      //     表格保持总宽出横向滚动，列宽不被压缩
      tableLayout="fixed"
      sticky={!isSearching}
      scroll={{ x: scrollX }}
      rowClassName={() => interactionDisabled ? 'explorer-row-disabled' : ''}
      rowSelection={showSelection ? {
        selectedRowKeys: safeSelectedRowKeys,
        onChange: onSelectChange,
        type: 'checkbox',
        // 目录切换未命中缓存时禁用选择框，防止对旧目录数据执行批量操作
        getCheckboxProps: () => interactionDisabled ? { disabled: true } : {},
        // 【2026-07-17 列宽修复】固定选择列宽度 48px，避免 antd 默认值漂移
        columnWidth: 48,
      } : null}
      onRow={onRow}
      pagination={tablePagination}
      onChange={onTableChange}
      onHeaderRow={() => ({
        onContextMenu: (e) => {
          e.preventDefault();
          e.stopPropagation();
        },
      })}
      locale={{ emptyText }}
      />
    </div>
  );
};

export default React.memo(FileTable);
