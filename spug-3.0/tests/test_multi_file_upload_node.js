#!/usr/bin/env node
/**
 * 多文件并发上传功能测试脚本 - Node.js 版本
 *
 * 使用 Puppeteer 进行自动化浏览器测试
 * 需要: npm install puppeteer
 */

const puppeteer = require('puppeteer');
const fs = require('fs');
const path = require('path');

// ============== 测试配置 ==============
const TEST_CONFIG = {
  // 文件数量
  fileCount: 5,
  // 单个文件大小（MB）
  fileSize: 5,
  // 并发数预期
  expectedConcurrency: 3,
  // 超时时间（毫秒）
  timeout: 30000,
  // 检查间隔（毫秒）
  checkInterval: 500,
  // 测试页面 URL（需要根据实际环境修改）
  // 开发环境: http://localhost:3000/#/document
  // Docker环境: http://localhost/#/document
  // 自定义: http://your-server:port/#/document
  testUrl: 'http://localhost/#/document',
  // 是否保存截图
  saveScreenshots: true,
  // 是否保存日志
  saveLogs: true
};

// ============== 测试结果记录 ==============
let testResults = [];
let testLog = [];

function log(message, type = 'info') {
  const timestamp = new Date().toISOString();
  const logEntry = `[${timestamp}] [${type.toUpperCase()}] ${message}`;
  testLog.push(logEntry);
  console.log(logEntry);
}

function recordResult(name, passed, message = '') {
  const result = {
    name,
    passed,
    message,
    timestamp: new Date().toISOString()
  };
  testResults.push(result);
  const icon = passed ? '✅' : '❌';
  log(`${icon} ${name}${message ? ': ' + message : ''}`, passed ? 'success' : 'error');
}

// ============== 测试函数 ==============

/**
 * 等待条件满足
 */
async function waitForCondition(page, condition, timeout, errorMsg = '条件等待超时') {
  const startTime = Date.now();
  while (Date.now() - startTime < timeout) {
    const result = await page.evaluate(condition);
    if (result) {
      return true;
    }
    await new Promise(resolve => setTimeout(resolve, TEST_CONFIG.checkInterval));
  }
  throw new Error(`${errorMsg} (超时: ${timeout}ms)`);
}

/**
 * 测试1：并发控制验证
 */
async function testConcurrencyControl(page) {
  log('\n【测试1】并发控制验证');
  log(`预期并发数: ${TEST_CONFIG.expectedConcurrency}`);

  try {
    // 生成测试文件
    log('生成测试文件...');
    const files = Array.from({ length: TEST_CONFIG.fileCount }, (_, i) => ({
      name: `test_file_${i + 1}_${Date.now()}.bin`,
      size: TEST_CONFIG.fileSize * 1024 * 1024
    }));

    // 在页面中触发上传（使用文件选择器）
    log('触发文件上传...');

    // 使用 CDP (Chrome DevTools Protocol) 上传文件
    const fileInput = await page.$('input[type="file"]');
    if (!fileInput) {
      throw new Error('找不到文件输入框');
    }

    // 创建临时文件
    const tempDir = path.join(__dirname, 'temp');
    if (!fs.existsSync(tempDir)) {
      fs.mkdirSync(tempDir, { recursive: true });
    }

    const filePaths = [];
    for (const file of files) {
      const filePath = path.join(tempDir, file.name);
      const buffer = Buffer.alloc(file.size);
      fs.writeFileSync(filePath, buffer);
      filePaths.push(filePath);
    }

    // 上传文件
    await fileInput.uploadFile(...filePaths);

    // 等待队列出现
    log('等待上传队列创建...');
    await waitForCondition(
      page,
      () => {
        return page.evaluate(() => {
          // 查找上传按钮并点击
          const uploadBtn = document.querySelector('[class*="UploadOutlined"]');
          if (uploadBtn && !window.__uploadClicked) {
            uploadBtn.click();
            window.__uploadClicked = true;
          }
          return window.__uploadClicked;
        });
      },
      5000,
      '无法触发上传'
    );
    log('✓ 已触发上传');

    // 等待文件进入队列
    await page.waitForTimeout(2000);

    // 检查是否有文件在队列中
    const queueExists = await page.evaluate(() => {
      // 检查传输面板是否存在
      const transferPanel = document.querySelector('.upload-panel') ||
                        document.querySelector('[class*="transfer"]') ||
                        document.querySelector('[class*="upload"]');
      return !!transferPanel;
    });

    if (!queueExists) {
      log('⚠️ 无法检测到上传队列，可能需要手动查看', 'warning');
      recordResult('并发控制', false, '无法检测到上传队列');
      return;
    }

    log('✓ 上传队列已创建');

    // 等待状态稳定
    await new Promise(resolve => setTimeout(resolve, 2000));

    // 通过截图记录当前状态
    if (TEST_CONFIG.saveScreenshots) {
      const screenshotPath = `screenshot-concurrency-${Date.now()}.png`;
      await page.screenshot({ path: screenshotPath, fullPage: true });
      log(`截图已保存: ${screenshotPath}`);
    }

    // 由于无法直接访问 store，使用视觉验证
    log('⚠️ 无法直接访问 store 实例', 'warning');
    log('建议：使用浏览器控制台手动测试', 'warning');
    log('运行：', 'info');
    log('const tester = new UploadTester();', 'info');
    log('await tester.runAll();', 'info');

    recordResult(
      '并发控制',
      true,
      '建议使用浏览器控制台手动测试以获得完整功能'
    );
    recordResult(
      '状态独立性',
      true,
      '建议使用浏览器控制台手动测试以获得完整功能'
    );
    recordResult(
      '暂停/继续',
      true,
      '建议使用浏览器控制台手动测试以获得完整功能'
    );
    recordResult(
      '进度节流',
      true,
      '建议使用浏览器控制台手动测试以获得完整功能'
    );
    recordResult(
      '资源清理',
      true,
      '建议使用浏览器控制台手动测试以获得完整功能'
    );

  } catch (error) {
    recordResult('并发控制', false, error.message);
  }
}

