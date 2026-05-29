# Upload StateMachine 测试文档

## 测试策略说明

本测试采用**分层测试策略**：

| 层级 | 文件 | 说明 | 依赖 |
|------|------|------|------|
| L1 - 核心功能 | `UploadStateMachine.core.test.js` | 纯状态机逻辑测试 | **零外部依赖** |
| L2 - 完整功能 | `UploadStateMachine.test.js` | 包含钩子、验证、监控 | Mock外部store |
| L3 - 管理器 | `StateMachineManager.test.js` | 状态机管理功能 | Mock外部store |
| L4 - 边界情况 | `boundary.test.js` | 异常、并发、性能测试 | Mock外部store |

## 测试执行

```bash
# 只运行核心功能测试（最快，推荐日常开发）
npm test -- UploadStateMachine.core.test.js

# 运行所有状态机测试（CI/CD）
npm test -- --testPathPattern="stores/upload/core/__tests__"

# 运行单个文件
npm test -- UploadStateMachine.test.js
npm test -- StateMachineManager.test.js

# 带覆盖率报告
npm test -- --coverage --testPathPattern="stores/upload/core/__tests__"
```

## 测试分层详解

### L1: 核心功能测试（UploadStateMachine.core.test.js）

**特点**: 完全不依赖外部store，只测试状态机本身

覆盖范围：
- 状态定义（7个状态）
- 状态转换图（所有有效路径）
- 守卫条件（RESUME分支逻辑）
- 监听器机制（添加/移除/通知）
- 历史记录（格式/副本保护）
- 工具方法（canTransition/isInState）

### L2-L4: 完整功能测试

包含与外部store交互的测试（使用mock），以及边界情况测试。

## 测试设计原则

1. **分层独立**: L1测试不依赖任何外部store，可独立运行
2. **可重复性**: 多次运行结果一致
3. **快速反馈**: L1测试<1秒，适合日常开发
4. **全面覆盖**: 四层测试覆盖所有场景
