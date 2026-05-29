/**
 * 自动排班算法
 * Auto Schedule Algorithm
 * 
 * 第一阶段重构：基础设施
 */
import moment from 'moment';

/**
 * 生成自动排班
 * @param {Object} staff - 人员信息
 * @param {Object} shift - 班次规则
 * @param {moment} startDate - 开始日期
 * @param {moment} endDate - 结束日期
 * @param {Array} existingSchedules - 现有排班（用于冲突检查）
 * @returns {{schedules: Array, conflicts: Array}}
 */
export const generateAutoSchedule = (staff, shift, startDate, endDate, existingSchedules = []) => {
  const schedules = [];
  const conflicts = [];
  let currentDate = startDate.clone();
  
  if (shift.shift_type === 'work_rest' && shift.work_days && shift.rest_days) {
    // 上X休Y模式
    let workCount = 0;
    let restCount = 0;
    let isWorkCycle = true;
    
    while (currentDate.isSameOrBefore(endDate)) {
      const dateStr = currentDate.format('YYYY-MM-DD');
      
      if (isWorkCycle) {
        // 检查冲突
        const conflict = checkScheduleConflict(staff.id, dateStr, existingSchedules);
        if (conflict) {
          conflicts.push(dateStr);
        } else {
          schedules.push(createScheduleItem(staff, shift, dateStr));
        }
        
        workCount++;
        if (workCount >= shift.work_days) {
          workCount = 0;
          isWorkCycle = false;
        }
      } else {
        restCount++;
        if (restCount >= shift.rest_days) {
          restCount = 0;
          isWorkCycle = true;
        }
      }
      currentDate.add(1, 'day');
    }
  } else {
    // 自定义模式 - 每天排班
    while (currentDate.isSameOrBefore(endDate)) {
      const dateStr = currentDate.format('YYYY-MM-DD');
      const conflict = checkScheduleConflict(staff.id, dateStr, existingSchedules);
      
      if (conflict) {
        conflicts.push(dateStr);
      } else {
        schedules.push(createScheduleItem(staff, shift, dateStr));
      }
      currentDate.add(1, 'day');
    }
  }
  
  return { schedules, conflicts };
};

/**
 * 检查排班冲突
 * @param {number} staffId - 人员ID
 * @param {string} dateStr - 日期字符串 YYYY-MM-DD
 * @param {Array} existingSchedules - 现有排班列表
 * @returns {Object|undefined}
 */
const checkScheduleConflict = (staffId, dateStr, existingSchedules) => {
  return existingSchedules.find(s => 
    s.schedule_date === dateStr && s.staff_id === staffId
  );
};

/**
 * 创建排班项
 * @param {Object} staff - 人员信息
 * @param {Object} shift - 班次信息
 * @param {string} dateStr - 日期字符串
 * @returns {Object}
 */
const createScheduleItem = (staff, shift, dateStr) => ({
  staff_id: staff.id,
  staff_name: staff.user_name,
  schedule_date: dateStr,
  shift_id: shift.id,
  shift_name: shift.name,
});

/**
 * 检查排班列表是否有冲突
 * @param {Array} schedules - 待检查的排班列表
 * @returns {Array} 冲突列表
 */
export const checkScheduleListConflicts = (schedules) => {
  const conflicts = [];
  const seen = new Map();
  
  schedules.forEach((schedule, index) => {
    const key = `${schedule.staff_id}_${schedule.schedule_date}`;
    
    if (seen.has(key)) {
      conflicts.push({
        index,
        staff_id: schedule.staff_id,
        staff_name: schedule.staff_name,
        date: schedule.schedule_date,
        conflict_with: seen.get(key),
      });
    } else {
      seen.set(key, index);
    }
  });
  
  return conflicts;
};

/**
 * 统计排班分布
 * @param {Array} schedules - 排班列表
 * @returns {Object}
 */
export const analyzeScheduleDistribution = (schedules) => {
  const stats = {
    total: schedules.length,
    byStaff: {},
    byShift: {},
    byDate: {},
    byDayOfWeek: { 0: 0, 1: 0, 2: 0, 3: 0, 4: 0, 5: 0, 6: 0 },
  };
  
  schedules.forEach(s => {
    // 按人员统计
    stats.byStaff[s.staff_name] = (stats.byStaff[s.staff_name] || 0) + 1;
    
    // 按班次统计
    stats.byShift[s.shift_name] = (stats.byShift[s.shift_name] || 0) + 1;
    
    // 按日期统计
    stats.byDate[s.schedule_date] = (stats.byDate[s.schedule_date] || 0) + 1;
    
    // 按周几统计
    const dayOfWeek = moment(s.schedule_date).day();
    stats.byDayOfWeek[dayOfWeek]++;
  });
  
  return stats;
};

/**
 * 生成班次轮换建议
 * @param {Array} staffList - 人员列表
 * @param {Array} shiftList - 班次列表
 * @param {moment} startDate - 开始日期
 * @param {number} days - 天数
 * @returns {Array}
 */
export const generateRotationSuggestion = (staffList, shiftList, startDate, days = 30) => {
  const suggestions = [];
  let staffIndex = 0;
  let shiftIndex = 0;
  
  const currentDate = startDate.clone();
  
  for (let i = 0; i < days; i++) {
    const staff = staffList[staffIndex % staffList.length];
    const shift = shiftList[shiftIndex % shiftList.length];
    
    suggestions.push({
      staff_id: staff.id,
      staff_name: staff.user_name,
      schedule_date: currentDate.format('YYYY-MM-DD'),
      shift_id: shift.id,
      shift_name: shift.name,
    });
    
    currentDate.add(1, 'day');
    staffIndex++;
    
    // 每7天轮换一次班次
    if ((i + 1) % 7 === 0) {
      shiftIndex++;
    }
  }
  
  return suggestions;
};
