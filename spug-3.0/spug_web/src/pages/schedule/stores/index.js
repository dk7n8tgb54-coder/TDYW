/**
 * Copyright (c) OpenSpug Organization. https://github.com/openspug/spug
 * Copyright (c) <spug.dev@gmail.com>
 * Released under the AGPL-3.0 License.
 */
/**
 * Schedule模块Store入口
 * 
 * 第3阶段重构：前端Store拆分
 * 
 * 重构后架构：
 * - scheduleStore.js: 排班数据管理
 * - staffStore.js: 人员数据管理
 * - shiftStore.js: 班次数据管理
 * - swapStore.js: 换班数据管理
 * - substituteStore.js: 替班数据管理
 * 
 * 保持向后兼容的默认导出
 */

import scheduleStore from './scheduleStore';
import staffStore from './staffStore';
import shiftStore from './shiftStore';
import swapStore from './swapStore';
import substituteStore from './substituteStore';

// 组合store对象（推荐新用法）
export const stores = {
  schedule: scheduleStore,
  staff: staffStore,
  shift: shiftStore,
  swap: swapStore,
  substitute: substituteStore,
};

// ===== 全局初始化状态管理（修复P0-1竞态条件）=====
let initializationPromise = null;

/**
 * 安全地执行fetch操作，失败时不阻塞其他操作
 * @param {Function} fetchFn - fetch函数
 * @param {string} storeName - store名称（用于日志）
 * @returns {Promise<void>}
 */
async function safeFetch(fetchFn, storeName) {
  console.log(`[Schedule] 开始加载 ${storeName}...`);
  try {
    await fetchFn();
    console.log(`[Schedule] ${storeName} 加载成功`);
  } catch (error) {
    console.warn(`[Schedule] ${storeName} 加载失败:`, error.message || error);
    // 不抛出错误，允许其他store继续加载
  }
}

/**
 * 统一初始化所有Store
 * 防止多个组件同时调用导致的数据竞态条件
 * @returns {Promise<void>}
 */
export async function initializeStores() {
  console.log('[Schedule] initializeStores 被调用');
  console.log('[Schedule] initializationPromise:', initializationPromise ? '存在' : 'null');
  console.log('[Schedule] isInitialized:', stores.schedule.isInitialized);
  
  // 如果正在初始化，返回现有的Promise
  if (initializationPromise) {
    console.log('[Schedule] 正在初始化中，返回现有Promise');
    return initializationPromise;
  }
  
  // 如果已初始化，直接返回
  if (stores.schedule.isInitialized) {
    console.log('[Schedule] 已初始化，直接返回');
    return Promise.resolve();
  }
  
  console.log('[Schedule] 开始创建初始化Promise');
  
  // 创建初始化Promise
  initializationPromise = (async () => {
    console.log('[Schedule] 初始化执行开始');
    try {
      // 并行获取基础数据（容错处理：单个失败不阻塞整体）
      console.log('[Schedule] 开始并行加载基础数据...');
      await Promise.all([
        safeFetch(() => staffStore.fetchStaffList(), '人员列表'),
        safeFetch(() => shiftStore.fetchShiftList(), '班次列表'),
        safeFetch(() => swapStore.fetchSwapList(), '换班列表'),
        safeFetch(() => substituteStore.fetchSubstituteList(), '替班列表')
      ]);
      console.log('[Schedule] 基础数据加载完成');
      
      // 获取当前月份排班数据
      console.log('[Schedule] 开始加载排班数据...');
      await safeFetch(
        () => scheduleStore.fetchSchedule(
          scheduleStore.currentDate.year(),
          scheduleStore.currentDate.month() + 1,
          false
        ),
        '排班数据'
      );
      console.log('[Schedule] 排班数据加载完成');
      
      // 标记已初始化（无论数据是否全部加载成功，都允许页面渲染）
      console.log('[Schedule] 设置 isInitialized = true');
      scheduleStore.setInitialized(true);
      console.log('[Schedule] 初始化完成！');
    } catch (error) {
      console.error('[Schedule] 初始化过程中发生错误:', error);
      // 即使出错也标记为已初始化，避免页面一直加载中
      console.log('[Schedule] 出错后仍设置 isInitialized = true');
      scheduleStore.setInitialized(true);
      throw error;
    } finally {
      // 重置Promise，允许重试
      console.log('[Schedule] 重置 initializationPromise');
      initializationPromise = null;
    }
  })();
  
  return initializationPromise;
}

/**
 * 重置初始化状态（用于测试或重新登录场景）
 */
export function resetStoreInitialization() {
  initializationPromise = null;
  if (stores.schedule) {
    stores.schedule.setInitialized(false);
  }
}

// 单独导出（便于按需导入）
export { scheduleStore };
export { staffStore };
export { shiftStore };
export { swapStore };
export { substituteStore };

// 创建 Proxy 来确保 MobX observable 能正确响应
// 使用 getter 让每次访问都获取最新的值
const legacyStore = {};

