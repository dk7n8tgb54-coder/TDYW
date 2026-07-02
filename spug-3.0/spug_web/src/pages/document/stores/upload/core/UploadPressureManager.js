/**
 * UploadPressureManager - 上传压力管理器
 *
 * 职责：根据后端 /api/document/upload_pressure/ 返回的服务器压力等级，
 * 动态调整前端上传并发，避免多账号同时上传大文件时压垮后端。
 *
 * 降级策略（normal -> busy/critical）：
 *   - 立即生效：新任务调度按新并发限制执行
 *   - 已在上传中的分片不强制中断（只是不再启动新的 waiting 任务）
 *   - normalStreak 归零
 *
 * 升级策略（critical/busy -> normal）：
 *   - 保守恢复：连续 PRESSURE_RECOVERY_THRESHOLD 次都为 normal 才恢复高并发
 *   - 避免并发频繁抖动
 *
 * 拉取时机（由调用方控制）：
 *   1. 资料库页面初始化（DocumentIndex useEffect）-> init()
 *   2. 开始上传前 -> refreshNow()
 *   3. 上传过程中轮询 -> startPolling() / stopPolling()
 *
 * 注意：分片上传当前为串行实现（chunkUpload.js 的 for+await 循环），
 *   maxConcurrentChunks 字段会随压力更新并回传后端契约，但当前实际分片并发=1。
 *   真正的分片并发降级需后续把串行循环改为并发池，本次不做（避免破坏断点续传）。
 */
import {
  PRESSURE_LEVELS,
  PRESSURE_LEVEL_CONFIG,
  PRESSURE_RECOVERY_THRESHOLD,
  PRESSURE_POLL_INTERVAL,
  API_ENDPOINTS,
} from './upload-core-constants';

// 等级严重度排序（用于判断是降级还是升级）
const LEVEL_SEVERITY = {
  [PRESSURE_LEVELS.NORMAL]: 0,
  [PRESSURE_LEVELS.BUSY]: 1,
  [PRESSURE_LEVELS.CRITICAL]: 2,
};

export class UploadPressureManager {
  constructor(coreStore) {
    this.core = coreStore;
    // 轮询定时器
    this._pollTimer = null;
    // 当前已应用的等级（初始化为 normal，尚未与后端确认）
    this._currentLevel = PRESSURE_LEVELS.NORMAL;
    // 连续 normal 计数（升级保守用）
    this._normalStreak = 0;
    // 是否已完成首次拉取
    this._initialized = false;
    // 是否正在请求中（防重入）
    this._fetching = false;
  }

  // ============================================================
  // 生命周期
  // ============================================================

  /**
   * 初始化：立即拉取一次压力状态
   * 由 DocumentIndex 挂载时调用
   */
  async init() {
    if (this._initialized) return;
    this._initialized = true;
    await this.refreshNow();
  }

  /**
   * 启动轮询（资料库页面活跃 + 有上传任务时）
   */
  startPolling() {
    if (this._pollTimer) return;
    this._pollTimer = setInterval(() => {
      // 静默刷新，不弹错误
      this.refreshNow().catch((e) => {
        console.debug('[UploadPressure] 轮询失败:', e?.message);
      });
    }, PRESSURE_POLL_INTERVAL);
  }

  /**
   * 停止轮询（页面卸载或长时间无任务时）
   */
  stopPolling() {
    if (this._pollTimer) {
      clearInterval(this._pollTimer);
      this._pollTimer = null;
    }
  }

  /**
   * 销毁：停止轮询并重置状态
   */
  destroy() {
    this.stopPolling();
    this._initialized = false;
  }

  // ============================================================
  // 拉取与等级应用
  // ============================================================

