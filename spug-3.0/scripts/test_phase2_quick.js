/**
 * 快速验证 - 直接在控制台执行
 */

// 验证 P1-1: 班次列表
fetch('/api/schedule/shift/', {
    headers: {'X-Token': localStorage.getItem('token')}
}).then(r => r.json()).then(result => {
    const data = result.data || result;
    console.log('✅ P1-1 班次列表API:', data.length, '条记录');
    console.log('班次详情:');
    data.forEach((s, i) => {
        console.log(`  ${i+1}. ${s.name}: ${s.times?.length || 0} 个时间段`);
    });
});

// 验证 P1-3: 排班列表性能测试
(async () => {
    const times = [];
    for (let i = 0; i < 3; i++) {
        const start = performance.now();
        const r = await fetch('/api/schedule/?year=2026&month=3', {
            headers: {'X-Token': localStorage.getItem('token')}
        });
        const result = await r.json();
        const data = result.data || result;
        times.push(performance.now() - start);
    }
    const avg = times.reduce((a,b) => a+b, 0) / 3;
    console.log(`✅ P1-3 排班查询平均: ${avg.toFixed(1)}ms`);
})();
