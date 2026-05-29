/**
 * 日期处理工具函数
 * Date Utilities
 * 
 * 第一阶段重构：基础设施
 */
import moment from 'moment';

/**
 * 格式化日期为字符串
 * @param {moment|Date|string} date - 日期对象
 * @param {string} format - 格式，默认 'YYYY-MM-DD'
 * @returns {string}
 */
export const formatDate = (date, format = 'YYYY-MM-DD') => {
  if (!date) return '';
  return moment(date).format(format);
};

/**
 * 获取月份的起始和结束日期
 * @param {moment} date - 日期
 * @returns {{start: moment, end: moment}}
 */
export const getMonthRange = (date) => {
  const start = date.clone().startOf('month');
  const end = date.clone().endOf('month');
  return { start, end };
};

/**
 * 获取前后月份的日期范围（用于日历显示）
 * @param {moment} date - 当前日期
 * @returns {Array<{year: number, month: number}>}
 */
export const getExtendedMonthRange = (date) => {
  const months = [];
  const prevMonth = date.clone().subtract(1, 'month');
  const nextMonth = date.clone().add(1, 'month');
  
  [prevMonth, date, nextMonth].forEach(m => {
    months.push({ year: m.year(), month: m.month() + 1 });
  });
  
  // 去重
  return months.filter((m, index, self) => 
    index === self.findIndex(t => t.year === m.year && t.month === m.month)
  );
};

/**
 * 判断日期是否在同一月
 * @param {moment} date1 
 * @param {moment} date2 
 * @returns {boolean}
 */
export const isSameMonth = (date1, date2) => {
  return date1.year() === date2.year() && date1.month() === date2.month();
};

/**
 * 判断日期是否在同一天
 * @param {moment} date1 
 * @param {moment} date2 
 * @returns {boolean}
 */
export const isSameDay = (date1, date2) => {
  return date1.format('YYYY-MM-DD') === date2.format('YYYY-MM-DD');
};

/**
 * 获取今天的日期字符串
 * @returns {string} YYYY-MM-DD
 */
export const getToday = () => {
  return moment().format('YYYY-MM-DD');
};

/**
 * 解析日期字符串为moment对象
 * @param {string} dateStr - 日期字符串
 * @returns {moment|null}
 */
export const parseDate = (dateStr) => {
  if (!dateStr) return null;
  const m = moment(dateStr, 'YYYY-MM-DD');
  return m.isValid() ? m : null;
};

/**
 * 获取日期是周几（0=周日，6=周六）
 * @param {moment|string} date 
 * @returns {number}
 */
export const getDayOfWeek = (date) => {
  return moment(date).day();
};

/**
 * 判断是否为工作日（周一到周五）
 * @param {moment|string} date 
 * @returns {boolean}
 */
export const isWeekday = (date) => {
  const day = getDayOfWeek(date);
  return day >= 1 && day <= 5;
};

/**
 * 判断是否为周末
 * @param {moment|string} date 
 * @returns {boolean}
 */
export const isWeekend = (date) => {
  const day = getDayOfWeek(date);
  return day === 0 || day === 6;
};

/**
 * 获取两个日期之间的天数差
 * @param {moment|string} date1 
 * @param {moment|string} date2 
 * @returns {number}
 */
export const daysBetween = (date1, date2) => {
  const d1 = moment(date1);
  const d2 = moment(date2);
  return Math.abs(d2.diff(d1, 'days'));
};
