/**
 * Copyright (c) OpenSpug Organization. https://github.com/openspug/spug
 * Copyright (c) <spug.dev@gmail.com>
 * Released under the AGPL-3.0 License.
 */
import { useState, useCallback, useMemo } from 'react';
import { message } from 'antd';
import store from '../store';

export default function useDataViewQuery() {
  const [selectedYear, setSelectedYear] = useState(new Date().getFullYear().toString());
  const [selectedMonth, setSelectedMonth] = useState((new Date().getMonth() + 1).toString().padStart(2, '0'));
  const [viewData, setViewData] = useState(null);

  const years = useMemo(() => Array.from({length: 80}, (_, i) => (2021 + i).toString()), []);
  const months = useMemo(() => Array.from({length: 12}, (_, i) => (i + 1).toString().padStart(2, '0')), []);
  const days = useMemo(() => Array.from({length: 31}, (_, i) => i + 1), []);

  const handleQuery = useCallback(async () => {
    if (store.projects.length === 0) {
      message.warning('暂无检查项目');
      return;
    }

    try {
      const results = await Promise.all(store.projects.map(async (project) => {
        const data = await store.fetchCheckRecords(selectedYear, selectedMonth, project);
        return { project, data };
      }));

      const allProjectsData = {};
      results.forEach(({ project, data }) => {
        allProjectsData[project] = data;
      });
      setViewData(allProjectsData);
    } catch (error) {
      console.error('查询失败:', error);
      message.error('查询失败');
    }
  }, [selectedYear, selectedMonth]);

  const calculateTotalStats = useCallback(() => {
    if (!viewData) return { total: 0, normal: 0, abnormal: 0, unchecked: 0 };

    let total = 0, normal = 0, abnormal = 0, unchecked = 0;

    Object.values(viewData).forEach(projectData => {
      if (projectData.records) {
        projectData.records.forEach(record => {
          total++;
          if (record.status === 'NORMAL') normal++;
          else if (record.status === 'ABNORMAL') abnormal++;
          else unchecked++;
        });
      }
    });

    return { total, normal, abnormal, unchecked };
  }, [viewData]);

  return {
    selectedYear,
    setSelectedYear,
    selectedMonth,
    setSelectedMonth,
    viewData,
    years,
    months,
    days,
    handleQuery,
    calculateTotalStats
  };
}
