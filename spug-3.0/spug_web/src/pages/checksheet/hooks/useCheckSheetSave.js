/**
 * Copyright (c) OpenSpug Organization. https://github.com/openspug/spug
 * Copyright (c) <spug.dev@gmail.com>
 * Released under the AGPL-3.0 License.
 */
import { useCallback } from 'react';
import { message } from 'antd';
import store from '../store';

export default function useCheckSheetSave(allProjectsData, loaded, confirmedOperator, todayDay, selectedYear, selectedMonth) {
  const handleSave = useCallback(async () => {
    if (!loaded) {
      message.warning('请先加载数据');
      return;
    }

    if (!confirmedOperator) {
      message.warning('请先进行签字确认');
      return;
    }

    try {
      const savePromises = Object.keys(allProjectsData).map(project => {
        const projectData = allProjectsData[project];
        const records = Object.entries(projectData.checkData).map(([key, value]) => ({
          item_index: parseInt(key),
          day: todayDay,
          status: value.status
        }));

        const payload = {
          year: selectedYear,
          month: selectedMonth,
          day: todayDay,
          project,
          records,
          signatures: {
            operator: confirmedOperator
          },
          daily_summary: projectData.dailySummary
        };
        return store.saveCheckRecords(payload);
      });

      await Promise.all(savePromises);
      message.success('保存成功');
    } catch (error) {
      console.error('保存失败:', error);
      message.error('保存失败，请重试');
    }
  }, [allProjectsData, loaded, confirmedOperator, todayDay, selectedYear, selectedMonth]);

  return { handleSave };
}
