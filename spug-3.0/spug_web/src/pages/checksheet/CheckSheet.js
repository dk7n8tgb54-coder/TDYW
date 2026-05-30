/**
 * Copyright (c) OpenSpug Organization. https://github.com/openspug/spug
 * Copyright (c) <spug.dev@gmail.com>
 * Released under the AGPL-3.0 License.
 */
import React from 'react';
import { observer } from 'mobx-react';
import { Card, Button, Divider, Space } from 'antd';
import { SaveOutlined } from '@ant-design/icons';
import { AuthButton } from 'components';
import { useCheckSheetData, useCheckSheetUI, useCheckSheetSave } from './hooks';
import CheckSheetTable from './components/CheckSheetTable';
import StatsPanel from './components/StatsPanel';
import ConfirmModal from './components/ConfirmModal';
import LegendPanel from './components/LegendPanel';
import './CheckSheet.css';

export default observer(function CheckSheet() {
  const currentUser = sessionStorage.getItem('nickname') || '';

  const {
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
    updateDailySummaryField,
    calculateStats
  } = useCheckSheetData();

  const { handleSave } = useCheckSheetSave(allProjectsData, loaded, confirmedOperator, todayDay, selectedYear, selectedMonth);

  const {
    confirmVisible,
    setConfirmVisible,
    handleRightClick,
    handleConfirmSignature
  } = useCheckSheetUI(allProjectsData, loaded, confirmedOperator, updateDailySummaryField);

  const stats = calculateStats();

  return (
    <div className="checksheet-container">
      <Card>
        <div style={{ marginBottom: 16, display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
          <Space size="middle">
            <span style={{ fontSize: '16px', fontWeight: 'bold' }}>{selectedYear}年{selectedMonth}月{todayDay}日 日检查表录入</span>
            <Button type="primary" onClick={handleLoadAllData}>加载数据</Button>
          </Space>
          <Space size="middle">
            <AuthButton auth="checksheet.checksheet.edit" type="default" onClick={() => handleConfirmSignature(currentUser)}>
              {confirmedOperator ? '已签字' : '签字确认'}
            </AuthButton>
            <AuthButton auth="checksheet.checksheet.edit" type="primary" icon={<SaveOutlined />} onClick={handleSave}>保存</AuthButton>
          </Space>
        </div>

        <Divider />

        <div style={{ marginBottom: 16 }}>
          <Space>
            <Button size="small" onClick={() => handleBatchFill('NORMAL')}>全部设为正常</Button>
            <Button size="small" onClick={() => handleBatchFill('UNCHECKED')}>全部重置</Button>
          </Space>
        </div>

        {loaded && (
          <div>
            <StatsPanel stats={stats} />
            <CheckSheetTable
              allProjectsData={allProjectsData}
              getTotalRows={getTotalRows}
              handleCellClick={handleCellClick}
              handleRightClick={handleRightClick}
              updateDailySummaryField={updateDailySummaryField}
            />
          </div>
        )}

        <Divider />
        <LegendPanel />

        <ConfirmModal
          visible={confirmVisible}
          onOk={() => {
            handleConfirmOk(currentUser);
            setConfirmVisible(false);
          }}
          onCancel={() => setConfirmVisible(false)}
          currentUser={currentUser}
        />
      </Card>
    </div>
  );
});
