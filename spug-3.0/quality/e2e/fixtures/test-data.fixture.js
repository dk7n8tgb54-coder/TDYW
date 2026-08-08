/**
 * Test data fixture - generates unique, identifiable test data.
 * All test data is prefixed with E2E_ for easy identification and cleanup.
 */
const { test: base } = require('@playwright/test');

/**
 * Generate a unique run ID for this test execution.
 * Format: E2E_YYYYMMDDHHmmss
 */
function generateRunId() {
  const now = new Date();
  const pad = (n) => String(n).padStart(2, '0');
  return `E2E_${now.getFullYear()}${pad(now.getMonth() + 1)}${pad(now.getDate())}${pad(now.getHours())}${pad(now.getMinutes())}${pad(now.getSeconds())}`;
}

const RUN_ID = generateRunId();

/**
 * Generate unique test data with a consistent prefix.
 */
function makeTestData(domain, extra = {}) {
  const timestamp = Date.now();
  const random = Math.floor(Math.random() * 10000);
  return {
    runId: RUN_ID,
    prefix: `E2E_${domain}`,
    uniqueName: `E2E_${domain}_${timestamp}_${random}`,
    ...extra,
  };
}

/**
 * Common test data patterns.
 */
const TEST_DATA = {
  // Department duty log
  deptDutyLog: {
    title: () => `E2E_部门值班日志_${Date.now()}`,
    content: 'E2E TEST DATA - Automated test content',
    department: 'E2E测试部门',
  },

  // Duty log
  duty: {
    title: () => `E2E_值班日志_${Date.now()}`,
    content: 'E2E TEST DATA - Automated test content',
  },

  // Run log (cross-day items)
  runlog: {
    title: () => `E2E_跨日事项_${Date.now()}`,
    content: 'E2E TEST DATA - Automated test content',
  },

  // Reminder
  reminder: {
    title: () => `E2E_提醒事项_${Date.now()}`,
    content: 'E2E TEST DATA - Automated test content',
  },

  // Announcement
  announcement: {
    title: () => `E2E_测试公告_${Date.now()}`,
    content: 'E2E TEST DATA - This is an automated test announcement',
  },

  // Radio license
  radioLicense: {
    licenseNo: () => `E2E-LIC-${Date.now()}`,
    unit: 'E2E测试单位',
  },

  // Station frequency approval
  frequencyApproval: {
    approvalNo: () => `E2E-APP-${Date.now()}`,
    unit: 'E2E测试单位',
  },

  // Contract agreement
  contract: {
    title: () => `E2E_测试合同_${Date.now()}`,
    partyA: 'E2E测试甲方',
    partyB: 'E2E测试乙方',
  },

  // Document
  document: {
    folderName: () => `E2E_测试文件夹_${Date.now()}`,
    fileName: () => `E2E_测试文件_${Date.now()}.txt`,
  },

  // Regulation
  regulation: {
    title: () => `E2E_测试规章_${Date.now()}`,
    content: 'E2E TEST DATA - Regulation content',
  },

  // Device resume
  device: {
    name: () => `E2E_测试设备_${Date.now()}`,
    model: 'E2E-TEST-MODEL',
  },

  // Fault record
  fault: {
    title: () => `E2E_测试故障_${Date.now()}`,
    description: 'E2E TEST DATA - Fault description',
  },

  // Upgrade record
  upgrade: {
    title: () => `E2E_测试升级_${Date.now()}`,
    content: 'E2E TEST DATA - Upgrade content',
  },

  // Interference
  interference: {
    title: () => `E2E_测试干扰_${Date.now()}`,
    description: 'E2E TEST DATA - Interference description',
  },
};

const test = base.extend({
  runId: async (_, use) => {
    await use(RUN_ID);
  },
});

module.exports = {
  test,
  RUN_ID,
  makeTestData,
  TEST_DATA,
};
