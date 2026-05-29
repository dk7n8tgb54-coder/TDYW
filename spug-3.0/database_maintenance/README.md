# 数据库维护工具

此文件夹包含用于数据库碎片检查和优化的相关工具。

## 文件说明

### 1. check_and_optimize.sql
- **功能**：检查数据库碎片并执行优化
- **使用方法**：通过MySQL命令执行 `mysql -h 127.0.0.1 -P 3306 -u spug -pspug.cc < check_and_optimize.sql`
- **作用**：自动检测碎片并执行OPTIMIZE TABLE操作

### 2. check_fragmentation.bat
- **功能**：批处理文件，执行碎片检查
- **使用方法**：双击运行
- **作用**：显示碎片情况和所有表状态

### 3. check_fragmentation.py
- **功能**：Python脚本，使用Django ORM检查碎片
- **使用方法**：`python check_fragmentation.py`
- **依赖**：Django环境

### 4. check_fragmentation_simple.py
- **功能**：简单版Python脚本，使用pymysql检查碎片
- **使用方法**：`python check_fragmentation_simple.py`
- **依赖**：pymysql模块

### 5. database_optimization_plan.py
- **功能**：生成完整的数据库优化方案
- **使用方法**：`python database_optimization_plan.py`
- **作用**：分析数据库状态并提供优化建议

### 6. run_optimize.bat
- **功能**：批处理文件，执行完整的优化流程
- **使用方法**：双击运行
- **作用**：执行SQL脚本并显示优化结果

## 推荐使用流程

1. **定期检查**：每月运行一次 `database_optimization_plan.py` 分析数据库状态
2. **执行优化**：在业务低峰期运行 `run_optimize.bat` 执行优化
3. **验证结果**：优化后再次运行检查脚本确认效果

## 注意事项

- 优化操作会锁定表，建议在业务低峰期执行
- 确保有足够的磁盘空间用于临时操作
- 对于大表，优化时间可能较长，请耐心等待

## 优化频率

- **建议**：每月执行一次
- **最低**：每季度执行一次
- **特殊情况**：在大量数据变更后立即执行

## 联系信息

如有疑问，请参考相关文档或联系技术支持。
