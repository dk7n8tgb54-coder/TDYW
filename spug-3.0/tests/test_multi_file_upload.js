#!/usr/bin/env node
/**
 * 多文件并发上传功能测试脚本
 *
 * 用于自动化测试多文件并发上传的各项功能
 * 浏览器环境使用：复制到浏览器控制台执行
 * Node.js 环境使用：需要配置 puppeteer 等工具
 */

// ============== 测试配置 ==============
const TEST_CONFIG = {
  // 测试文件数量
  fileCount: 5,
  // 单个文件大小（MB）
  fileSize: 5,
  // 并发数预期
  expectedConcurrency: 3,
  // 超时时间（毫秒）
  timeout: 30000,
  // 测试等待间隔（毫秒）
  checkInterval: 500
};

// ============== 测试工具函数 ==============

/**
 * 生成测试文件
 * @param {number} sizeMB 文件大小（MB）
 * @param {string} name 文件名
 * @returns {File} 测试文件
 */
function generateTestFile(sizeMB, name) {
  const size = sizeMB * 1024 * 1024;
  const buffer = new Uint8Array(size);
  // 填充随机数据
  for (let i = 0; i < size; i++) {
    buffer[i] = Math.floor(Math.random() * 256);
  }
  const blob = new Blob([buffer], { type: 'application/octet-stream' });
  return new File([blob], name);
}

/**
 * 生成多个测试文件
 * @param {number} count 文件数量
 * @param {number} sizeMB 单个文件大小
 * @returns {Array<File>} 测试文件数组
 */
function generateTestFiles(count, sizeMB) {
  const files = [];
  for (let i = 0; i < count; i++) {
    const name = `test_file_${i + 1}_${Date.now()}.bin`;
    files.push(generateTestFile(sizeMB, name));
  }
  return files;
}

/**
 * 等待指定时间
 * @param {number} ms 毫秒数
 */
function sleep(ms) {
  return new Promise(resolve => setTimeout(resolve, ms));
}

/**
 * 等待条件满足
 * @param {Function} condition 条件函数
 * @param {number} timeout 超时时间
 * @param {string} errorMsg 超时错误信息
 */
async function waitForCondition(condition, timeout, errorMsg = '条件等待超时') {
  const startTime = Date.now();
  while (Date.now() - startTime < timeout) {
    if (condition()) {
      return true;
    }
    await sleep(TEST_CONFIG.checkInterval);
  }
  throw new Error(`${errorMsg} (超时: ${timeout}ms)`);
}

// ============== 测试用例 ==============

class UploadTester {
  constructor() {
    this.results = [];
    this.startTime = null;
  }

  /**
   * 记录测试结果
   * @param {string} name 测试名称
   * @param {boolean} passed 是否通过
   * @param {string} message 结果消息
   */
  recordResult(name, passed, message = '') {
    this.results.push({
      name,
      passed,
      message,
      timestamp: Date.now()
    });
    const icon = passed ? '✅' : '❌';
    console.log(`${icon} ${name}${message ? ': ' + message : ''}`);
  }

  /**
   * 打印测试摘要
   */
  printSummary() {
    const passed = this.results.filter(r => r.passed).length;
    const failed = this.results.filter(r => !r.passed).length;
    const duration = this.startTime ? Math.round((Date.now() - this.startTime) / 1000) : 0;

    console.log('\n==================== 测试摘要 ====================');
    console.log(`总计: ${this.results.length} 个测试`);
    console.log(`通过: ${passed} 个`);
    console.log(`失败: ${failed} 个`);
    console.log(`耗时: ${duration} 秒`);
    console.log('===================================================\n');

    if (failed > 0) {
      console.log('失败的测试：');
      this.results.filter(r => !r.passed).forEach(r => {
        console.log(`  - ${r.name}: ${r.message}`);
      });
    }
  }

  /**
   * 获取上传队列
   */
  getUploadQueue() {
    // 假设全局 store 对象
    if (window.documentStore) {
      return window.documentStore.uploadQueue;
    }
    throw new Error('找不到 documentStore，请确保在正确的页面执行');
  }

