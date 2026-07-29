/**
 * 搜索结果分组展示组件
 * 【任务4.2】从Explorer组件拆分出来的子组件
 * 职责：展示按类型分组的搜索结果
 */
import React from 'react';
import { Empty } from 'antd';
import FileTable from './FileTable';

/**
 * 搜索结果分组展示组件
 * @param {Object} props - 组件属性
 * @param {Array} props.groups - 分组数据
 * @param {Array} props.columns - 表格列配置
 * @param {boolean} props.loading - 加载状态
 * @param {Array} props.selectedRowKeys - 选中的行keys
 * @param {Function} props.onSelectChange - 选中变化回调
 * @param {Function} props.onRow - 行事件处理
 */
const SearchResults = ({
  groups,
  columns,
  loading,
  selectedRowKeys,
  onSelectChange,
  onRow,
  showSelection = true,
}) => {
  if (!groups || groups.length === 0) {
    return <Empty description="未找到匹配的文件" />;
  }

  return (
    <div style={{ padding: '0 16px' }}>
      {groups.map((group) => (
        <div key={group.key} style={{ marginBottom: 24 }}>
          <div
            style={{
              fontSize: 16,
              fontWeight: 'bold',
              marginBottom: 12,
              padding: '8px 0',
              borderBottom: '1px solid #f0f0f0',
              color: '#262626',
            }}
          >
            {group.title}
            <span
              style={{
                fontSize: 14,
                fontWeight: 'normal',
                color: '#8c8c8c',
                marginLeft: 8,
              }}
            >
              ({group.items.length}个)
            </span>
          </div>
          <FileTable
            columns={columns}
            dataSource={group.items}
            loading={loading}
            selectedRowKeys={selectedRowKeys}
            onSelectChange={onSelectChange}
            onRow={onRow}
            showPagination={false}
            showSelection={showSelection}
            isSearching={true}
          />
        </div>
      ))}
    </div>
  );
};

export default React.memo(SearchResults);
