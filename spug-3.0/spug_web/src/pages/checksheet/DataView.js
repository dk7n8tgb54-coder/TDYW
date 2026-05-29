/**
 * Copyright (c) OpenSpug Organization. https://github.com/openspug/spug
 * Copyright (c) <spug.dev@gmail.com>
 * Released under the AGPL-3.0 License.
 */
import React from 'react';
import { observer } from 'mobx-react';
import { Card } from 'antd';
import { useDataViewQuery, useDataViewExport } from './hooks';
import QueryControls from './components/QueryControls';
import StatsCard from './components/StatsCard';
import DataViewTable from './components/DataViewTable';

export default observer(function DataView() {
  const {
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
  } = useDataViewQuery();

  const { handleExportPDF } = useDataViewExport(viewData, selectedYear, selectedMonth, days);

  const totalStats = calculateTotalStats();

  return (
    <Card>
      <QueryControls
        years={years}
        months={months}
        selectedYear={selectedYear}
        selectedMonth={selectedMonth}
        onYearChange={setSelectedYear}
        onMonthChange={setSelectedMonth}
        onQuery={handleQuery}
        onExport={handleExportPDF}
      />

      {viewData && (
        <div style={{ padding: '20px', backgroundColor: '#fff' }}>
          <StatsCard stats={totalStats} />
          <DataViewTable
            viewData={viewData}
            days={days}
            selectedYear={selectedYear}
            selectedMonth={selectedMonth}
          />
        </div>
      )}
    </Card>
  );
});
