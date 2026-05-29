/**
 * Copyright (c) OpenSpug Organization. https://github.com/openspug/spug
 * Copyright (c) <spug.dev@gmail.com>
 * Released under the AGPL-3.0 License.
 */
import React, { useState, useEffect, useCallback, useRef } from 'react';
import { observer } from 'mobx-react';
import { Modal, Button, message, Card, Row, Col, Tag, Spin, Tooltip } from 'antd';
import moment from 'moment';
import store from './stores';

/**
 * 班次调整组件
 * 支持拖拽人员到不同日期，完成后自动生成替班/换班记录
 */
const ShiftAdjust = observer(({ onClose }) => {
  // 组件挂载状态跟踪
  const isMountedRef = useRef(true);

  // 状态管理
  const [isLoading, setIsLoading] = useState(false);
  const [adjustMode, setAdjustMode] = useState(false);
  const [draggedItem, setDraggedItem] = useState(null);
  const [dragOverDate, setDragOverDate] = useState(null);
  const [saving, setSaving] = useState(false);

  // 临时排班状态（调整过程中的临时数据）
  const [tempSchedule, setTempSchedule] = useState([]);
  // 原始排班快照（用于对比生成换班/替班记录）
  const [originSchedule, setOriginSchedule] = useState([]);

  // 日期范围（当前月）
  const [dateRange, setDateRange] = useState([]);

  // 初始化：加载排班数据并进入调整模式
  useEffect(() => {
    const initAdjustMode = async () => {
      try {
        setIsLoading(true);

        // 获取当前月份的排班数据
        const year = store.currentDate.year();
        const month = store.currentDate.month() + 1;
        await store.fetchSchedule(year, month);

        if (!isMountedRef.current) return;

        // 获取当前月份的所有日期
        const daysInMonth = store.currentDate.daysInMonth();
        const dates = [];
        for (let i = 1; i <= daysInMonth; i++) {
          dates.push(store.currentDate.clone().date(i).format('YYYY-MM-DD'));
        }
        setDateRange(dates);

        // 保存原始排班快照
        setOriginSchedule(JSON.parse(JSON.stringify(store.scheduleList)));

        // 初始化临时排班状态
        setTempSchedule([...store.scheduleList]);

        setAdjustMode(true);
      } catch (e) {
        if (!isMountedRef.current) return;
        console.error('[排班] 初始化班次调整失败:', e);
        message.error('加载数据失败，请重试');
        onClose();
      } finally {
        if (isMountedRef.current) setIsLoading(false);
      }
    };

    initAdjustMode();

    return () => {
      isMountedRef.current = false;
      setDraggedItem(null);
      setDragOverDate(null);
    };
  }, []);

  // 构建日期-人员矩阵数据
  const getScheduleMatrix = useCallback(() => {
    const matrix = {};
    dateRange.forEach(date => {
      matrix[date] = tempSchedule.filter(s => s.schedule_date === date);
    });
    return matrix;
  }, [dateRange, tempSchedule]);

  // 开始拖拽
  const handleDragStart = (e, schedule) => {
    setDraggedItem(schedule);
    e.dataTransfer.effectAllowed = 'move';
    e.dataTransfer.setData('text/plain', JSON.stringify(schedule));
  };

  // 拖拽进入
  const handleDragOver = (e, date) => {
    e.preventDefault();
    setDragOverDate(date);
  };

  // 拖拽离开
  const handleDragLeave = () => {
    setDragOverDate(null);
  };

  // 拖拽放下（执行调整）
  const handleDrop = (e, targetDate) => {
    e.preventDefault();
    setDragOverDate(null);

    if (!draggedItem) return;


    const sourceDate = draggedItem.schedule_date;

    // 检查是否是同一天
    if (sourceDate === targetDate) {
      message.info('请拖拽到不同的日期');
      return;
    }

    // 查找目标日期的所有排班
    const targetDateSchedules = tempSchedule.filter(s => s.schedule_date === targetDate);

    // 检查目标日期是否已有相同人员
    const hasSameStaff = targetDateSchedules.some(s => s.staff_id === draggedItem.staff_id);
    if (hasSameStaff) {
      message.error(`${draggedItem.staff_name} 已在 ${targetDate} 排班，同一天不能重复排班`);
      setDraggedItem(null);
      return;
    }

    // 只移动拖动的标签到目标日期，不交换
    setTempSchedule(prev => {
      return prev.map(s => {
        if (s.id === draggedItem.id) {
          return {
            ...s,
            schedule_date: targetDate
          };
        }
        return s;
      });
    });

    setDraggedItem(null);
  };

  // 撤销调整：恢复到原始状态
  const handleUndo = () => {
    setTempSchedule([...originSchedule]);
    setDraggedItem(null);
    setDragOverDate(null);
    message.info('已撤销调整');
  };

  // 完成调整：仅保存排班调整
  const handleComplete = () => {
    // 统计调整的记录数
    const adjustedSchedules = tempSchedule.filter(temp => {
      const origin = originSchedule.find(o => o.id === temp.id);
      if (!origin) return false;
      return origin.schedule_date !== temp.schedule_date;
    });

    if (adjustedSchedules.length === 0) {
      message.info('没有进行任何调整');
      return;
    }

    Modal.confirm({
      title: '确认保存',
      content: `确认保存本次调整？共 ${adjustedSchedules.length} 条排班记录将被修改`,
      okText: '确认保存',
      cancelText: '取消',
      okButtonProps: { loading: saving },
      onOk: async () => {
        if (saving) return;
        await saveAdjustments(adjustedSchedules.length);
      }
    });
  };

  // 保存调整（仅修改排班，不生成换班/替班记录）
  const saveAdjustments = async (adjustedCount) => {
    try {
      setSaving(true);

      // 对比原始快照，仅保存真正有变化的记录
      const adjustedSchedules = tempSchedule.filter(temp => {
        const origin = originSchedule.find(o => o.id === temp.id);
        if (!origin) return false;
        return origin.schedule_date !== temp.schedule_date;
      });

      if (adjustedSchedules.length === 0) {
        if (isMountedRef.current) {
          message.info('没有需要保存的调整');
        }
        onClose();
        return;
      }

      // 移除前端临时字段
      const submitData = adjustedSchedules.map(item => {
        const { is_adjusted, ...rest } = item;
        return rest;
      });

      await store.batchAdjustSchedule(submitData);

      if (isMountedRef.current) {
        message.success(`班次调整保存成功！已更新 ${adjustedCount} 条排班记录`);
        onClose();
      }
    } catch (e) {
      if (isMountedRef.current) {
        console.error('[排班] 保存调整失败:', e);
        message.error('保存失败：' + (e.message || '未知错误'));
      }
    } finally {
      if (isMountedRef.current) {
        setSaving(false);
      }
    }
  };

  const scheduleMatrix = getScheduleMatrix();

  if (isLoading) {
    return (
      <div style={{ textAlign: 'center', padding: 60 }}>
        <Spin size="large" tip="正在加载数据..." />
      </div>
    );
  }

  // 空数据提示
  if (tempSchedule.length === 0) {
    return (
      <Modal visible={adjustMode} title="班次调整" width={1200} onCancel={onClose} footer={null}>
        <div style={{ textAlign: 'center', padding: 60 }}>
          <p style={{ color: '#999' }}>当月暂无排班数据，无法调整</p>
          <Button onClick={onClose} type="primary">关闭</Button>
        </div>
      </Modal>
    );
  }

  return (
    <Modal
      visible={adjustMode}
      title="班次调整"
      width={1200}
      onCancel={onClose}
      footer={[
        <Button key="undo" onClick={handleUndo} disabled={saving}>
          撤销调整
        </Button>,
        <Button key="complete" type="primary" onClick={handleComplete} disabled={saving}>
          完成调整
        </Button>
      ]}
      maskClosable={false}
    >
      <div style={{ marginBottom: 16 }}>
        <p style={{ color: '#999', fontSize: 12 }}>
          提示：拖动人员姓名标签到不同日期，完成后点击"完成调整"保存
        </p>
      </div>

      <Spin spinning={saving}>
        <Row gutter={[8, 8]}>
          {dateRange.map(date => {
            const daySchedules = scheduleMatrix[date] || [];
            const isDragOver = dragOverDate === date;
            const isHoliday = moment(date).day() === 0 || moment(date).day() === 6;

            return (
              <Col key={date} span={4}>
                <Card
                  size="small"
                  style={{
                    minHeight: 120,
                    backgroundColor: isDragOver ? '#e6f7ff' : (isHoliday ? '#f5f5f5' : '#fff'),
                    border: isDragOver ? '2px dashed #1890ff' : '1px solid #d9d9d9',
                    cursor: 'default'
                  }}
                  onDragOver={(e) => handleDragOver(e, date)}
                  onDragLeave={handleDragLeave}
                  onDrop={(e) => handleDrop(e, date)}
                >
                  <div style={{ fontWeight: 'bold', marginBottom: 8, fontSize: 14 }}>
                    {moment(date).format('MM-DD')}
                    {isHoliday && <Tag color="orange" style={{ marginLeft: 4 }}>周末</Tag>}
                  </div>
                  <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
                    {daySchedules.map(schedule => (
                      <Tooltip
                        key={schedule.id}
                        title={`${schedule.staff_name} - ${schedule.shift_name}`}
                      >
                        <Tag
                          draggable
                          onDragStart={(e) => handleDragStart(e, schedule)}
                          style={{
                            cursor: 'move',
                            userSelect: 'none',
                            padding: '4px 8px',
                            fontSize: 12
                          }}
                        >
                          {schedule.staff_name}
                          {schedule.shift_name && ` (${schedule.shift_name})`}
                        </Tag>
                      </Tooltip>
                    ))}
                    {daySchedules.length === 0 && (
                      <div style={{ color: '#ccc', fontSize: 12, textAlign: 'center' }}>
                        无排班
                      </div>
                    )}
                  </div>
                </Card>
              </Col>
            );
          })}
        </Row>
      </Spin>
    </Modal>
  );
});

export default ShiftAdjust;
