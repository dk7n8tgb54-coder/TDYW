/**
 * Copyright (c) OpenSpug Organization. https://github.com/openspug/spug
 * Copyright (c) <spug.dev@gmail.com>
 * Released under the AGPL-3.0 License.
 */
import { useState, useCallback } from 'react';
import { message } from 'antd';
import store from '../store';

// P1-7 修复：改为工厂函数，每次调用时计算当前日期（避免模块级别常量跨午夜不更新）
const getInitialDate = () => {
  const today = new Date();
  return {
    todayDay: today.getDate(),
    selectedYear: today.getFullYear().toString(),
    selectedMonth: (today.getMonth() + 1).toString().padStart(2, '0')
  };
};

export default function useCheckSheetData() {
  const { todayDay: initDay, selectedYear: initYear, selectedMonth: initMonth } = getInitialDate();
  const [allProjectsData, setAllProjectsData] = useState({});
  const [loaded, setLoaded] = useState(false);
  const [confirmedOperator, setConfirmedOperator] = useState('');
  const [todayDay] = useState(initDay);
  const [selectedYear] = useState(initYear);
  const [selectedMonth] = useState(initMonth);

  const getTotalRows = useCallback(() => {
    return Object.values(allProjectsData).reduce((total, projectData) => {
      return total + (projectData.template?.check_items?.length || 0);
    }, 0);
  }, [allProjectsData]);

  const handleLoadAllData = useCallback(async () => {
    if (store.projects.length === 0) {
      message.warning('暂无检查项目');
      return;
    }

    try {
      const results = await Promise.all(store.projects.map(async (project) => {
        const data = await store.fetchCheckRecords(selectedYear, selectedMonth, project, todayDay);
        return { project, data };
      }));

      const projectsData = {};
      results.forEach(({ project, data }) => {
        if (data.template && data.records) {
          const dailySummary = data.daily_summaries && data.daily_summaries[todayDay] || { operator: '', remark: '', rectification: '' };

          projectsData[project] = {
            template: data.template,
            checkData: {},
            dailySummary: dailySummary
          };

          data.records.forEach(record => {
            if (record.day === todayDay) {
              const key = `${record.item_index}`;
              projectsData[project].checkData[key] = {
                status: record.status
              };
            }
          });
        }
      });

      setAllProjectsData(projectsData);
      setLoaded(true);
      message.success('数据加载成功');
    } catch (error) {
      console.error('加载数据失败:', error);
      message.error('加载数据失败');
    }
  }, []);

  const updateCellStatus = useCallback((project, itemIndex, newStatus) => {
    setAllProjectsData(prev => {
      const projectData = prev[project];
      if (!projectData) return prev;

      const key = `${itemIndex}`;
      const current = projectData.checkData[key] || { status: 'UNCHECKED', remark: '', rectification: '' };

      return {
        ...prev,
        [project]: {
          ...projectData,
          checkData: {
            ...projectData.checkData,
            [key]: { ...current, status: newStatus }
          }
        }
      };
    });
  }, []);

  const handleCellClick = useCallback((project, itemIndex) => {
    const projectData = allProjectsData[project];
    if (!projectData) return;

    const key = `${itemIndex}`;
    const current = projectData.checkData[key] || { status: 'UNCHECKED', remark: '', rectification: '' };

    if (current.status !== 'ABNORMAL') {
      const newStatus = current.status === 'UNCHECKED' ? 'NORMAL' : 'UNCHECKED';
      updateCellStatus(project, itemIndex, newStatus);
    } else {
      const newStatus = current.status === 'ABNORMAL' ? 'NORMAL' : 'ABNORMAL';
      updateCellStatus(project, itemIndex, newStatus);
    }
  }, [allProjectsData, updateCellStatus]);

  const handleBatchFill = useCallback((status) => {
    if (!loaded) {
      message.warning('请先加载数据');
      return;
    }

    const newProjectsData = {};

    Object.keys(allProjectsData).forEach(project => {
      const projectData = allProjectsData[project];
      const newCheckData = {};

      projectData.template.check_items.forEach((_, index) => {
        const key = `${index}`;
        newCheckData[key] = {
          status,
          remark: projectData.checkData[key]?.remark || '',
          rectification: projectData.checkData[key]?.rectification || ''
        };
      });

      newProjectsData[project] = {
        ...projectData,
        checkData: newCheckData
      };
    });

    setAllProjectsData(newProjectsData);
    message.success('批量填充成功');
  }, [loaded, allProjectsData]);

  const handleConfirmOk = useCallback((currentUser) => {
    setConfirmedOperator(currentUser);

    const newProjectsData = {};
    Object.keys(allProjectsData).forEach(project => {
      const projectData = allProjectsData[project];
      newProjectsData[project] = {
        ...projectData,
        dailySummary: {
          ...(projectData.dailySummary || {}),
          operator: currentUser
        }
      };
    });
    setAllProjectsData(newProjectsData);
    message.success('签字确认成功');
  }, [allProjectsData]);

  const updateDailySummaryField = useCallback((field, value) => {
    setAllProjectsData(prev => {
      const newData = {};
      Object.keys(prev).forEach(p => {
        newData[p] = {
          ...prev[p],
          dailySummary: {
            ...(prev[p].dailySummary || {}),
            [field]: value
          }
        };
      });
      return newData;
    });
  }, []);

  const calculateStats = useCallback(() => {
    const stats = { total: 0, normal: 0, abnormal: 0, unchecked: 0 };

    Object.values(allProjectsData).forEach(projectData => {
      Object.values(projectData.checkData).forEach(item => {
        stats.total++;
        if (item.status === 'NORMAL') stats.normal++;
        else if (item.status === 'ABNORMAL') stats.abnormal++;
        else stats.unchecked++;
      });
    });

    return stats;
  }, [allProjectsData]);

  return {
    allProjectsData,
    loaded,
    confirmedOperator,
    todayDay,
    selectedYear,
    selectedMonth,
    getTotalRows,
    handleLoadAllData,
    handleCellClick,
    handleBatchFill,
    handleConfirmOk,
    updateCellStatus,
    updateDailySummaryField,
    calculateStats,
    setAllProjectsData
  };
}
