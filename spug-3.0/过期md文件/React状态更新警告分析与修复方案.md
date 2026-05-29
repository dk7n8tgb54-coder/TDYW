# React 状态更新警告分析与修复方案

## 警告信息

```
Warning: Can't perform a React state update on an unmounted component.
This is a no-op, but it indicates a memory leak in your application.
```

**调用堆栈位置**：
```
in Overflow (created by SelectSelector)
in SelectSelector (created by Selector)
in Selector (created by Trigger)
...
in DeviceResume (created by Context.Consumer)
in Route (at layout/index.js:21)
```

---

## 问题分析

### 1. 问题根源

该警告发生在设备管理页面（`spug_web/src/pages/device/index.js`）的 `Select` 组件中。具体来说，是在搜索表单的几个下拉选择框中：

- 设备型号选择器（第27-36行）
- 当前设备状况选择器（第39-51行）
- 使用单位选择器（第54-63行）

### 2. 产生原因

当用户快速切换页面或在数据加载过程中离开页面时，可能发生以下时序：

1. **组件挂载** → `Select` 组件开始渲染
2. **触发数据加载** → `store.fetchRecords()` 或 `store.fetchFilterOptions()` 发起 HTTP 请求
3. **组件卸载** → 用户导航到其他页面，`DeviceResume` 组件从 DOM 移除
4. **请求完成** → 异步请求返回数据，尝试更新 `store.useUnits` 或 `store.deviceModels`
5. **状态更新** → MobX 更新 `store` 中的 observable 属性
6. **组件重渲染** → React 尝试在已卸载的组件上触发重新渲染
7. **警告触发** → React 检测到对已卸载组件的状态更新

### 3. 具体代码路径

**问题代码1**：`store.js:77-86` - `fetchFilterOptions()`
```javascript
fetchFilterOptions = () => {
  const promises = [];
  promises.push(http.get('/api/device/device-resume/?use_units=1').then(res => {
    this.useUnits = res;  // ← 可能触发已卸载组件的渲染
  }));
  promises.push(http.get('/api/device/device-resume/?device_models=1').then(res => {
    this.deviceModels = res;  // ← 可能触发已卸载组件的渲染
  }));
  return Promise.all(promises);
};
```

**问题代码2**：`index.js:33, 60` - Select 组件绑定
```javascript
{store.deviceModels.map(item => (  // ← useUnits/deviceModels 更新时触发重渲染
  <Select.Option key={item} value={item}>{item}</Select.Option>
))}
```

---

## 为什么会形成内存泄漏

1. **未取消的异步请求**：组件卸载时，HTTP 请求仍然在后台进行
2. **Store 全局状态**：`useUnits` 和 `deviceModels` 存储在全局 Store 中
3. **组件订阅未清理**：`observer` 包裹的组件会自动订阅 MobX observable
4. **延迟状态更新**：请求完成后更新全局状态，触发所有订阅组件重渲染

虽然 MobX 的 `observer` 会自动管理订阅，但组件卸载后 Store 的更新仍可能触发警告。

---

## 修复方案

### 方案1：添加请求取消（推荐）✅

**原理**：在组件卸载时取消所有进行中的 HTTP 请求。

**实现步骤**：

#### 1.1 修改 `store.js`，使用 AbortController

```javascript
// 新增请求控制器
class Store {
  @observable useUnits = [];
  @observable deviceModels = [];
  _abortController = null;  // 新增：请求控制器

  fetchFilterOptions = () => {
    // 取消之前的请求
    if (this._abortController) {
      this._abortController.abort();
    }
    this._abortController = new AbortController();

    const signal = this._abortController.signal;
    const promises = [];

    promises.push(http.get('/api/device/device-resume/?use_units=1', { signal }).then(res => {
      this.useUnits = res;
    }));

    promises.push(http.get('/api/device/device-resume/?device_models=1', { signal }).then(res => {
      this.deviceModels = res;
    }));

    return Promise.all(promises);
  };
}
```

#### 1.2 修改 `index.js`，在组件卸载时清理

```javascript
import React, { useEffect } from 'react';
import { observer } from 'mobx-react';

export default observer(function DeviceResume() {
  useEffect(() => {
    // 组件挂载时加载数据
    store.fetchFilterOptions();
    store.fetchRecords();

    return () => {
      // 组件卸载时取消请求
      if (store._abortController) {
        store._abortController.abort();
      }
    };
  }, []);

  return (
    <AuthDiv auth="device.device_resume.view">
      {/* ... */}
    </AuthDiv>
  );
})
```

---

### 方案2：添加组件卸载标记（简单但不彻底）

**原理**：在 Store 中添加标记，阻止已卸载组件的数据更新。

#### 2.1 修改 `store.js`

```javascript
class Store {
  @observable isMounted = false;  // 组件挂载状态

  fetchFilterOptions = () => {
    if (!this.isMounted) return;  // 如果未挂载，直接返回

    const promises = [];
    promises.push(http.get('/api/device/device-resume/?use_units=1').then(res => {
      if (this.isMounted) {  // 再次检查
        this.useUnits = res;
      }
    }));
    // ...
  };
}
```

#### 2.2 修改 `index.js`

```javascript
export default observer(function DeviceResume() {
  useEffect(() => {
    store.isMounted = true;
    store.fetchFilterOptions();
    store.fetchRecords();

    return () => {
      store.isMounted = false;
    };
  }, []);

  // ...
})
```

**缺点**：请求仍会完成，只是不更新状态，浪费资源。

---

### 方案3：使用 React 的 useReducer + 挂载检查（React 方式）

**原理**：将状态管理从 MobX Store 转移到 React 组件内部。

