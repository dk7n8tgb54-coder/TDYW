#!/usr/bin/env python3
"""
Document views.py 拆分脚本
按功能模块将大文件拆分为多个小文件
"""

import re
import os

# 定义拆分规则： (新文件名, [类名列表], [额外导入])
SPLIT_RULES = [
    (
        'folder.py',
        ['FolderSearchView', 'FolderView', 'FolderCopyView', 'FolderMoveView', 
         'FolderDownloadView', 'FolderRenameView'],
        []  # 额外导入
    ),
    (
        'file.py', 
        ['FileView', 'FileUploadView', 'FileDownloadView', 'FilePreviewView',
         'FileCopyView', 'FileMoveView', 'FileRenameView'],
        []
    ),
    (
        'upload.py',
        ['FileChunkUploadView', 'FileMergeChunksView', 'CheckUploadedChunksView', 
         'FileMergeStatusView'],
        ['threading', 'time', 'os', 'json']
    ),
    (
        'transfer.py',
        ['TransferListView', 'TransferCreateView', 'TransferProgressUpdateView',
         'TransferCompleteView', 'TransferCancelView', 'TransferStatusUpdateView',
         'TransferDeleteView', 'TransferHashUpdateView', 'TransferFailView',
         'TransferBatchPauseView', 'TransferBatchResumeView', 
         'TransferBatchCancelView', 'TransferBatchDeleteView'],
        []
    ),
]

def extract_class_content(content, class_name):
    """从内容中提取指定类的定义"""
    # 匹配类定义：class ClassName(View): ... 下一个类或文件结束
    pattern = rf'(^class {class_name}\(View\):.*?(?=\nclass |\Z))'
    match = re.search(pattern, content, re.MULTILINE | re.DOTALL)
    if match:
        return match.group(1)
    return None

def split_views():
    """执行拆分"""
    base_dir = 'e:/TDYW/spug-3.0/spug_api/apps/document'
    views_file = os.path.join(base_dir, 'views.py')
    views_dir = os.path.join(base_dir, 'views')
    
    # 读取原文件
    with open(views_file, 'r', encoding='utf-8') as f:
        content = f.read()
    
    print(f"原文件大小: {len(content)} 字符")
    print(f"开始拆分到: {views_dir}")
    
    # 提取公共头部（导入语句等）
    header_match = re.search(r'(^.*?)(?=^class \w+\(View\):)', content, re.MULTILINE | re.DOTALL)
    if not header_match:
        print("错误: 无法提取文件头部")
        return
    
    common_header = header_match.group(1)
    print(f"公共头部: {len(common_header)} 字符")
    
    # 为每个规则创建文件
    for filename, class_names, extra_imports in SPLIT_RULES:
        filepath = os.path.join(views_dir, filename)
        print(f"\n创建 {filename}...")
        
        # 构建文件内容
        file_content = common_header
        
        # 添加额外导入
        for imp in extra_imports:
            if imp not in file_content:
                file_content = f"import {imp}\n" + file_content
        
        # 提取每个类
        extracted_classes = []
        for class_name in class_names:
            class_content = extract_class_content(content, class_name)
            if class_content:
                extracted_classes.append(class_content)
                print(f"  [OK] 提取类: {class_name}")
            else:
                print(f"  [MISS] 未找到类: {class_name}")
        
        if extracted_classes:
            file_content += '\n\n'.join(extracted_classes)
            
            # 写入文件
            with open(filepath, 'w', encoding='utf-8') as f:
                f.write(file_content)
            print(f"  写入 {len(file_content)} 字符到 {filename}")
        else:
            print(f"  跳过 {filename} (无内容)")
    
    print("\n拆分完成!")
    print("请检查生成的文件，确认无误后可以将 views.py 备份并删除")

if __name__ == '__main__':
    # 先检查目录是否存在
    views_dir = 'e:/TDYW/spug-3.0/spug_api/apps/document/views'
    if not os.path.exists(views_dir):
        print(f"错误: 目录不存在 {views_dir}")
        print("请先创建 views 目录和 __init__.py、utils.py 文件")
        exit(1)
    
    # 执行拆分
    split_views()
