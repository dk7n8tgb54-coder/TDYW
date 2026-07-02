/**
 * Copyright (c) OpenSpug Organization. https://github.com/openspug
 * Copyright: (c) <spug.dev@gmail.com>
 * Released under the AGPL-3.0 License.
 */
import React, { useState, useMemo } from 'react';
import { observer } from 'mobx-react';
import { Select, Divider, message, Modal } from 'antd';
import { PlusOutlined, DeleteOutlined } from '@ant-design/icons';
import { http, hasPermission } from 'libs';
import store from '../store';

const { Option } = Select;

/**
 * 升级系统选择器（搜索 + 选择 + 新增 + 移除）
 *
 * 数据源：store.systems（仅字典表 active 项）
 *   - 列表筛选用 filterOptions.systems（含历史兜底，停用的系统仍可筛选旧记录）
 *   - 本组件用 store.systems（仅 active，停用后立即从下拉消失）
 *
 * 关键：用 observer 包裹以响应 store.systems 的 mobx 变化，
 *       删除/新增后乐观更新 store，下拉列表即时刷新，无需重新输入或刷新页面。
 */
function SystemSelect({ value, onChange, placeholder = '请选择或输入系统', disabled, style }) {
  const [keyword, setKeyword] = useState('');
  const [adding, setAdding] = useState(false);

  // systems 是对象数组 [{id, name, sort_order}]（mobx observable，observer 自动追踪）
  const systems = store.systems || [];
  const systemNames = systems.map(s => s.name);
  const canAdd = hasPermission('upgrade.upgrade.edit');
  const canManage = hasPermission('upgrade.system.manage');

  // 大小写不敏感判断 keyword 是否已存在于候选项
  const existed = useMemo(() => {
    const kw = (keyword || '').trim();
    if (!kw) return true;
    return systemNames.some(s => s.toLowerCase() === kw.toLowerCase());
  }, [keyword, systemNames]);

  function handleAdd() {
    const name = (keyword || '').trim();
    if (!name) {
      message.warning('请先输入系统名称');
      return;
    }
    setAdding(true);
    http.post('/api/upgrade/systems/create/', { name })
      .then(res => {
        // 乐观更新：立即追加到本地 store，下拉即时显示
        store.addSystem({ id: res.id, name: res.name, sort_order: res.sort_order });
        if (onChange) onChange(res.name);
        message.success(res.existed ? `系统「${res.name}」已存在，已自动选中` : `已新增系统「${res.name}」`);
        setKeyword('');
        // 异步同步 filter-options（保证列表筛选也同步），不阻塞 UI
        store.fetchFilterOptions().catch(() => {});
      })
      .catch(() => {})
      .finally(() => setAdding(false));
  }

  function handleRemove(sys) {
    Modal.confirm({
      title: '移除系统候选项',
      content: `确定要从候选列表移除「${sys.name}」吗？${'\n'}已有升级记录使用该系统时将改为停用（不影响已有记录）。`,
      okText: '移除',
      okButtonProps: { danger: true },
      cancelText: '取消',
      onOk: () => {
        return http.delete(`/api/upgrade/systems/${sys.id}/delete/`)
          .then(res => {
            // 乐观更新：立即从本地 store 移除，下拉即时消失（observer 自动重渲染）
            store.removeSystem(sys.name);
            // 如果当前选中的正是被移除的系统，清空选择
            if (value === sys.name && onChange) {
              onChange(undefined);
              message.warning('当前选中的系统已被移除，请重新选择');
            } else {
              message.success(res.msg || '已移除');
            }
            // 异步同步 filter-options（列表筛选数据源），不阻塞 UI
            store.fetchFilterOptions().catch(() => {});
          })
          .catch(() => {});
      },
    });
  }

  return (
    <Select
      showSearch
      allowClear
      value={value}
      onChange={onChange}
      onSearch={setKeyword}
      onClear={() => setKeyword('')}
      onBlur={() => setKeyword('')}
      disabled={disabled}
      style={style}
      placeholder={placeholder}
      filterOption={(input, option) => {
        // option.children 可能是数组（文本 + 图标），取纯文本部分匹配
        const text = typeof option.children === 'string'
          ? option.children
          : Array.isArray(option.children) ? String(option.children[0] || '') : '';
        return text.toLowerCase().indexOf((input || '').toLowerCase()) >= 0;
      }}
      dropdownRender={menu => (
        <>
          {menu}
          {canAdd && !existed && (keyword || '').trim() && (
            <>
              <Divider style={{ margin: '4px 0' }} />
              <div
                onMouseDown={e => e.preventDefault()}
                onClick={handleAdd}
                style={{ padding: '5px 12px', cursor: 'pointer', color: '#1890ff' }}
              >
                <PlusOutlined /> 新增&ldquo;{keyword.trim()}&rdquo;
              </div>
            </>
          )}
        </>
      )}
    >
      {systems.map(item => (
        <Option value={item.name} key={item.name}>
          <span>{item.name}</span>
          {canManage && (
            <DeleteOutlined
              onMouseDown={e => { e.preventDefault(); e.stopPropagation(); }}
              onClick={e => { e.preventDefault(); e.stopPropagation(); handleRemove(item); }}
              style={{ float: 'right', color: '#ff4d4f', marginTop: 2 }}
              title="从候选列表移除"
            />
          )}
        </Option>
      ))}
    </Select>
  );
}

export default observer(SystemSelect);
