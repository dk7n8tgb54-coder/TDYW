# CheckSheet 中文字体配置说明

## 为什么要字体文件？

CheckSheet 的 PDF 导出功能需要中文字体来正确显示中文内容。这**不是**读取数据库数据的问题，而是 PDF 渲染的技术要求：

- **数据库存储**：只存储中文文本（如"检查项目"），不包含字形信息
- **PDF 渲染**：需要字体文件来绘制这些中文字符的图形形状

## 解决方案

### 方案A：使用项目内嵌字体（推荐）✅

将字体文件放在 `spug_api/apps/checksheet/fonts/` 目录下，避免依赖宿主机系统。

**步骤：**
1. 获取 simhei.ttf 字体文件（约10MB）
   - 从 Windows 复制：`C:\Windows\Fonts\simhei.ttf`
   - 或下载开源字体：https://github.com/StellarCN/scp_zh/tree/master/fonts
2. 放置到：`spug_api/apps/checksheet/fonts/simhei.ttf`
3. 重启 Spug 容器

**优点：**
- ✅ 不依赖宿主机系统字体
- ✅ 跨平台一致性（Windows/Linux 都能正常工作）
- ✅ 便于部署和管理

### 方案B：使用系统字体（不推荐）⚠️

不放置字体文件，依赖宿主机系统字体。

**系统路径：**
- Windows: `C:\Windows\Fonts\simhei.ttf`
- Linux: `/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc`

**缺点：**
- ❌ 依赖宿主机环境，可能在不同系统上失效
- ❌ Docker 容器内可能缺少中文字体

## 当前实现逻辑

代码优先级：
1. **优先级1**：读取 `checksheet/fonts/simhei.ttf`（内嵌字体）
2. **优先级2**：读取 `checksheet/fonts/simhei.otf`（内嵌字体）
3. **优先级3**：回退到系统字体路径

## 快速配置

如果你有 Windows 系统：
```bash
# 复制字体文件
cp /mnt/c/Windows/Fonts/simhei.ttf e:/TDYW/spug-3.0/spug_api/apps/checksheet/fonts/

# 或者使用 PowerShell（在 Windows 上执行）
copy C:\Windows\Fonts\simhei.ttf e:\TDYW\spug-3.0\spug_api\apps\checksheet\fonts\
```

## 验证方法

导出 PDF 后，查看日志输出：
```
[CheckSheet] Registered font: /app/spug_api/apps/checksheet/fonts/simhei.ttf
```

如果显示：
```
[CheckSheet] Warning: No Chinese font found, text may display as squares
```
说明字体文件未正确加载，需要检查字体文件路径。
