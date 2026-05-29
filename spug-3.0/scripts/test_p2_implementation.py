#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
P2任务实现验证脚本
测试内容：
1. 分片缓存管理器 (ChunkCacheManager)
2. _SUCCESS_标记文件管理器 (SuccessMarkerManager)
3. 超时检测任务 (check_merge_timeout)
"""

import os
import sys
import django

# 添加项目路径
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'spug_api'))
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'spug.settings')

try:
    django.setup()
    print("✅ Django 初始化成功")
except Exception as e:
    print(f"❌ Django 初始化失败: {e}")
    sys.exit(1)


def test_chunk_cache_manager():
    """测试分片缓存管理器"""
    print("\n" + "="*60)
    print("测试1: 分片缓存管理器 (ChunkCacheManager)")
    print("="*60)
    
    try:
        from apps.document.libs.chunk_cache import ChunkCacheManager
        
        # 创建缓存管理器实例
        cache_mgr = ChunkCacheManager(
            file_hash='test_hash_123',
            user_id=1,
            is_public=False
        )
        
        # 测试缓存键生成
        cache_key = cache_mgr.cache_key
        assert 'document:chunks' in cache_key, "缓存键格式错误"
        print(f"✅ 缓存键生成正确: {cache_key}")
        
        # 测试设置缓存
        test_chunks = [0, 1, 2, 3, 4]
        result = cache_mgr.set_cached_chunks(test_chunks, timeout=300)
        assert result is True, "设置缓存失败"
        print(f"✅ 缓存设置成功")
        
        # 测试获取缓存
        cached = cache_mgr.get_cached_chunks()
        assert cached is not None, "缓存未命中"
        assert cached == set(test_chunks), "缓存数据不匹配"
        print(f"✅ 缓存获取成功: {cached}")
        
        # 测试更新缓存
        result = cache_mgr.update_cache_after_upload(5, 6)
        assert result is True, "更新缓存失败"
        
        cached = cache_mgr.get_cached_chunks()
        assert 5 in cached, "更新后缓存不包含新分片"
        print(f"✅ 缓存更新成功")
        
        # 清理测试缓存
        cache_mgr.delete_cache()
        print(f"✅ 缓存清理成功")
        
        return True
        
    except Exception as e:
        print(f"❌ 测试失败: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_success_marker_manager():
    """测试_SUCCESS_标记文件管理器"""
    print("\n" + "="*60)
    print("测试2: _SUCCESS_标记文件管理器 (SuccessMarkerManager)")
    print("="*60)
    
    try:
        from apps.document.libs.chunk_cache import SuccessMarkerManager
        import tempfile
        
        # 创建临时目录
        with tempfile.TemporaryDirectory() as tmpdir:
            marker_mgr = SuccessMarkerManager(tmpdir)
            
            # 测试标记文件不存在
            exists = marker_mgr.exists()
            assert exists is False, "标记文件不应存在"
            print("✅ 标记文件不存在检测正确")
            
            # 创建标记文件
            result = marker_mgr.create(total_chunks=10, file_hash='abc123')
            assert result is True, "创建标记文件失败"
            print("✅ 标记文件创建成功")
            
            # 测试标记文件存在
            exists = marker_mgr.exists()
            assert exists is True, "标记文件应存在"
            print("✅ 标记文件存在检测正确")
            
            # 读取标记文件
            data = marker_mgr.read()
            assert data is not None, "读取标记文件失败"
            assert data.get('total_chunks') == '10', "total_chunks不匹配"
            assert data.get('file_hash') == 'abc123', "file_hash不匹配"
            print(f"✅ 标记文件读取成功: {data}")
            
            # 删除标记文件
            result = marker_mgr.delete()
            assert result is True, "删除标记文件失败"
            print("✅ 标记文件删除成功")
            
            # 确认已删除
            exists = marker_mgr.exists()
            assert exists is False, "标记文件应已删除"
            print("✅ 标记文件已确认删除")
        
        return True
        
    except Exception as e:
        print(f"❌ 测试失败: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_timeout_checker_import():
    """测试超时检测任务导入"""
    print("\n" + "="*60)
    print("测试3: 超时检测任务导入")
    print("="*60)
    
    try:
        from apps.document.tasks.timeout_checker import (
            check_merge_timeout,
            cleanup_stale_merging_tasks
        )
        
        print("✅ check_merge_timeout 导入成功")
        print("✅ cleanup_stale_merging_tasks 导入成功")
        
        # 验证是Celery任务
        assert hasattr(check_merge_timeout, 'delay'), "check_merge_timeout 不是Celery任务"
        assert hasattr(cleanup_stale_merging_tasks, 'delay'), "cleanup_stale_merging_tasks 不是Celery任务"
        print("✅ 任务已正确注册为Celery任务")
        
        return True
        
    except Exception as e:
        print(f"❌ 测试失败: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_celery_beat_schedule():
    """测试Celery Beat定时任务配置"""
    print("\n" + "="*60)
    print("测试4: Celery Beat定时任务配置")
    print("="*60)
    
    try:
        from apps.document.celery_beat_schedule import DOCUMENT_BEAT_SCHEDULE
        
        # 检查超时检测任务
        assert 'document-check-merge-timeout' in DOCUMENT_BEAT_SCHEDULE, \
            "document-check-merge-timeout 任务未配置"
        print("✅ document-check-merge-timeout 任务已配置")
        
        # 检查僵尸任务清理
        assert 'document-cleanup-stale-merging' in DOCUMENT_BEAT_SCHEDULE, \
            "document-cleanup-stale-merging 任务未配置"
        print("✅ document-cleanup-stale-merging 任务已配置")
        
        # 检查任务参数
        timeout_task = DOCUMENT_BEAT_SCHEDULE['document-check-merge-timeout']
        assert timeout_task['task'] == 'apps.document.tasks.timeout_checker.check_merge_timeout', \
            "任务路径错误"
        assert 'schedule' in timeout_task, "schedule未配置"
        print(f"✅ 超时检测任务配置正确: {timeout_task['schedule']}")
        
        stale_task = DOCUMENT_BEAT_SCHEDULE['document-cleanup-stale-merging']
        assert stale_task['task'] == 'apps.document.tasks.timeout_checker.cleanup_stale_merging_tasks', \
            "任务路径错误"
        print(f"✅ 僵尸任务清理配置正确: {stale_task['schedule']}")
        
        return True
        
    except Exception as e:
        print(f"❌ 测试失败: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_updated_at_field():
    """测试DocumentTransfer模型的updated_at字段"""
    print("\n" + "="*60)
    print("测试5: DocumentTransfer模型的updated_at字段")
    print("="*60)
    
    try:
        from apps.document.models import DocumentTransfer
        
        # 检查字段存在
        assert hasattr(DocumentTransfer, 'updated_at'), "updated_at 字段不存在"
        print("✅ updated_at 字段存在")
        
        # 检查字段类型
        from django.db import models
        field = DocumentTransfer._meta.get_field('updated_at')
        assert isinstance(field, models.DateTimeField), "updated_at 不是DateTimeField"
        print("✅ updated_at 字段类型正确 (DateTimeField)")
        
        # 检查auto_now属性
        assert field.auto_now is True, "updated_at 未设置auto_now=True"
        print("✅ updated_at 已设置auto_now=True")
        
        return True
        
    except Exception as e:
        print(f"❌ 测试失败: {e}")
        import traceback
        traceback.print_exc()
        return False


def main():
    """运行所有测试"""
    print("\n" + "="*70)
    print("  P2任务实现验证")
    print("="*70)
    
    tests = [
        ("分片缓存管理器", test_chunk_cache_manager),
        ("_SUCCESS_标记文件管理器", test_success_marker_manager),
        ("超时检测任务导入", test_timeout_checker_import),
        ("Celery Beat定时任务配置", test_celery_beat_schedule),
        ("DocumentTransfer updated_at字段", test_updated_at_field),
    ]
    
    results = []
    for name, test_func in tests:
        try:
            result = test_func()
            results.append((name, result))
        except Exception as e:
            print(f"\n❌ {name} 测试异常: {e}")
            results.append((name, False))
    
    # 打印汇总
    print("\n" + "="*70)
    print("  测试结果汇总")
    print("="*70)
    
    passed = sum(1 for _, r in results if r)
    total = len(results)
    
    for name, result in results:
        status = "✅ 通过" if result else "❌ 失败"
        print(f"  {status}: {name}")
    
    print(f"\n  总计: {passed}/{total} 通过")
    
    if passed == total:
        print("\n🎉 所有P2任务测试通过！")
        return 0
    else:
        print("\n⚠️  部分测试失败，请检查")
        return 1


if __name__ == '__main__':
    sys.exit(main())
