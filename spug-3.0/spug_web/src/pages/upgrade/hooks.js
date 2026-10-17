/**
 * Copyright (c) OpenSpug Organization. https://github.com/openspug/spug
 * Copyright: (c) <spug.dev@gmail.com>
 * Released under the AGPL-3.0 License.
 */
import { useState, useEffect, useRef } from 'react';
import { http } from 'libs';
import moment from 'moment';
import store from './store';
import { submitUpgradeForm } from './workbenchActions';

/**
 * 筛选选项 Hook
 */
export function useFilterOptions() {
  const [options, setOptions] = useState({ systems: [], statuses: [], upgradeTypes: [] });
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    setLoading(true);
    http.get('/api/upgrade/filter-options/')
      .then(res => setOptions({
        systems: res.systems || [],
        statuses: res.statuses || [],
        upgradeTypes: res.upgrade_types || [],
      }))
      .catch(() => {})
      .finally(() => setLoading(false));
  }, []);

  return { options, loading };
}

/**
 * store.record → 表单值映射（system 表单值为系统档案 ID）。
 * 编辑基本信息面板打开/取消恢复时复用同一映射，保证回灌口径一致。
 */
export function recordToFormValues(record) {
  return {
    ...record,
    system: record.system_id,
    upgrade_time: record.upgrade_time ? moment(record.upgrade_time) : null,
  };
}

/**
 * 查看/编辑模式的"编辑基本信息"面板状态与动作。
 * 保存经 submitUpgradeForm(redirectMode='inline')，成功后留在工作台并刷新主记录；
 * 取消恢复为已保存数据（store.record 即服务端最新已保存值）。
 */
export function useBasicInfoEditor(form, recordId) {
  const [editVisible, setEditVisible] = useState(false);
  const [saving, setSaving] = useState(false);

  function toggleEdit() {
    setEditVisible(v => !v);
  }

  function cancelEdit() {
    form.resetFields();
    form.setFieldsValue(recordToFormValues(store.record));
    setEditVisible(false);
  }

  function saveEdit() {
    submitUpgradeForm({
      form, isNew: false, recordId, redirectMode: 'inline',
      onSaveStart: () => setSaving(true),
      onSaveEnd: () => setSaving(false),
      onSaveSuccess: () => {
        setSaving(false);
        setEditVisible(false);
        // 清除 touched 让 useSyncRecordToForm 在重取后回灌最新已保存值
        form.resetFields();
        store.fetchRecord(recordId).catch(() => {});
      },
      onSaveError: () => setSaving(false),
    });
  }

  return {editVisible, saving, toggleEdit, cancelEdit, saveEdit};
}

/**
 * 查看/编辑模式：把 store.record 同步进表单（system 表单值为系统档案 ID）。
 *
 * 同一条记录的重复重取（如删除状态日志后刷新主记录）不回灌表单：
 * 用户已在编辑面板改动但未保存的字段不被服务端旧值静默覆盖；
 * 换了记录（id 变化）或表单未被触碰时正常回灌。
 */
export function useSyncRecordToForm(form, isNew) {
  const syncedIdRef = useRef(null);
  useEffect(() => {
    if (isNew || !store.record.id) return;
    const sameRecord = syncedIdRef.current === store.record.id;
    if (sameRecord && form.isFieldsTouched()) return;
    syncedIdRef.current = store.record.id;
    form.setFieldsValue(recordToFormValues(store.record));
    // form 为 useForm 稳定实例；store.record 是 observable，
    // 依赖 store.record 是刻意的 mobx 刷新模式（与仓库其他页面一致）
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [store.record, isNew]);
}