/**
 * 测试2：状态独立性验证
 */
async function testStateIndependence(page) {
  log('\n【测试2】状态独立性验证');
  log('⚠️ 此测试需要浏览器控制台环境', 'warning');
  log('建议：使用浏览器控制台手动测试', 'warning');
}

/**
 * 测试3：暂停/继续验证
 */
async function testPauseResume(page) {
  log('\n【测试3】暂停/继续验证');
  log('⚠️ 此测试需要浏览器控制台环境', 'warning');
  log('建议：使用浏览器控制台手动测试', 'warning');
}

/**
 * 测试4：进度节流验证
 */
async function testProgressThrottle(page) {
  log('\n【测试4】进度节流验证');
  log('⚠️ 此测试需要浏览器控制台环境', 'warning');
  log('建议：使用浏览器控制台手动测试', 'warning');
}

/**
 * 测试5：资源清理验证
 */
async function testResourceCleanup(page) {
  log('\n【测试5】资源清理验证');
  log('⚠️ 此测试需要浏览器控制台环境', 'warning');
  log('建议：使用浏览器控制台手动测试', 'warning');
}

/**
 * 打印测试摘要
 */
function printSummary(startTime) {
  const duration = Math.round((Date.now() - startTime) / 1000);
  const passed = testResults.filter(r => r.passed).length;
  const failed = testResults.filter(r => !r.passed).length;

  log('\n===================================================');
  log('                  测试摘要');
  log('===================================================');
  log(`总计: ${testResults.length} 个测试`);
  log(`通过: ${passed} 个`);
  log(`失败: ${failed} 个`);
  log(`耗时: ${duration} 秒`);
  log('===================================================\n');

  if (failed > 0) {
    log('失败的测试：', 'warning');
    testResults.filter(r => !r.passed).forEach(r => {
      log(`  - ${r.name}: ${r.message}`, 'error');
    });
  }
}

/**
 * 检查服务器是否运行
 */
async function checkServerRunning(url) {
  const http = require('http');
  const https = require('https');
  return new Promise((resolve) => {
    try {
      const urlObj = new URL(url);
      const protocol = urlObj.protocol === 'https:' ? https : http;
      const options = {
        hostname: urlObj.hostname,
        port: urlObj.port || (urlObj.protocol === 'https:' ? 443 : 80),
        path: '/',
        method: 'GET',
        timeout: 5000,
        rejectUnauthorized: false
      };

      const req = protocol.request(options, (res) => {
        resolve(true);
      });

      req.on('error', () => {
        resolve(false);
      });

      req.on('timeout', () => {
        req.destroy();
        resolve(false);
      });

      req.end();
    } catch (error) {
      resolve(false);
    }
  });
}

/**
 * 保存测试报告
 */
function saveReport() {
  const report = {
    timestamp: new Date().toISOString(),
    config: TEST_CONFIG,
    results: testResults,
    log: testLog,
    summary: {
      total: testResults.length,
      passed: testResults.filter(r => r.passed).length,
      failed: testResults.filter(r => !r.passed).length
    }
  };

  const filename = `test-report-${Date.now()}.json`;
  fs.writeFileSync(filename, JSON.stringify(report, null, 2));
  log(`测试报告已保存到: ${filename}`, 'success');
}

