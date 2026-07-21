# Copyright: (c) OpenSpug Organization. https://github.com/openspug/spug
# Copyright: (c) <spug.dev@gmail.com>
# Released under the AGPL-3.0 License.
"""
健康检查视图
用于监控系统各组件状态
【新增】数据库连接池监控
"""
import logging
from django.views.generic import View
from django.db import connection
from libs import json_response
from apps.document.libs.document_auth import document_auth

logger = logging.getLogger(__name__)


class HealthCheckView(View):
    """
    系统健康检查 API
    【注意】健康检查不需要登录验证
    【M-2修复】未认证端点不暴露组件错误细节，仅返回 ok/error 状态
    """

    def get(self, request):
        """
        执行健康检查

        Returns:
            200: 所有组件正常
            503: 有组件异常
        """
        checks = {
            'database': self._check_database(),
        }

        # 判断整体状态
        has_error = any(
            check.get('status') == 'error'
            for check in checks.values()
        )

        # 【M-2修复】未认证端点仅返回 ok/error，不暴露组件名和错误细节
        response_data = {
            'status': 'error' if has_error else 'ok',
        }

        if has_error:
            logger.error(f'[HealthCheck] 健康检查失败: {checks}')
            response = json_response(response_data)
            response.status_code = 503
            return response

        return json_response(response_data)
    
    def _check_database(self):
        """检查数据库连接"""
        try:
            with connection.cursor() as cursor:
                cursor.execute('SELECT 1')
                cursor.fetchone()
            return {'status': 'ok'}
        except Exception as e:
            # 【M-2修复】不向未认证用户暴露数据库错误细节
            logger.error(f'[HealthCheck] 数据库检查失败: {e}')
            return {
                'status': 'error',
                'error': 'database_error'  # 仅返回通用错误类型
            }


class DatabasePoolStatusView(View):
    """
    数据库连接池状态监控 API
    【新增】详细的连接池监控和告警
    需要登录验证
    """

    @document_auth('view')
    def get(self, request):
        """
        获取数据库连接池详细状态
        
        Returns:
            200: 连接池状态详情
        """
        status = self._get_pool_status()
        
        # 记录告警日志
        if status['status'] == 'warning':
            logger.warning(f'[DBPool] 连接池告警: {status["message"]}')
        elif status['status'] == 'error':
            logger.error(f'[DBPool] 连接池严重: {status["message"]}')
        
        return json_response(status)
    
    def _get_pool_status(self):
        """获取连接池详细状态"""
        try:
            with connection.cursor() as cursor:
                # 1. 当前连接数
                cursor.execute("SHOW STATUS LIKE 'Threads_connected'")
                threads_connected = int(cursor.fetchone()[1])
                
                # 2. 历史最大连接数
                cursor.execute("SHOW STATUS LIKE 'Max_used_connections'")
                max_used = int(cursor.fetchone()[1])
                
                # 3. 正在运行的线程数
                cursor.execute("SHOW STATUS LIKE 'Threads_running'")
                threads_running = int(cursor.fetchone()[1])
                
                # 4. 缓存中的线程数
                cursor.execute("SHOW STATUS LIKE 'Threads_cached'")
                threads_cached = int(cursor.fetchone()[1])
                
                # 5. 创建的线程总数
                cursor.execute("SHOW STATUS LIKE 'Threads_created'")
                threads_created = int(cursor.fetchone()[1])
                
                # 6. MySQL 最大连接数限制
                cursor.execute("SELECT @@max_connections")
                max_connections = int(cursor.fetchone()[0])
                
                # 7. 等待连接的次数
                cursor.execute("SHOW STATUS LIKE 'Connection_errors_internal'")
                conn_errors = int(cursor.fetchone()[1])
                
                # 8. 被拒绝的连接数
                cursor.execute("SHOW STATUS LIKE 'Aborted_connects'")
                aborted_connects = int(cursor.fetchone()[1])
                
                # 计算利用率
                utilization = (threads_connected / max_connections) * 100
                
                # 判断状态
                status = 'ok'
                if utilization > 80:
                    status = 'warning'
                if utilization > 95:
                    status = 'error'
                
                # 生成建议
                message = self._generate_advice(
                    utilization, threads_running, threads_cached, 
                    conn_errors, aborted_connects
                )
                
                return {
                    'status': status,
                    'timestamp': self._get_timestamp(),
                    'connections': {
                        'current': threads_connected,
                        'running': threads_running,
                        'cached': threads_cached,
                        'max_used': max_used,
                        'total_created': threads_created,
                        'max_allowed': max_connections,
                    },
                    'utilization': {
                        'percent': round(utilization, 2),
                        'display': f'{utilization:.1f}%'
                    },
                    'errors': {
                        'connection_errors': conn_errors,
                        'aborted_connects': aborted_connects,
                    },
                    'message': message,
                    'thresholds': {
                        'warning': 80,
                        'error': 95,
                        'max_connections': max_connections
                    }
                }
                
        except Exception as e:
            logger.error(f'[DBPool] 获取连接池状态失败: {e}')
            return {
                'status': 'error',
                'error': str(e),
                'message': '无法获取连接池状态'
            }
    
    def _generate_advice(self, utilization, running, cached, conn_errors, aborted):
        """根据状态生成建议"""
        advices = []
        
        if utilization > 90:
            advices.append(f'连接池利用率过高({utilization:.1f}%)，建议增加max_connections')
        elif utilization > 80:
            advices.append(f'连接池利用率偏高({utilization:.1f}%)，请关注')
        
        if running > 20:
            advices.append(f'活跃查询较多({running})，可能存在慢查询')
        
        if cached < 5:
            advices.append('线程缓存较少，建议增加thread_cache_size')
        
        if conn_errors > 0:
            advices.append(f'存在{conn_errors}个连接错误，请检查')
        
        if aborted > 100:
            advices.append(f'存在{aborted}个异常断开，请检查网络或客户端')
        
        if not advices:
            return '连接池状态正常'
        
        return '；'.join(advices)
    
    def _get_timestamp(self):
        """获取当前时间戳"""
        from datetime import datetime
        return datetime.now().isoformat()


class DatabasePoolMetricsView(View):
    """
    数据库连接池指标 API（用于监控系统集成）
    【新增】Prometheus/Grafana 格式
    需要登录验证
    """

    @document_auth('view')
    def get(self, request):
        """
        获取连接池指标（简化版，便于监控）
        
        Returns:
            200: 关键指标
        """
        try:
            with connection.cursor() as cursor:
                cursor.execute("SHOW STATUS LIKE 'Threads_connected'")
                connected = int(cursor.fetchone()[1])
                
                cursor.execute("SELECT @@max_connections")
                max_conn = int(cursor.fetchone()[0])
                
                cursor.execute("SHOW STATUS LIKE 'Threads_running'")
                running = int(cursor.fetchone()[1])
                
                utilization = (connected / max_conn) * 100
                
                # 返回简化格式，便于监控系统解析
                return json_response({
                    'db_pool_connected': connected,
                    'db_pool_running': running,
                    'db_pool_max': max_conn,
                    'db_pool_utilization': round(utilization, 2),
                    'db_pool_status': 'healthy' if utilization < 80 else 'warning' if utilization < 95 else 'critical'
                })
                
        except Exception as e:
            logger.error(f'[DBPool] 获取指标失败: {e}')
            return json_response({
                'error': '获取指标失败',
                'db_pool_status': 'unknown'
            })
