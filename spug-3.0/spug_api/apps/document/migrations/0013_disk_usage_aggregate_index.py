# 为私有空间文件表补充磁盘用量聚合专用索引。
#
# 背景：DiskUsageView 的聚合查询
#   DocumentFilePrivate.objects.filter(is_deleted=False).filter(tenant_id=?)
#       .aggregate(total_size=Sum('file_size'))
# 不带 folder_id，无法走现有 doc_pri_file_list_idx=(folder_id, tenant_id,
# is_deleted, -created_at, -id) 的左前缀，生产环境多租户大表退化为全表扫描。
# 前端 useDiskSpace 每 30s 轮询一次，多账号并发上传时 N 个浏览器同时轮询，
# 全表扫描与上传 INSERT 争抢 DB 连接 / IO，拖慢整体上传吞吐。
#
# 本迁移新增覆盖索引 (tenant_id, is_deleted, file_size)：
#   1. 前导列 tenant_id 选择性好，服务 WHERE tenant_id=? 过滤；
#   2. is_deleted 配合 WHERE is_deleted=False 进一步收敛；
#   3. 末尾 file_size 让 SUM(file_size) 直接在索引上完成，无需回表。
#
# 公共空间表（DocumentFilePublic）聚合查询 WHERE is_deleted=False 无 tenant_id
# 前导列可用，is_deleted 选择性极差（仅 True/False），加单列索引优化器大概率
# 放弃使用，故不为公共表加索引，改为在 DiskUsageView 层加 Redis 缓存解决。

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('document', '0012_system_folder_unique_folder'),
    ]

    operations = [
        migrations.AddIndex(
            model_name='documentfileprivate',
            index=models.Index(
                fields=['tenant_id', 'is_deleted', 'file_size'],
                name='doc_pri_file_diskusage_idx',
            ),
        ),
    ]
