#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
简单测试脚本 - 验证Cleaner核心功能
版本：v1.0
开发人员：QUILL
许可协议：Apache-2.0 License
"""

import os
import tempfile
import shutil
from pathlib import Path
from cleaner import Config, FileScanner, NamingEngine, FileProcessor

def create_test_files():
    """创建测试文件结构"""
    # 创建临时目录
    test_dir = Path(tempfile.mkdtemp(prefix="cleaner_test_"))
    
    # 创建源目录结构
    source_dir = test_dir / "source"
    source_dir.mkdir()
    
    # 创建子目录和文件
    (source_dir / "照片").mkdir()
    (source_dir / "照片" / "IMG_001.jpg").write_text("fake image content")
    (source_dir / "照片" / "IMG_002.jpg").write_text("fake image content")
    (source_dir / "照片" / "DSC_001.jpg").write_text("fake image content")
    
    (source_dir / "文档").mkdir()
    (source_dir / "文档" / "report.pdf").write_text("fake pdf content")
    (source_dir / "文档" / "data.xlsx").write_text("fake excel content")
    
    # 创建目标目录
    target_dir = test_dir / "target"
    target_dir.mkdir()
    
    return str(source_dir), str(target_dir), str(test_dir)

def test_file_scanning():
    """测试文件扫描功能"""
    print("测试文件扫描功能...")
    
    source_dir, target_dir, test_dir = create_test_files()
    
    try:
        config = Config()
        scanner = FileScanner(config)
        
        files = scanner.scan_directories([source_dir])
        
        print(f"扫描到 {len(files)} 个文件:")
        for file_info in files:
            print(f"  - {file_info['filename']} (父级: {Path(file_info['parent_path']).name})")
        
        assert len(files) == 5, f"期望5个文件，实际{len(files)}个"
        print("✓ 文件扫描测试通过")
        
    finally:
        shutil.rmtree(test_dir)

def test_naming_engine():
    """测试命名引擎功能"""
    print("\n测试命名引擎功能...")
    
    source_dir, target_dir, test_dir = create_test_files()
    
    try:
        config = Config()
        scanner = FileScanner(config)
        naming_engine = NamingEngine(config.naming)
        
        files = scanner.scan_directories([source_dir])
        named_files = naming_engine.generate_names(files)
        
        print("生成的新文件名:")
        for file_info in named_files:
            print(f"  {file_info['filename']} -> {file_info['new_name']}")
        
        # 验证命名规则
        photo_files = [f for f in named_files if "照片" in f['new_name']]
        assert len(photo_files) == 3, "照片文件数量不正确"
        
        # 验证序号
        photo_names = [f['new_name'] for f in photo_files]
        assert any("_1." in name for name in photo_names), "序号1未找到"
        assert any("_2." in name for name in photo_names), "序号2未找到"
        assert any("_3." in name for name in photo_names), "序号3未找到"
        
        print("✓ 命名引擎测试通过")
        
    finally:
        shutil.rmtree(test_dir)

def test_dry_run():
    """测试干跑模式"""
    print("\n测试干跑模式...")
    
    source_dir, target_dir, test_dir = create_test_files()
    
    try:
        config = Config()
        config.dry_run = True
        
        scanner = FileScanner(config)
        naming_engine = NamingEngine(config.naming)
        processor = FileProcessor(config)
        
        files = scanner.scan_directories([source_dir])
        named_files = naming_engine.generate_names(files)
        result = processor.process_files(named_files, target_dir)
        
        print(f"干跑模式结果:")
        print(f"  - 预计成功: {result['success_count']} 个文件")
        print(f"  - 预计失败: {result['failed_count']} 个文件")
        
        # 验证目标目录为空（干跑模式不应创建文件）
        target_files = list(Path(target_dir).rglob("*"))
        target_files = [f for f in target_files if f.is_file()]
        assert len(target_files) == 0, f"干跑模式不应创建文件，但发现{len(target_files)}个文件"
        
        print("✓ 干跑模式测试通过")
        
    finally:
        shutil.rmtree(test_dir)

def main():
    """运行所有测试"""
    print("开始运行ImageNameCleaner功能测试...")
    print("=" * 50)
    
    try:
        test_file_scanning()
        test_naming_engine()
        test_dry_run()
        
        print("\n" + "=" * 50)
        print("✓ 所有测试通过！ImageNameCleaner功能正常")
        
    except Exception as e:
        print(f"\n✗ 测试失败: {e}")
        raise

if __name__ == "__main__":
    main()