  /**
   * 获取活跃上传数
   */
  getActiveUploads() {
    if (window.documentStore) {
      return window.documentStore.activeUploads;
    }
    throw new Error('找不到 documentStore');
  }

  /**
   * 测试1：并发控制验证
   */
  async testConcurrencyControl() {
    console.log('\n【测试1】并发控制验证');
    console.log(`预期并发数: ${TEST_CONFIG.expectedConcurrency}`);

    const files = generateTestFiles(TEST_CONFIG.fileCount, TEST_CONFIG.fileSize);
    console.log(`生成 ${files.length} 个测试文件，每个 ${TEST_CONFIG.fileSize}MB`);

    // 触发上传（需要根据实际 UI 交互调整）
    // 这里假设有一个 uploadFiles 方法
    try {
      if (window.documentStore && window.documentStore.uploadFiles) {
        window.documentStore.uploadFiles(files);
      } else {
        throw new Error('找不到 uploadFiles 方法');
      }

      // 等待队列出现
      await waitForCondition(
        () => this.getUploadQueue().length > 0,
        5000,
        '上传队列未出现'
      );
      console.log('✓ 上传队列已创建');

      // 等待所有任务进入队列
      await waitForCondition(
        () => this.getUploadQueue().length === files.length,
        5000,
        '文件未全部进入队列'
      );
      console.log(`✓ 所有 ${files.length} 个文件已进入队列`);

      // 检查并发数（等待 1 秒让状态稳定）
      await sleep(1000);
      const activeUploads = this.getActiveUploads();
      const uploadingCount = this.getUploadQueue().filter(item => item.status === 'uploading').length;

      console.log(`当前活跃上传数: ${activeUploads}`);
      console.log(`正在上传的文件数: ${uploadingCount}`);

      // 验证并发数不超过预期
      if (activeUploads <= TEST_CONFIG.expectedConcurrency) {
        this.recordResult(
          '并发控制',
          true,
          `活跃上传数 ${activeUploads} <= 预期 ${TEST_CONFIG.expectedConcurrency}`
        );
      } else {
        this.recordResult(
          '并发控制',
          false,
          `活跃上传数 ${activeUploads} > 预期 ${TEST_CONFIG.expectedConcurrency}`
        );
      }

      // 验证等待队列
      const waitingCount = this.getUploadQueue().filter(item => item.status === 'waiting').length;
      const expectedWaiting = files.length - TEST_CONFIG.expectedConcurrency;

      console.log(`等待中的文件数: ${waitingCount}`);
      if (waitingCount >= expectedWaiting) {
        this.recordResult(
          '等待队列',
          true,
          `${waitingCount} 个文件在等待队列`
        );
      } else {
        this.recordResult(
          '等待队列',
          false,
          `等待队列中只有 ${waitingCount} 个文件，预期至少 ${expectedWaiting} 个`
        );
      }

    } catch (error) {
      this.recordResult('并发控制', false, error.message);
    }
  }

  /**
   * 测试2：状态独立性验证
   */
  async testStateIndependence() {
    console.log('\n【测试2】状态独立性验证');

    try {
      const queue = this.getUploadQueue();

      // 检查每个文件的状态是否独立
      const statuses = queue.map(item => item.status);
      const uniqueStatuses = [...new Set(statuses)];

      console.log('当前状态分布:', statuses);

      // 验证有不同的状态存在
      if (uniqueStatuses.length > 1) {
        this.recordResult(
          '状态多样性',
          true,
          `存在 ${uniqueStatuses.join(', ')} 等状态`
        );
      } else {
        this.recordResult(
          '状态多样性',
          false,
          `所有文件状态相同: ${uniqueStatuses[0]}`
        );
      }

      // 验证每个文件有独立的进度
      const percents = queue.map(item => item.percent);
      const uniquePercents = [...new Set(percents)];

      console.log('当前进度分布:', percents);

      if (uniquePercents.length > 1) {
        this.recordResult(
          '进度独立性',
          true,
          `${uniquePercents.length} 个不同的进度值`
        );
      } else if (queue.length > 1) {
        this.recordResult(
          '进度独立性',
          false,
          '所有文件进度相同'
        );
      }

    } catch (error) {
      this.recordResult('状态独立性', false, error.message);
    }
  }

