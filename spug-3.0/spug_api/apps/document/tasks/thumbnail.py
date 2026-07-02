# Copyright: (c) OpenSpug Organization
# Released under the AGPL-3.0 License.
"""
资料库缩略图异步生成任务

【改造目标】
将缩略图生成从上传/合并请求线程中剥离，交给独立 Celery 队列
`document.thumbnail` 异步消费，避免 Pillow 解码吃 CPU 拖慢上传
接口响应或合并任务耗时。

【设计要点】
1. 复用现有 `thumbnail_service.generate_thumbnail_for_file`，不重写
   图片处理逻辑。
2. 任务入参只传 `file_id` 与 `is_public`，文件路径等在任务执行时
   再从数据库读取，避免传入陈旧路径。
3. 软删除文件 (`is_deleted=True`) 默认被 `SoftDeletedManager` 过滤，
   任务查不到记录会安全退出，不会为已删除文件生成缩略图。
4. 非图片文件直接安全退出，不报错。
5. 缩略图生成失败只记录日志，不影响文件上传成功语义。
6. 任务由 `document.thumbnail` 队列消费，需独立 worker 或由其他
   worker 兼听该队列。
"""
import logging

from celery import shared_task

logger = logging.getLogger(__name__)

# Celery 任务配置
# 缩略图生成一般几秒内完成，给宽松一点的软/硬超时兜底
THUMBNAIL_SOFT_TIME_LIMIT_SECONDS = 120   # 软超时 2 分钟
THUMBNAIL_HARD_TIME_LIMIT_SECONDS = 180   # 硬超时 3 分钟
THUMBNAIL_MAX_RETRIES = 2                 # 失败重试次数（仅对可恢复异常）
THUMBNAIL_RETRY_DELAY_SECONDS = 30        # 重试间隔


@shared_task(
    bind=True,
    max_retries=THUMBNAIL_MAX_RETRIES,
    default_retry_delay=THUMBNAIL_RETRY_DELAY_SECONDS,
    soft_time_limit=THUMBNAIL_SOFT_TIME_LIMIT_SECONDS,
    time_limit=THUMBNAIL_HARD_TIME_LIMIT_SECONDS,
    queue='document.thumbnail',
)
def generate_document_thumbnail(self, file_id, is_public):
    """
    异步生成资料库文件缩略图

    Args:
        file_id: 文件记录主键
        is_public: 是否公共资料库（决定使用 DocumentFilePublic/Private）

    安全退出条件（不报错、不重试）：
        - 文件记录不存在（可能已被删除）
        - 文件已被软删除（SoftDeletedManager 默认过滤）
        - 不是支持的图片类型

    失败处理：
        - Pillow 处理异常：记录 warning 日志，不重试（避免对损坏图片反复重试）
        - 数据库异常：抛出并触发 Celery 重试
    """
    if not file_id:
        logger.warning('[Thumbnail] generate_document_thumbnail called with empty file_id, skip.')
        return

    # 延迟导入，避免 Celery 加载阶段触发 Django 模型初始化
    from apps.document.libs.document_utils import get_file_model
    from apps.document.services.thumbnail_service import (
        generate_thumbnail_for_file,
        ThumbnailGenerator,
    )

    FileModel = get_file_model(is_public=is_public)

    # 查询文件记录
    # 注意：FileModel.objects 默认是 SoftDeletedManager，
    # 已删除文件 (is_deleted=True) 不会被查到，自然安全退出。
    file_record = FileModel.objects.filter(pk=file_id).first()
    if file_record is None:
        logger.info(
            f'[Thumbnail] File record not found or soft-deleted, '
            f'skip thumbnail: file_id={file_id}, is_public={is_public}'
        )
        return

    # 仅对支持的图片类型生成
    file_path = file_record.file_path
    physical_name = file_record.physical_name

    if not file_path or not physical_name:
        logger.info(
            f'[Thumbnail] File record missing file_path/physical_name, '
            f'skip: file_id={file_id}'
        )
        return

    if not ThumbnailGenerator.is_supported_image(file_path):
        logger.debug(
            f'[Thumbnail] Not a supported image, skip: file_id={file_id}, '
            f'path={file_path}'
        )
        return

    # 已有缩略图则跳过（重复任务幂等保护）
    if file_record.thumbnail_path:
        logger.info(
            f'[Thumbnail] Thumbnail already exists, skip: file_id={file_id}, '
            f'path={file_record.thumbnail_path}'
        )
        return

    logger.info(
        f'[Thumbnail] Start generating thumbnail: file_id={file_id}, '
        f'is_public={is_public}, path={file_path}'
    )

    # 调用现有 thumbnail_service 生成缩略图
    try:
        thumbnail_path = generate_thumbnail_for_file(file_path, physical_name)
    except Exception as e:
        # Pillow 解码/保存异常，多为图片损坏或格式异常
        # 不重试（重试也不会成功），仅记录日志，不影响上传
        logger.warning(
            f'[Thumbnail] Failed to generate thumbnail (image processing error): '
            f'file_id={file_id}, path={file_path}, error={e}'
        )
        return

    if not thumbnail_path:
        # generate_thumbnail_for_file 内部异常时返回 None
        logger.warning(
            f'[Thumbnail] generate_thumbnail_for_file returned None: '
            f'file_id={file_id}, path={file_path}'
        )
        return

    # 更新 thumbnail_path
    try:
        updated = FileModel.objects.filter(pk=file_id).update(
            thumbnail_path=thumbnail_path
        )
        if updated:
            logger.info(
                f'[Thumbnail] Thumbnail generated and saved: file_id={file_id}, '
                f'thumbnail_path={thumbnail_path}'
            )
        else:
            # 记录可能在任务执行期间被删除
            logger.warning(
                f'[Thumbnail] File record disappeared before update: '
                f'file_id={file_id}'
            )
    except Exception as e:
        # 数据库异常：尝试重试（可能是瞬时连接问题）
        logger.error(
            f'[Thumbnail] Failed to update thumbnail_path, will retry: '
            f'file_id={file_id}, error={e}'
        )
        try:
            raise self.retry(exc=e)
        except self.MaxRetriesExceededError:
            logger.error(
                f'[Thumbnail] Max retries exceeded when updating thumbnail_path: '
                f'file_id={file_id}'
            )
