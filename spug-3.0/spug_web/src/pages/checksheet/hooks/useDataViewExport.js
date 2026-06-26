/**
 * Copyright (c) OpenSpug Organization. https://github.com/openspug/spug
 * Copyright (c) <spug.dev@gmail.com>
 * Released under the AGPL-3.0 License.
 */
import { useCallback } from 'react';
import { message } from 'antd';
import { http, exportFile } from 'libs';
import store from '../store';
import { STATUS_MAP } from '../constants';

export default function useDataViewExport(viewData, selectedYear, selectedMonth, days) {
  const buildTableData = useCallback(() => {
    const tableData = [];
    const headerRow = ['项目', '检查项目'];
    days.forEach(day => headerRow.push(`${day}日`));
    tableData.push(headerRow);

    Object.entries(viewData).forEach(([project, projectData]) => {
      const checkItems = projectData.template?.check_items || [];
      checkItems.forEach((item, itemIndex) => {
        const row = [itemIndex === 0 ? project : '', item];
        days.forEach(day => {
          const record = projectData.records?.find(r => r.item_index === itemIndex && r.day === day);
          const status = record?.status || 'UNCHECKED';
          const statusInfo = STATUS_MAP[status];
          let cellValue = statusInfo.label;
          if (record?.remark) {
            cellValue += ` ${record.remark}`;
          }
          row.push(cellValue);
        });
        tableData.push(row);
      });
    });

    return tableData;
  }, [viewData, days]);

  const collectDailySummaries = useCallback(() => {
    const dailySummaries = {};
    try {
      for (const project of Object.keys(viewData)) {
        const summaries = viewData[project]?.daily_summaries;
        if (summaries) {
          Object.entries(summaries).forEach(([day, summary]) => {
            if (!dailySummaries[day]) {
              dailySummaries[day] = { rectification: '', operator: '', remark: '' };
            }
            if (summary.rectification) dailySummaries[day].rectification = summary.rectification;
            if (summary.operator) dailySummaries[day].operator = summary.operator;
            if (summary.remark) dailySummaries[day].remark = summary.remark;
          });
        }
      }
    } catch (error) {
      console.error('[PDF Export] Error collecting daily summaries:', error);
    }
    return dailySummaries;
  }, [viewData]);

  const handleExportPDF = useCallback(async () => {
    if (store.projects.length === 0) {
      message.warning('暂无检查项目');
      return;
    }
    if (!viewData) {
      message.warning('请先查询数据');
      return;
    }

    const tableData = buildTableData();
    const dailySummaries = collectDailySummaries();

    const requestData = {
      year: selectedYear,
      month: selectedMonth,
      table_data: tableData,
      daily_summaries: dailySummaries,
      title: `${selectedYear}年${selectedMonth}月 全部项目检查表`
    };

    await exportFile({
      url: '/api/checksheet/export/pdf/',
      method: 'post',
      data: requestData,
      defaultFilename: `${selectedYear}年${selectedMonth}月_全部项目检查表.pdf`,
      timeout: 60000,
      loadingText: '正在生成PDF...',
    });
  }, [viewData, selectedYear, selectedMonth, buildTableData, collectDailySummaries]);

  return { handleExportPDF };
}