  /**
   * 测试3：资源清理验证
   */
  async testResourceCleanup() {
    console.log('\n【测试3】资源清理验证');

    try {
      const store = window.documentStore;

      // 执行取消操作
      if (store.cancelAll) {
        store.cancelAll();
        await sleep(500);
      } else {
        throw new Error('找不到 cancelAll 方法');
      }

      // 验证活跃上传数归零
      const activeUploads = this.getActiveUploads();
      if (activeUploads === 0) {
        this.recordResult(
          '活跃上传计数重置',
          true,
          `活跃上传数 = ${activeUploads}`
        );
      } else {
        this.recordResult(
          '活跃上传计数重置',
          false,
          `活跃上传数 = ${activeUploads}，期望 0`
        );
      }

      // 验证队列状态更新
      const queue = this.getUploadQueue();
      const errorCount = queue.filter(item => item.status === 'error').length;

      if (errorCount === queue.length) {
        this.recordResult(
          '队列状态更新',
          true,
          `所有 ${errorCount} 个文件状态已更新为 error`
        );
      } else {
        this.recordResult(
          '队列状态更新',
          false,
          `${errorCount}/${queue.length} 个文件状态为 error`
        );
      }

      // 验证 abortToken 清理
      const hasAbortToken = queue.some(item => item.abortToken !== null);
      if (!hasAbortToken) {
        this.recordResult(
          'abortToken 清理',
          true,
          '所有文件的 abortToken 已清理'
        );
      } else {
        this.recordResult(
          'abortToken 清理',
          false,
          '部分文件的 abortToken 未清理'
        );
      }

    } catch (error) {
      this.recordResult('资源清理', false, error.message);
    }
  }

  /**
   * 测试4：暂停/继续验证
   */
  async testPauseResume() {
    console.log('\n【测试4】暂停/继续验证');

    try {
      const store = window.documentStore;
      const files = generateTestFiles(2, TEST_CONFIG.fileSize);

      // 重新开始上传
      store.uploadFiles(files);
      await sleep(2000);

      // 暂停上传
      if (store.pauseAll) {
        store.pauseAll();
        await sleep(1000);
      } else {
        throw new Error('找不到 pauseAll 方法');
      }

      // 验证暂停状态
      const queue = this.getUploadQueue();
      const pausedCount = queue.filter(item => item.status === 'paused').length;

      console.log(`已暂停的文件数: ${pausedCount}/${queue.length}`);

      if (pausedCount > 0) {
        this.recordResult(
          '暂停功能',
          true,
          `${pausedCount} 个文件已暂停`
        );
      } else {
        this.recordResult(
          '暂停功能',
          false,
          '没有文件进入暂停状态'
        );
      }

      // 继续上传
      if (store.resumeAll) {
        store.resumeAll();
        await sleep(1000);
      } else {
        console.log('⚠️ 没有实现 resumeAll 方法，跳过继续测试');
        return;
      }

      // 验证继续状态
      const uploadingCount = queue.filter(item => item.status === 'uploading').length;

      console.log(`正在上传的文件数: ${uploadingCount}/${queue.length}`);

      if (uploadingCount > 0) {
        this.recordResult(
          '继续功能',
          true,
          `${uploadingCount} 个文件继续上传`
        );
      } else {
        this.recordResult(
          '继续功能',
          false,
          '没有文件恢复上传'
        );
      }

    } catch (error) {
      this.recordResult('暂停/继续', false, error.message);
    }
  }

