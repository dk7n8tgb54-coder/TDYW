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

    // P1-3 修复：按"模板检查项数量 × 当月天数"统计，缺失记录视为 UNCHECKED，
    // 避免后端无记录时统计显示总数 0。
    // 当月天数：new Date(year, month, 0).getDate()，month 传 1-12 时取上月末尾即当月天数。
    const yearInt = parseInt(selectedYear, 10);
    const monthInt = parseInt(selectedMonth, 10);
    const daysInMonth = new Date(yearInt, monthInt, 0).getDate();

    let total = 0, normal = 0, abnormal = 0, unchecked = 0;

    Object.values(viewData).forEach(projectData => {
      const itemCount = projectData?.template?.check_items?.length || 0;
      if (itemCount === 0) return;

      // 把已存在记录按 `${item_index}_${day}` 建索引
      const recordMap = {};
      (projectData.records || []).forEach(r => {
        recordMap[`${r.item_index}_${r.day}`] = r.status;
      });

      for (let index = 0; index < itemCount; index++) {
        for (let day = 1; day <= daysInMonth; day++) {
          const status = recordMap[`${index}_${day}`] || 'UNCHECKED';
          total++;
          if (status === 'NORMAL') normal++;
          else if (status === 'ABNORMAL') abnormal++;
          else unchecked++;
        }
      }
    });

    return { total, normal, abnormal, unchecked };
  }, [viewData, selectedYear, selectedMonth]);

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