  /**
   * 主动刷新一次压力状态（上传前/轮询时调用）
   */
  async refreshNow() {
    if (this._fetching) return;
    this._fetching = true;
    try {
      const { http } = await import('libs');
      const data = await http.get(API_ENDPOINTS.UPLOAD_PRESSURE);
      if (data && data.level) {
        this.applyLevel(data.level);
      }
    } catch (e) {
      // 拉取失败不阻断上传：保持当前等级，下次轮询重试
      console.debug('[UploadPressure] 拉取压力失败:', e?.message);
    } finally {
      this._fetching = false;
    }
  }

  /**
   * 应用压力等级（核心：降级立即，升级保守）
   * @param {string} newLevel - PRESSURE_LEVELS 之一
   */
  applyLevel(newLevel) {
    if (!PRESSURE_LEVEL_CONFIG[newLevel]) {
      console.warn('[UploadPressure] 未知压力等级:', newLevel);
      return;
    }

    const currentSeverity = LEVEL_SEVERITY[this._currentLevel];
    const newSeverity = LEVEL_SEVERITY[newLevel];

    if (newSeverity > currentSeverity) {
      // === 降级：立即生效 ===
      this._normalStreak = 0;
      this._applyLevelConfig(newLevel);
    } else if (newSeverity < currentSeverity) {
      // === 升级：保守恢复 ===
      if (newLevel === PRESSURE_LEVELS.NORMAL) {
        this._normalStreak += 1;
        if (this._normalStreak >= PRESSURE_RECOVERY_THRESHOLD) {
          // 连续 N 次 normal，恢复高并发
          this._applyLevelConfig(newLevel);
        } else {
          // 仍未达恢复阈值，保持当前降级状态
          // 仅更新 message 为后端最新（让用户感知趋势），但不提升并发
          this._updateMessageOnly(newLevel);
        }
      } else {
        // 向 busy 升级（从 critical -> busy）：同样保守，重置 streak
        this._normalStreak = 0;
        this._applyLevelConfig(newLevel);
      }
    } else {
      // === 同级：仅更新 message ===
      this._updateMessageOnly(newLevel);
    }
  }

  /**
   * 应用等级配置到 coreStore（修改并发上限 + 触发重新调度）
   */
  _applyLevelConfig(level) {
    const prevLevel = this._currentLevel;
    const config = PRESSURE_LEVEL_CONFIG[level];

    this._currentLevel = level;

    // 更新 coreStore 的可观察并发字段
    // maxConcurrentUploads 已是 @observable，UploadCoordinator.startWaiting 会读取它
    this.core.maxConcurrentUploads = config.maxConcurrentUploads;
    // maxConcurrentChunks 同步更新（当前分片串行，字段为预留/契约用）
    if ('maxConcurrentChunks' in this.core) {
      this.core.maxConcurrentChunks = config.maxConcurrentChunks;
    }
    if ('pressureLevel' in this.core) {
      this.core.pressureLevel = level;
    }
    if ('pressureMessage' in this.core) {
      this.core.pressureMessage = config.message;
    }

    // 等级变化时触发重新调度：
    //   - 降级：startWaiting 不会启动新任务（availableSlots 可能<=0），已运行的不受影响
    //   - 升级：startWaiting 会启动更多 waiting 任务
    if (prevLevel !== level) {
      try {
        // 【ESLint no-unused-expressions】obj?.method() 需写成 if 保护形式
        if (this.core.uploadCoordinator) {
          this.core.uploadCoordinator.startWaiting();
        }
      } catch (e) {
        console.debug('[UploadPressure] 触发重新调度失败:', e?.message);
      }
    }
  }

  /**
   * 仅更新提示文案，不改变并发配置（同级或未达恢复阈值时用）
   */
  _updateMessageOnly(level) {
    const config = PRESSURE_LEVEL_CONFIG[level];
    if ('pressureMessage' in this.core) {
      this.core.pressureMessage = config.message;
    }
  }

  // ============================================================
  // 查询
  // ============================================================

  get currentLevel() {
    return this._currentLevel;
  }

  get isInitialized() {
    return this._initialized;
  }
}

export default UploadPressureManager;