  /**
   * 测试5：进度节流验证
   */
  async testProgressThrottle() {
    console.log('\n【测试5】进度节流验证');

    try {
      const store = window.documentStore;
      const files = generateTestFiles(1, TEST_CONFIG.fileSize);

      // 开始单个文件上传
      store.uploadFiles(files);
      await sleep(500);

      // 监控进度更新频率
      const queue = this.getUploadQueue();
      const item = queue[0];
      if (!item) {
        throw new Error('上传队列为空');
      }

      const updateCount = { value: 0 };
      const originalPercent = item.percent;

      // 观察 2 秒内的进度更新次数
      const startTime = Date.now();
      const checkInterval = setInterval(() => {
        if (item.percent !== originalPercent) {
          updateCount.value++;
        }
      }, 100);

      await sleep(2000);
      clearInterval(checkInterval);

      const duration = (Date.now() - startTime) / 1000;
      const updatesPerSecond = Math.round(updateCount.value / duration);

      console.log(`2 秒内更新次数: ${updateCount.value}`);
      console.log(`每秒更新次数: ${updatesPerSecond}`);

      // 预期每秒不超过 5 次更新（200ms 节流）
      if (updatesPerSecond <= 5) {
        this.recordResult(
          '进度节流',
          true,
          `每秒更新 ${updatesPerSecond} 次（预期 ≤ 5 次）`
        );
      } else {
        this.recordResult(
          '进度节流',
          false,
          `每秒更新 ${updatesPerSecond} 次（预期 ≤ 5 次），节流可能失效`
        );
      }

      // 清理
      store.cancelAll();

    } catch (error) {
      this.recordResult('进度节流', false, error.message);
    }
  }

  /**
   * 运行所有测试
   */
  async runAll() {
    this.startTime = Date.now();
    console.log('===================================================');
    console.log('      多文件并发上传功能测试开始');
    console.log('===================================================');
    console.log(`测试配置:`);
    console.log(`  - 文件数量: ${TEST_CONFIG.fileCount}`);
    console.log(`  - 文件大小: ${TEST_CONFIG.fileSize}MB`);
    console.log(`  - 预期并发: ${TEST_CONFIG.expectedConcurrency}`);
    console.log('===================================================');

    try {
      // 运行测试
      await this.testConcurrencyControl();
      await this.testStateIndependence();
      await this.testPauseResume();
      await this.testProgressThrottle();
      await this.testResourceCleanup();

    } catch (error) {
      console.error('测试过程中发生错误:', error);
    }

    // 打印摘要
    this.printSummary();

    return this.results;
  }
}

// ============== 使用说明 ==============

/**
 * 使用说明
 */
function printUsage() {
  console.log(`
╔═══════════════════════════════════════════════════════════╗
║         多文件并发上传功能测试脚本使用说明                ║
╚═══════════════════════════════════════════════════════════╝

【浏览器环境使用】
1. 打开 Spug 文档管理页面
2. 按 F12 打开开发者工具，切换到 Console 标签
3. 复制本脚本到控制台执行
4. 查看测试结果

【测试项目】
1. 并发控制验证 - 验证最多 3 个文件同时上传
2. 状态独立性验证 - 验证每个文件的进度和状态独立
3. 暂停/继续验证 - 验证暂停和继续功能
4. 进度节流验证 - 验证进度更新频率（预期 ≤ 5 次/秒）
5. 资源清理验证 - 验证取消时清理 Worker 和网络请求

【自定义配置】
修改 TEST_CONFIG 对象来自定义测试参数：
  - fileCount: 测试文件数量（默认 5）
  - fileSize: 单个文件大小 MB（默认 5）
  - expectedConcurrency: 预期并发数（默认 3）
  - timeout: 超时时间毫秒（默认 30000）

【注意事项】
1. 确保在文档管理页面执行，否则会找不到 documentStore
2. 测试会生成临时文件并上传，请确保有测试目录
3. 测试完成后会自动取消上传，清理资源
4. 建议在测试环境运行，避免影响生产数据

【示例】
// 运行默认测试
const tester = new UploadTester();
await tester.runAll();

// 自定义测试配置
TEST_CONFIG.fileCount = 10;
TEST_CONFIG.fileSize = 2;
const tester = new UploadTester();
await tester.runAll();

╚═══════════════════════════════════════════════════════════╝
`);
}

// ============== 导出 ==============

// 浏览器环境：自动创建全局实例
if (typeof window !== 'undefined') {
  window.UploadTester = UploadTester;
  window.TEST_CONFIG = TEST_CONFIG;
  printUsage();
}

// Node.js 环境：导出模块
if (typeof module !== 'undefined' && module.exports) {
  module.exports = {
    UploadTester,
    TEST_CONFIG,
    generateTestFile,
    generateTestFiles,
    sleep,
    waitForCondition
  };
}