```javascript
import React, { useState, useEffect, useRef } from 'react';

export default function DeviceResume() {
  const [useUnits, setUseUnits] = useState([]);
  const [deviceModels, setDeviceModels] = useState([]);
  const isMounted = useRef(true);

  useEffect(() => {
    isMounted.current = true;

    const loadOptions = async () => {
      try {
        const [unitsRes, modelsRes] = await Promise.all([
          http.get('/api/device/device-resume/?use_units=1'),
          http.get('/api/device/device-resume/?device_models=1')
        ]);

        if (isMounted.current) {  // 检查组件是否仍挂载
          setUseUnits(unitsRes);
          setDeviceModels(modelsRes);
        }
      } catch (err) {
        if (isMounted.current) {
          message.error('加载失败');
        }
      }
    };

    loadOptions();

    return () => {
      isMounted.current = false;
    };
  }, []);

  // ...
}
```

**缺点**：需要重构现有架构，工作量较大。

---

### 方案4：使用 MobX 的 autorun + dispose（MobX 方式）

**原理**：使用 MobX 的响应式特性，在组件卸载时清理订阅。

```javascript
import React, { useEffect, useRef } from 'react';
import { autorun } from 'mobx';

export default observer(function DeviceResume() {
  const disposerRef = useRef(null);

  useEffect(() => {
    // 创建响应式订阅
    disposerRef.current = autorun(() => {
      if (store.useUnits.length === 0 && store.deviceModels.length === 0) {
        store.fetchFilterOptions();
      }
    });

    return () => {
      // 组件卸载时清理订阅
      if (disposerRef.current) {
        disposerRef.current();
      }
    };
  }, []);

  // ...
})
```

**缺点**：无法直接取消 HTTP 请求，只是停止响应式更新。

---

## 推荐方案对比

| 方案 | 优点 | 缺点 | 复杂度 | 推荐度 |
|------|------|------|---------|--------|
| 方案1：AbortController | ✅ 完全取消请求<br>✅ 节省资源<br>✅ 避免无效更新 | 需要修改 Store | 中 | ⭐⭐⭐⭐⭐ |
| 方案2：挂载标记 | ✅ 实现简单 | ❌ 请求仍会完成<br>❌ 浪费资源 | 低 | ⭐⭐⭐ |
| 方案3：React useState | ✅ 完全避免问题 | ❌ 需要重构架构<br>❌ 失去全局状态优势 | 高 | ⭐⭐ |
| 方案4：MobX autorun | ✅ 符合 MobX 架构 | ❌ 无法取消请求<br>❌ 仅停止响应 | 中 | ⭐⭐⭐ |

---

## 最终推荐实现（方案1）

### 完整代码修改

#### 1. 修改 `spug_web/src/pages/device/store.js`

```javascript
class Store {
  @observable useUnits = [];
  @observable deviceModels = [];
  _abortController = null;  // 新增

  fetchFilterOptions = () => {
    // 取消之前的请求
    if (this._abortController) {
      this._abortController.abort();
    }
    this._abortController = new AbortController();

    const signal = this._abortController.signal;
    const promises = [];

    promises.push(http.get('/api/device/device-resume/?use_units=1', { signal }).then(res => {
      this.useUnits = res;
    }).catch(err => {
      // 忽略取消的请求
      if (err.name !== 'AbortError') {
        console.error('[Store] 获取使用单位失败:', err);
      }
    }));

    promises.push(http.get('/api/device/device-resume/?device_models=1', { signal }).then(res => {
      this.deviceModels = res;
    }).catch(err => {
      if (err.name !== 'AbortError') {
        console.error('[Store] 获取设备型号失败:', err);
      }
    }));

    return Promise.all(promises);
  };
}
```

#### 2. 修改 `spug_web/src/pages/device/index.js`

```javascript
import React, { useEffect } from 'react';
import { observer } from 'mobx-react';
// ...

export default observer(function DeviceResume() {
  useEffect(() => {
    // 组件挂载时加载数据
    store.fetchFilterOptions();
    store.fetchRecords();

    return () => {
      // 组件卸载时取消请求
      if (store._abortController) {
        store._abortController.abort();
      }
    };
  }, []);

  return (
    <AuthDiv auth="device.device_resume.view">
      {/* ... */}
    </AuthDiv>
  );
})
```

---

## 预期效果

- ✅ **消除警告**：组件卸载时取消请求，不再尝试更新状态
- ✅ **避免内存泄漏**：未完成的请求和回调会被正确清理
- ✅ **提升性能**：减少无效的网络请求和状态更新
- ✅ **用户体验改善**：快速切换页面时不会加载不需要的数据

---

## 注意事项

1. **http 库兼容性**：确保项目中的 `http` 封装库支持 `AbortSignal` 参数
2. **并发请求处理**：多个组件共享同一个 Store 时，需要更复杂的取消逻辑
3. **测试验证**：修复后需要在开发环境验证警告是否消失

---

## 其他相关警告（次要）

### React 生命周期警告

```
componentWillMount has been renamed
componentWillReceiveProps has been renamed
```

**原因**：图表库（@ant-design/charts）内部使用了旧版生命周期

**解决方案**：等待图表库升级，或使用 `eslint-disable-next-line` 忽略

### ESLint 警告

```
'http' is defined but never used
'Progress' is defined but never used
```

**解决方案**：删除未使用的导入

### React Hooks 依赖警告

```
useEffect has a missing dependency: 'fetchSwapData'
```

**解决方案**：将 `fetchSwapData` 加入依赖数组，或使用 `useCallback` 包装

---

## 总结

**核心问题**：组件卸载后仍执行异步状态更新导致内存泄漏。

**最佳修复**：使用 `AbortController` 在组件卸载时取消 HTTP 请求，从源头阻止无效的状态更新。

**实施优先级**：方案1 > 方案2 > 方案4 > 方案3