// ===== scheduleStore 属性 =====
Object.defineProperty(legacyStore, 'scheduleList', {
  get: () => scheduleStore.scheduleList
});
Object.defineProperty(legacyStore, 'currentDate', {
  get: () => scheduleStore.currentDate
});
Object.defineProperty(legacyStore, 'selectedDate', {
  get: () => scheduleStore.selectedDate
});
Object.defineProperty(legacyStore, 'selectedCellData', {
  get: () => scheduleStore.selectedCellData
});
Object.defineProperty(legacyStore, 'formVisible', {
  get: () => scheduleStore.formVisible,
  set: (value) => { scheduleStore.formVisible = value; }
});
Object.defineProperty(legacyStore, 'record', {
  get: () => scheduleStore.record,
  set: (value) => { scheduleStore.record = value; }
});
Object.defineProperty(legacyStore, 'isFetching', {
  get: () => scheduleStore.isFetching
});
Object.defineProperty(legacyStore, 'isInitialized', {
  get: () => scheduleStore.isInitialized
});

// ===== scheduleStore 方法 =====
legacyStore.fetchSchedule = (...args) => scheduleStore.fetchSchedule(...args);
legacyStore.setCurrentDate = (...args) => scheduleStore.setCurrentDate(...args);
legacyStore.showForm = (...args) => scheduleStore.showForm(...args);
legacyStore.addSchedule = (...args) => scheduleStore.addSchedule(...args);
legacyStore.deleteSchedule = (...args) => scheduleStore.deleteSchedule(...args);
legacyStore.deleteScheduleNoRefresh = (...args) => scheduleStore.deleteScheduleNoRefresh(...args);
legacyStore.autoSchedule = (...args) => scheduleStore.autoSchedule(...args);
legacyStore.batchAdjustSchedule = (...args) => scheduleStore.batchAdjustSchedule(...args);
legacyStore.batchQuerySchedules = (...args) => scheduleStore.batchQuerySchedules(...args);
legacyStore.batchDeleteSchedules = (...args) => scheduleStore.batchDeleteSchedules(...args);
legacyStore.handleCellClick = (...args) => scheduleStore.handleCellClick(...args);
legacyStore.setInitialized = (...args) => scheduleStore.setInitialized(...args);

// ===== staffStore =====
Object.defineProperty(legacyStore, 'staffList', {
  get: () => staffStore.staffList
});
legacyStore.fetchStaffList = (...args) => staffStore.fetchStaffList(...args);

// ===== shiftStore =====
Object.defineProperty(legacyStore, 'shiftList', {
  get: () => shiftStore.shiftList
});
legacyStore.fetchShiftList = (...args) => shiftStore.fetchShiftList(...args);

// ===== swapStore =====
Object.defineProperty(legacyStore, 'swapList', {
  get: () => swapStore.swapList
});
Object.defineProperty(legacyStore, 'swapFormVisible', {
  get: () => swapStore.formVisible,
  set: (value) => { swapStore.formVisible = value; }
});
legacyStore.fetchSwapList = (...args) => swapStore.fetchSwapList(...args);
legacyStore.showSwapForm = (...args) => swapStore.showForm(...args);
legacyStore.createSwap = (...args) => swapStore.createSwap(...args);
legacyStore.approveSwap = (...args) => swapStore.approveSwap(...args);
legacyStore.rejectSwap = (...args) => swapStore.rejectSwap(...args);
legacyStore.cancelSwap = (...args) => swapStore.cancelSwap(...args);
legacyStore.deleteSwap = (...args) => swapStore.deleteSwap(...args);
legacyStore.batchCreateSwap = (...args) => swapStore.batchCreateSwap(...args);
legacyStore.isInSwap = (...args) => swapStore.isInSwap(...args);

// ===== substituteStore =====
Object.defineProperty(legacyStore, 'substituteList', {
  get: () => substituteStore.substituteList
});
Object.defineProperty(legacyStore, 'substituteFormVisible', {
  get: () => substituteStore.formVisible,
  set: (value) => { substituteStore.formVisible = value; }
});
legacyStore.fetchSubstituteList = (...args) => substituteStore.fetchSubstituteList(...args);
legacyStore.showSubstituteForm = (...args) => substituteStore.showForm(...args);
legacyStore.createSubstitute = (...args) => substituteStore.createSubstitute(...args);
legacyStore.approveSubstitute = (...args) => substituteStore.approveSubstitute(...args);
legacyStore.rejectSubstitute = (...args) => substituteStore.rejectSubstitute(...args);
legacyStore.cancelSubstitute = (...args) => substituteStore.cancelSubstitute(...args);
legacyStore.deleteSubstitute = (...args) => substituteStore.deleteSubstitute(...args);
legacyStore.batchCreateSubstitute = (...args) => substituteStore.batchCreateSubstitute(...args);
legacyStore.isInSubstitute = (...args) => substituteStore.isInSubstitute(...args);

export default legacyStore;
