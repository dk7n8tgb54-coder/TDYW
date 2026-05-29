/**
 * 第二阶段修复效果验证 - 浏览器控制台脚本
 * 
 * 使用方法:
 * 1. 打开排班管理页面
 * 2. F12 打开开发者工具
 * 3. 切换到 Console 标签
 * 4. 复制粘贴以下代码执行
 */

// ============================================
// 验证 P1-1 N+1查询优化 - 班次列表API性能
// ============================================
async function testShiftListPerformance() {
    console.log('%c=== 测试 P1-1: 班次列表API性能 ===', 'color: blue; font-size: 14px;');
    
    const token = localStorage.getItem('token');
    if (!token) {
        console.error('请先登录获取token');
        return;
    }
    
    const times = [];
    for (let i = 0; i < 3; i++) {
        const start = performance.now();
        try {
            const response = await fetch('/api/schedule/shift/', {
                headers: { 'X-Token': token }
            });
            const result = await response.json();
            const elapsed = performance.now() - start;
            times.push(elapsed);
            
            // 注意: json_response 返回 {data: [...], error: ''}
            const data = result.data || result;
            console.log(`第${i+1}次请求: ${elapsed.toFixed(1)}ms, 返回 ${data.length} 条班次数据`);
        } catch (e) {
            console.error(`第${i+1}次请求失败:`, e);
        }
    }
    
    if (times.length > 0) {
        const avg = times.reduce((a, b) => a + b, 0) / times.length;
        console.log(`%c平均响应时间: ${avg.toFixed(1)}ms`, 'color: green; font-weight: bold;');
        
        if (avg < 100) {
            console.log('%c✅ P1-1 N+1优化效果良好 (<100ms)', 'color: green;');
        } else if (avg < 500) {
            console.log('%c⚠️ 性能一般，可能需要进一步优化', 'color: orange;');
        } else {
            console.log('%c❌ 性能较差，请检查后端', 'color: red;');
        }
    }
}

// ============================================
// 验证班次数据结构 (检查 times 字段)
// ============================================
async function testShiftDataStructure() {
    console.log('%c=== 测试班次数据结构 ===', 'color: blue; font-size: 14px;');
    
    const token = localStorage.getItem('token');
    if (!token) return;
    
    try {
        const response = await fetch('/api/schedule/shift/', {
            headers: { 'X-Token': token }
        });
        const result = await response.json();
        const data = result.data || result;
        
        console.log(`班次数量: ${data.length}`);
        
        let allHaveTimes = true;
        data.forEach((shift, index) => {
            const timesCount = shift.times?.length || 0;
            console.log(`${index + 1}. ${shift.name}: ${timesCount} 个时间段`);
            if (!shift.hasOwnProperty('times')) {
                allHaveTimes = false;
            }
        });
        
        if (allHaveTimes) {
            console.log('%c✅ 所有班次都包含 times 字段', 'color: green;');
        } else {
            console.log('%c⚠️ 部分班次缺少 times 字段', 'color: orange;');
        }
        
    } catch (e) {
        console.error('数据检查失败:', e);
    }
}

// ============================================
// 验证 P1-3 索引优化 - 排班日历查询性能
// ============================================
async function testScheduleListPerformance() {
    console.log('%c=== 测试 P1-3: 排班日历查询性能 ===', 'color: blue; font-size: 14px;');
    
    const token = localStorage.getItem('token');
    if (!token) {
        console.error('请先登录获取token');
        return;
    }
    
    const times = [];
    const now = new Date();
    const year = now.getFullYear();
    const month = now.getMonth() + 1;
    
    for (let i = 0; i < 3; i++) {
        const start = performance.now();
        try {
            const response = await fetch(`/api/schedule/?year=${year}&month=${month}`, {
                headers: { 'X-Token': token }
            });
            const result = await response.json();
            const elapsed = performance.now() - start;
            times.push(elapsed);
            
            const data = result.data || result;
            console.log(`第${i+1}次请求: ${elapsed.toFixed(1)}ms, 返回 ${data.length} 条排班数据`);
        } catch (e) {
            console.error(`第${i+1}次请求失败:`, e);
        }
    }
    
    if (times.length > 0) {
        const avg = times.reduce((a, b) => a + b, 0) / times.length;
        console.log(`%c平均响应时间: ${avg.toFixed(1)}ms`, 'color: green; font-weight: bold;');
        
        if (avg < 200) {
            console.log('%c✅ P1-3 索引优化效果良好 (<200ms)', 'color: green;');
        } else if (avg < 1000) {
            console.log('%c⚠️ 性能一般', 'color: orange;');
        } else {
            console.log('%c❌ 性能较差', 'color: red;');
        }
    }
}

