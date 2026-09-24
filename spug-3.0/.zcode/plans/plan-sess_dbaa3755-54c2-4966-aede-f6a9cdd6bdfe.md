## 目标:今日巡检 = 一天一张台账,像纸质本子一样往里记

**形态**:工作台变成"今日一张表"——每次检查点"记录本次"存入**当日同一张台账**(草稿态),写完一天(或任意时刻)点"提交台账"转待复核。当天所有系统×所有轮次的明细合并在一张台账里,**每条明细自带实际执行时刻**(用模型已有的 `executed_at` 字段,列头/详情展示),一天一条记录,列表/复核/导出都按天。顺带修复现存缺陷:工作台当前创建的是草稿却提示"已提交,待复核"。

## 已核实的事实(后端今天就能支持,零迁移)

- `OperationLedgerItem.executed_at`(明细实际执行时间)已全链路支持:创建解析(`ledger_services.py:379` 附近 `_build_item_instance`)、详情返回(`models.py:1247`)。
- `create_ledger` 固定创建草稿态;`update_ledger`(`ledger_services.py:461-539`)支持对草稿台账按 id 保留/无 id 新增/缺失删除的方式追加明细,带 version 并发控制。
- `submit/return/void` 状态机现成。**无需任何后端接口、模型、迁移改动。**
- 现存缺陷:工作台 `handleSubmit` 只 POST 创建(草稿)却提示"已提交,待复核"(`LedgerWorksheet.js:294`),需随本次重构一并纠正。

## 改动内容

### 1. `LedgerWorksheet.js`(核心重做,巡检/周月/季共用组件)
- state 增加:`ledgerId`/`ledgerVersion`(当日草稿台账)、`rounds: [{time, values}]`(已记录轮次)、当前填写轮。
- **挂载恢复**:查当日草稿 `GET /ledgers/?ledger_type=inspection&status=draft&executed_from=today&executed_to=today` → 有则拉详情,按 `executed_at` 把 items 还原成轮次列;无则正常引导选模板。当日已提交则顶部显示状态,再填写另起新张。
- **"记录本次"**:校验 → 首次 `POST /ledgers/`(entries 含全部系统、items 带 `executed_at`=本轮时刻)创建当日草稿;后续 `PUT /ledgers/{id}/`(已有 items 带 id + 新轮 items 不带 id)追加;响应刷新 item ids。记录后当前区清空、时刻自动刷新为当前,已记录列变只读留底。
- **"提交台账"**:`POST /ledgers/{id}/submit/` → 提示"今日台账已提交,待复核",重建空表。
- localStorage 只暂存**当前未记录轮**(结构加 `round_time`);已记录轮次以服务器草稿为准。"空骨架不入暂存"逻辑保留。
- 当前轮"检查时刻"输入默认当前 HH:mm、可改(补录=改日期+时刻)。模板组合调整只影响后续轮次。

### 2. `ledgerCommon.js` / `LedgerRowsTable.js`
- items 载荷加 `executed_at`;新增已记录轮次的只读网格渲染(行=检查项目,列=轮次,列头=时刻);`buildSubmitEntries` 支持按轮次注入时刻。

### 3. `LedgerDetail.js`(小改)
- 明细增加"实际执行时刻"(`executed_at`)展示,同系统多轮按时间分组或加列。

### 4. CSV 导出(`ledger_views.py`,可选小改)
- 明细导出行增加 `executed_at` 列(改动后跑 ledger 相关后端测试)。

### 5. 测试
- 重写 `LedgerWorksheet.test.js`:首轮记录=创建草稿(断言 items 带 executed_at)、次轮=PUT 追加(已有项带 id)、提交调 submit、当日草稿恢复、补录改日期+时刻、空骨架不暂存保留。
- 后端零改动,跑 `apps.equipment_lifecycle` 测试确认无回归(create/update/submit 既有覆盖)。
- `npm test`(CI=true)全绿;改动文件一律 LF。

## 明确不做
- 无数据库迁移、无新后端接口;不加进度/目标次数统计;不动权限路由;`executed_start` 表头字段继续留空(时刻由明细 `executed_at` 承载,比上一版方案更准)。

## 已知取舍
- 提交后当日再填会另起一张(顶部有状态提示,少见场景)。
- 忘记日终提交:草稿在列表可见,可次日补提交(executed_date 不受影响)。