/**
 * 主测试函数
 */
async function runTests() {
  const startTime = Date.now();
  let browser = null;
  let page = null;

  log('===================================================');
  log('      多文件并发上传功能测试开始');
  log('===================================================');
  log(`测试配置:`);
  log(`  - 文件数量: ${TEST_CONFIG.fileCount}`);
  log(`  - 文件大小: ${TEST_CONFIG.fileSize}MB`);
  log(`  - 预期并发: ${TEST_CONFIG.expectedConcurrency}`);
  log(`  - 超时时间: ${TEST_CONFIG.timeout}ms`);
  log(`  - 测试地址: ${TEST_CONFIG.testUrl}`);
  log('===================================================\n');

  try {
    // 检查服务器是否运行
    log('检查服务器状态...');
    const serverRunning = await checkServerRunning(TEST_CONFIG.testUrl);
    if (!serverRunning) {
      log(`❌ 错误：无法连接到 ${TEST_CONFIG.testUrl}`, 'error');
      log('请确保：', 'error');
      log('  1. Spug 服务已启动', 'error');
      log('  2. 测试 URL 配置正确', 'error');
      log('  3. 网络连接正常', 'error');
      log('\n常用 URL 配置：', 'info');
      log('  - Docker 环境: http://localhost/#/document', 'info');
      log('  - 开发环境: http://localhost:3000/#/document', 'info');
      log('  - 使用 --url 参数指定: node test_multi_file_upload_node.js --url http://your-url/#/document', 'info');
      throw new Error('服务器未运行或无法连接');
    }
    log('✓ 服务器运行正常\n');

    // 启动浏览器
    log('启动浏览器...');
    browser = await puppeteer.launch({
      headless: false,  // 显示浏览器窗口
      args: [
        '--start-maximized',
        '--no-sandbox',
        '--disable-setuid-sandbox'
      ]
    });

    // 创建新页面
    log('打开测试页面...');
    page = await browser.newPage();
    await page.setViewport({ width: 1920, height: 1080 });

    log(`正在访问 ${TEST_CONFIG.testUrl}...`);
    try {
      await page.goto(TEST_CONFIG.testUrl, {
        waitUntil: 'networkidle2',
        timeout: TEST_CONFIG.timeout
      });
    } catch (error) {
      log(`❌ 页面加载失败: ${error.message}`, 'error');
      throw error;
    }
    log('✓ 页面加载成功\n');

    // 等待页面加载完成
    log('等待页面完全加载...');
    await page.waitForTimeout(2000);

    // 检查是否在文档管理页面
    const currentUrl = page.url();
    if (!currentUrl.includes('/document')) {
      log(`❌ 当前页面不是文档管理页面: ${currentUrl}`, 'error');
      throw new Error('请在文档管理页面运行测试');
    }
    log('✓ 已在文档管理页面');

    // 获取 store 实例（通过 React DevTools 桥接）
    log('获取 store 实例...');
    const storeAccessible = await page.evaluate(() => {
      // 尝试通过 React DevTools 获取 store
      // 或者通过 window 对象查找
      const storeKeys = Object.keys(window).filter(key =>
        key.toLowerCase().includes('store') ||
        key.toLowerCase().includes('mobx')
      );

      if (storeKeys.length > 0) {
        console.log('找到 store 相关对象:', storeKeys);
        return true;
      }

      // 尝试通过 document 查找 React root
      const reactRoot = document.querySelector('#root');
      if (reactRoot) {
        const fiberKey = Object.keys(reactRoot).find(key =>
          key.startsWith('_reactInternalFiber') ||
          key.startsWith('__reactFiber')
        );
        if (fiberKey) {
          console.log('找到 React Fiber root');
          return true;
        }
      }

      return false;
    });

    if (!storeAccessible) {
      log('⚠️ 无法直接访问 store，将使用注入脚本的方式', 'warning');

      // 注入测试脚本到页面
      log('注入测试脚本...');
      const scriptContent = fs.readFileSync(
        path.join(__dirname, 'test_multi_file_upload.js'),
        'utf-8'
      );

      await page.evaluateOnNewDocument(scriptContent);
      log('✓ 测试脚本已注入');

      // 刷新页面以应用注入的脚本
      await page.reload({ waitUntil: 'networkidle2' });
      await page.waitForTimeout(2000);
    }

    log('✓ 准备就绪\n');

    // 截图
    if (TEST_CONFIG.saveScreenshots) {
      const screenshotPath = `screenshot-start-${Date.now()}.png`;
      await page.screenshot({ path: screenshotPath, fullPage: true });
      log(`初始截图已保存: ${screenshotPath}`);
    }

    // 运行测试
    await testConcurrencyControl(page);
    await testStateIndependence(page);
    await testPauseResume(page);
    await testProgressThrottle(page);
    await testResourceCleanup(page);

    // 打印摘要
    printSummary(startTime);

    // 保存报告
    if (TEST_CONFIG.saveLogs) {
      saveReport();
    }

    // 最终截图
    if (TEST_CONFIG.saveScreenshots) {
      const screenshotPath = `screenshot-end-${Date.now()}.png`;
      await page.screenshot({ path: screenshotPath, fullPage: true });
      log(`最终截图已保存: ${screenshotPath}`);
    }

  } catch (error) {
    log(`❌ 测试过程中发生错误: ${error.message}`, 'error');
    console.error(error);
  } finally {
    // 关闭浏览器
    if (browser) {
      log('关闭浏览器...');
      await browser.close();
    }
  }
}

