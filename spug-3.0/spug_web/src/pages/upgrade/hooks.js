/**
 * Copyright (c) OpenSpug Organization. https://github.com/openspug/spug
 * Copyright: (c) <spug.dev@gmail.com>
 * Released under the AGPL-3.0 License.
 */
import { useState, useEffect } from 'react';
import { http } from 'libs';
import moment from 'moment';
import store from './store';

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
 * 查看/编辑模式：把 store.record 同步进表单（system 表单值为系统档案 ID）。
 */
export function useSyncRecordToForm(form, isNew) {
  useEffect(() => {
    if (!isNew && store.record.id) {
      form.setFieldsValue({
        ...store.record,
        system: store.record.system_id,
        upgrade_time: store.record.upgrade_time ? moment(store.record.upgrade_time) : null,
      });
    }
    // form 为 useForm 稳定实例；store.record 是 observable，
    // 依赖 store.record 是刻意的 mobx 刷新模式（与仓库其他页面一致）
  }, [store.record, isNew]);
}
