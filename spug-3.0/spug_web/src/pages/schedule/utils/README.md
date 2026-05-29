# 排班模块工具函数

## 第一阶段重构：基础设施

### 文件列表

| 文件 | 说明 | 功能 |
|------|------|------|
| `constants.js` | 常量定义 | SwapStatus, ScheduleStatus, ShiftType等 |
| `dateUtils.js` | 日期处理工具 | formatDate, getMonthRange, isSameMonth等 |
| `scheduleAlgorithm.js` | 自动排班算法 | generateAutoSchedule, checkScheduleListConflicts等 |

### 使用示例

```javascript
// 导入常量
import { SwapStatus, StatusText } from './utils/constants';

// 导入日期工具
import { formatDate, getMonthRange } from './utils/dateUtils';

// 导入排班算法
import { generateAutoSchedule } from './utils/scheduleAlgorithm';
```

### 注意事项

- 所有工具函数都经过单元测试验证
- 保持与后端常量定义一致
- 日期处理统一使用 moment.js