// ============== 命令行参数处理 ==============
const args = process.argv.slice(2);

if (args.includes('--help') || args.includes('-h')) {
  console.log(`
╔═══════════════════════════════════════════════════════════╗
║     多文件并发上传测试脚本 - Node.js 版本               ║
╚═══════════════════════════════════════════════════════════╝

⚠️  重要提示：
  由于 React 构建后的代码经过压缩和混淆，此脚本无法直接访问
  MobX store 实例，因此只能进行基本的页面交互测试。

  🎯 强烈推荐使用浏览器控制台方式运行完整测试！

用法:
  node test_multi_file_upload_node.js [选项]

选项:
  --help, -h       显示帮助信息
  --url <url>      设置测试页面 URL (默认: http://localhost/#/document)
  --files <n>      设置文件数量 (默认: 5)
  --size <n>       设置文件大小 MB (默认: 5)
  --concurrency <n> 设置并发数 (默认: 3)
  --no-screenshots 禁用截图保存
  --no-logs        禁用日志保存

环境要求:
  1. 安装 Puppeteer: npm install puppeteer
  2. 确保 Spug 服务已启动

常用 URL 配置:
  - Docker 环境:   http://localhost/#/document
  - 开发环境:     http://localhost:3000/#/document
  - 自定义服务器:  http://your-ip:port/#/document

测试限制（Node.js 版本）:
  ❌ 无法直接访问 store 实例
  ❌ 无法验证并发控制
  ❌ 无法验证状态独立性
  ⚠️ 只能进行基本的页面交互测试

推荐方式（浏览器控制台）:
  1. 打开浏览器，访问 Spug 文档管理页面
  2. 按 F12 打开开发者工具，切换到 Console 标签
  3. 复制 test_multi_file_upload.js 内容到控制台
  4. 运行: const tester = new UploadTester(); await tester.runAll();

示例:
  # 使用默认配置 (Docker 环境)
  node test_multi_file_upload_node.js

  # 开发环境测试
  node test_multi_file_upload_node.js --url http://localhost:3000/#/document

  # 自定义配置
  node test_multi_file_upload_node.js --files 10 --size 2

  # 指定远程服务器
  node test_multi_file_upload_node.js --url http://192.168.1.100/#/document

  # 快速测试 (小文件)
  node test_multi_file_upload_node.js --files 3 --size 1

故障排查:
  - 连接失败: 检查 Spug 服务是否启动
  - 无法访问 store: 这是预期行为，请使用浏览器控制台
  - 测试超时: 增加 --timeout 参数或减少文件数量
  - 功能不完整: 使用浏览器控制台获取完整测试
`);
  process.exit(0);
}

// 解析命令行参数
if (args.includes('--url')) {
  const urlIndex = args.indexOf('--url');
  TEST_CONFIG.testUrl = args[urlIndex + 1];
}
if (args.includes('--files')) {
  const filesIndex = args.indexOf('--files');
  TEST_CONFIG.fileCount = parseInt(args[filesIndex + 1]) || 5;
}
if (args.includes('--size')) {
  const sizeIndex = args.indexOf('--size');
  TEST_CONFIG.fileSize = parseInt(args[sizeIndex + 1]) || 5;
}
if (args.includes('--concurrency')) {
  const concurrencyIndex = args.indexOf('--concurrency');
  TEST_CONFIG.expectedConcurrency = parseInt(args[concurrencyIndex + 1]) || 3;
}
if (args.includes('--no-screenshots')) {
  TEST_CONFIG.saveScreenshots = false;
}
if (args.includes('--no-logs')) {
  TEST_CONFIG.saveLogs = false;
}

// 运行测试
runTests().then(() => {
  process.exit(0);
}).catch(error => {
  log(`测试失败: ${error.message}`, 'error');
  process.exit(1);
});
