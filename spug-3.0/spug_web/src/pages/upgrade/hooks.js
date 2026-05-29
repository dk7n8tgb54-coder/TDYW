/**
 * Copyright (c) OpenSpug Organization. https://github.com/openspug/spug
 * Copyright: (c) <spug.dev@gmail.com>
 * Released under the AGPL-3.0 License.
 */
import { useState, useEffect } from 'react';
import { http } from 'libs';

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