// ============================================
// 批量换班API测试 (P1-2 批量创建优化)
// ============================================
async function testBatchSwapCreate() {
    console.log('%c=== 测试 P1-2: 批量换班创建API ===', 'color: blue; font-size: 14px;');
    
    const token = localStorage.getItem('token');
    if (!token) {
        console.error('请先登录获取token');
        return;
    }
    
    // 先获取人员和班次数据
    try {
        const [staffRes, shiftRes] = await Promise.all([
            fetch('/api/schedule/staff/', { headers: { 'X-Token': token } }),
            fetch('/api/schedule/shift/', { headers: { 'X-Token': token } })
        ]);
        
        const staffResult = await staffRes.json();
        const shiftResult = await shiftRes.json();
        const staffList = staffResult.data || staffResult;
        const shiftList = shiftResult.data || shiftResult;
        
        if (staffList.length < 2 || shiftList.length < 1) {
            console.log('人员和班次数据不足，跳过批量创建测试');
            return;
        }
        
        // 构造批量换班数据
        const records = [];
        for (let i = 0; i < Math.min(3, staffList.length - 1); i++) {
            records.push({
                from_staff_id: staffList[i].id,
                from_staff_name: staffList[i].user_name,
                to_staff_id: staffList[i+1].id,
                to_staff_name: staffList[i+1].user_name,
                from_date: '2026-04-01',
                to_date: '2026-04-02',
                from_shift_id: shiftList[0].id,
                from_shift_name: shiftList[0].name,
                to_shift_id: shiftList[0].id,
                to_shift_name: shiftList[0].name,
                reason: '批量换班测试'
            });
        }
        
        console.log(`准备批量创建 ${records.length} 条换班记录...`);
        
        const start = performance.now();
        const response = await fetch('/api/schedule/batch_swap/', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'X-Token': token
            },
            body: JSON.stringify({ records })
        });
        
        const elapsed = performance.now() - start;
        const result = await response.json();
        
        console.log(`批量创建耗时: ${elapsed.toFixed(1)}ms`);
        console.log('返回结果:', result);
        
        if (response.ok && !result.error) {
            console.log('%c✅ P1-2 批量创建API工作正常', 'color: green;');
        } else {
            console.log('%c⚠️ API返回错误:', result.error || '未知错误', 'color: orange;');
        }
        
    } catch (e) {
        console.error('批量创建测试失败:', e);
    }
}

// ============================================
// 运行所有测试
// ============================================
async function runAllTests() {
    console.clear();
    console.log('%c========================================', 'color: purple; font-size: 16px;');
    console.log('%c  第二阶段修复效果验证', 'color: purple; font-size: 16px;');
    console.log('%c========================================', 'color: purple; font-size: 16px;');
    
    await testShiftListPerformance();
    await new Promise(r => setTimeout(r, 500));
    
    await testShiftDataStructure();
    await new Promise(r => setTimeout(r, 500));
    
    await testScheduleListPerformance();
    await new Promise(r => setTimeout(r, 500));
    
    await testBatchSwapCreate();
    
    console.log('%c========================================', 'color: purple; font-size: 16px;');
    console.log('%c  验证完成', 'color: purple; font-size: 16px;');
    console.log('%c========================================', 'color: purple; font-size: 16px;');
}

// 执行测试
runAllTests();

// 也可以单独测试:
// testShiftDataStructure();
