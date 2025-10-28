# Copyright (c) 2025 QUILL
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#     http://www.apache.org/licenses/LICENSE-2.0
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
#
# Author: QUILL

"""
大规模数据集重命名迁移到目标文件夹脚本（任何文件后缀可用）
版本：v1.0
开发人员：QUILL
许可协议：Apache-2.0 License
"""

import os
import sys
import re
import json
import csv
import hashlib
import shutil
import time
import argparse
import configparser
import logging
from datetime import datetime
from pathlib import Path
from typing import List, Dict, Tuple, Optional, Any
from dataclasses import dataclass, field
from concurrent.futures import ThreadPoolExecutor, as_completed
import threading
from collections import defaultdict

try:
    from tqdm import tqdm
    HAS_TQDM = True
except ImportError:
    HAS_TQDM = False
    
try:
    import slugify
    HAS_SLUGIFY = True
except ImportError:
    HAS_SLUGIFY = False

try:
    import ctypes
    from ctypes import wintypes
    import subprocess
    HAS_WINAPI = True
except ImportError:
    HAS_WINAPI = False


@dataclass
class SeqConfig:
    """序号配置"""
    scope: str = "per_parent"  # per_parent | global
    start: int = 1
    width: str = "auto"  # auto | 数字
    pad_char: str = "0"


@dataclass
class NamingConfig:
    """命名配置"""
    template: str = "{parent}_{orig}_{seq}{ext}"
    seq_config: SeqConfig = field(default_factory=SeqConfig)
    parent_strategy: str = "slug"  # slug | keep | pinyin
    parent_hash_suffix: bool = False
    orig_maxlen: int = 32
    parent_maxlen: int = 12


@dataclass
class Config:
    """全局配置"""
    # 通用设置
    include_ext: List[str] = field(default_factory=list)  # 空表示所有文件
    order: str = "natural"  # natural | mtime_asc | mtime_desc | ctime_asc | ctime_desc
    operation: str = "copy"  # copy | move
    dry_run: bool = False
    
    # 命名设置
    naming: NamingConfig = field(default_factory=NamingConfig)
    
    # 缩略图设置
    thumbnail_refresh: str = "off"  # off | touch | shell | cache_clear_confirmed
    
    # 性能设置
    workers: int = 8
    hash_dedup: str = "off"  # off | keep_first | suffix_all
    hash_algo: str = "md5"  # md5 | sha1


class FileScanner:
    """文件扫描器"""
    
    def __init__(self, config: Config):
        self.config = config
        
    def scan_directories(self, source_dirs: List[str]) -> List[Dict[str, Any]]:
        """扫描多个源目录，返回文件信息列表"""
        all_files = []
        
        for source_dir in source_dirs:
            if not os.path.exists(source_dir):
                print(f"警告：源目录不存在: {source_dir}")
                continue
                
            files = self._scan_single_directory(source_dir)
            all_files.extend(files)
            
        return self._sort_files(all_files)
    
    def _scan_single_directory(self, source_dir: str) -> List[Dict[str, Any]]:
        """扫描单个目录"""
        files = []
        source_path = Path(source_dir)
        
        try:
            for file_path in source_path.rglob("*"):
                if file_path.is_file():
                    # 跳过隐藏文件和系统文件
                    if file_path.name.startswith('.'):
                        continue
                        
                    # 检查文件大小
                    try:
                        if file_path.stat().st_size == 0:
                            continue
                    except (OSError, PermissionError):
                        continue
                    
                    # 检查扩展名过滤
                    if self.config.include_ext:
                        ext = file_path.suffix.lower()
                        if ext not in self.config.include_ext:
                            continue
                    
                    # 计算相对路径
                    try:
                        rel_path = file_path.relative_to(source_path)
                        parent_path = rel_path.parent
                        
                        file_info = {
                            'source_root': str(source_path),
                            'full_path': str(file_path),
                            'relative_path': str(rel_path),
                            'parent_path': str(parent_path),
                            'filename': file_path.name,
                            'stem': file_path.stem,
                            'suffix': file_path.suffix,
                            'size': file_path.stat().st_size,
                            'mtime': file_path.stat().st_mtime,
                            'ctime': file_path.stat().st_ctime,
                        }
                        files.append(file_info)
                        
                    except (OSError, PermissionError, ValueError) as e:
                        print(f"跳过文件 {file_path}: {e}")
                        continue
                        
        except (OSError, PermissionError) as e:
            print(f"扫描目录失败 {source_dir}: {e}")
            
        return files
    
    def _sort_files(self, files: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """排序文件列表"""
        if self.config.order == "natural":
            return sorted(files, key=lambda f: (self._natural_sort_key(f['parent_path']), 
                                              self._natural_sort_key(f['filename'])))
        elif self.config.order == "mtime_asc":
            return sorted(files, key=lambda f: f['mtime'])
        elif self.config.order == "mtime_desc":
            return sorted(files, key=lambda f: f['mtime'], reverse=True)
        elif self.config.order == "ctime_asc":
            return sorted(files, key=lambda f: f['ctime'])
        elif self.config.order == "ctime_desc":
            return sorted(files, key=lambda f: f['ctime'], reverse=True)
        else:
            return files
    
    def _natural_sort_key(self, text: str) -> List:
        """自然排序键"""
        def convert(text):
            return int(text) if text.isdigit() else text.lower()
        return [convert(c) for c in re.split('([0-9]+)', text)]


class NamingEngine:
    """命名引擎"""
    
    def __init__(self, config: NamingConfig):
        self.config = config
        self.parent_counters = defaultdict(int)
        self.global_counter = 0
        
    def generate_names(self, files: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """为文件列表生成新名称"""
        # 按父级分组统计，用于计算序号位宽
        parent_counts = defaultdict(int)
        for file_info in files:
            parent_key = self._get_parent_key(file_info)
            parent_counts[parent_key] += 1
        
        # 生成名称
        results = []
        for file_info in files:
            new_name = self._generate_single_name(file_info, parent_counts)
            file_info['new_name'] = new_name
            results.append(file_info)
            
        return results
    
    def _generate_single_name(self, file_info: Dict[str, Any], parent_counts: Dict[str, int]) -> str:
        """生成单个文件的新名称"""
        # 解析模板变量
        parent = self._process_parent(file_info)
        orig = self._process_orig(file_info)
        seq = self._process_seq(file_info, parent_counts)
        ext = self._process_ext(file_info)
        
        # 渲染模板
        template = self.config.template
        name = template.format(parent=parent, orig=orig, seq=seq, ext=ext)
        
        return self._sanitize_filename(name)
    
    def _get_parent_key(self, file_info: Dict[str, Any]) -> str:
        """获取父级键用于分组"""
        if self.config.parent_hash_suffix:
            # 包含路径哈希以区分同名但不同路径的父级
            parent_path = file_info['parent_path']
            path_hash = hashlib.md5(parent_path.encode('utf-8')).hexdigest()[:4]
            return f"{Path(parent_path).name}_{path_hash}"
        else:
            return Path(file_info['parent_path']).name or "root"
    
    def _process_parent(self, file_info: Dict[str, Any]) -> str:
        """处理父级名称"""
        parent_name = Path(file_info['parent_path']).name or "root"
        
        if self.config.parent_strategy == "slug" and HAS_SLUGIFY:
            parent = slugify.slugify(parent_name, separator='_')
        elif self.config.parent_strategy == "slug":
            # 简单的slug实现
            parent = re.sub(r'[^\w\u4e00-\u9fff]+', '_', parent_name)
        else:
            parent = parent_name
            
        # 截断长度
        if len(parent) > self.config.parent_maxlen:
            parent = parent[:self.config.parent_maxlen]
            
        # 添加哈希后缀
        if self.config.parent_hash_suffix:
            parent_path = file_info['parent_path']
            path_hash = hashlib.md5(parent_path.encode('utf-8')).hexdigest()[:4]
            parent = f"{parent}-{path_hash}"
            
        return parent or "unknown"
    
    def _process_orig(self, file_info: Dict[str, Any]) -> str:
        """处理原始文件名"""
        orig = file_info['stem']
        
        # 安全化处理
        orig = re.sub(r'[^\w\u4e00-\u9fff]+', '_', orig)
        
        # 截断长度
        if len(orig) > self.config.orig_maxlen:
            orig = orig[:self.config.orig_maxlen]
            
        return orig or "unnamed"
    
    def _process_seq(self, file_info: Dict[str, Any], parent_counts: Dict[str, int]) -> str:
        """处理序号"""
        seq_config = self.config.seq_config
        
        if seq_config.scope == "per_parent":
            parent_key = self._get_parent_key(file_info)
            self.parent_counters[parent_key] += 1
            seq_num = self.parent_counters[parent_key] + seq_config.start - 1
            
            # 计算位宽
            if seq_config.width == "auto":
                total_count = parent_counts[parent_key]
                width = len(str(total_count))
            else:
                width = int(seq_config.width)
        else:
            # global scope
            self.global_counter += 1
            seq_num = self.global_counter + seq_config.start - 1
            
            if seq_config.width == "auto":
                total_count = sum(parent_counts.values())
                width = len(str(total_count))
            else:
                width = int(seq_config.width)
        
        return str(seq_num).zfill(width)
    
    def _process_ext(self, file_info: Dict[str, Any]) -> str:
        """处理扩展名"""
        ext = file_info['suffix']
        return ext.lower() if ext else ""
    
    def _sanitize_filename(self, filename: str) -> str:
        """文件名安全化"""
        # Windows保留字符
        filename = re.sub(r'[<>:"/\\|?*]', '_', filename)
        
        # Windows保留名称
        reserved_names = {'CON', 'PRN', 'AUX', 'NUL', 'COM1', 'COM2', 'COM3', 'COM4', 
                         'COM5', 'COM6', 'COM7', 'COM8', 'COM9', 'LPT1', 'LPT2', 
                         'LPT3', 'LPT4', 'LPT5', 'LPT6', 'LPT7', 'LPT8', 'LPT9'}
        
        name_part = filename.split('.')[0].upper()
        if name_part in reserved_names:
            filename = f"_{filename}"
            
        # 去除首尾空格和点号
        filename = filename.strip(' .')
        
        return filename or "unnamed"


class LogManager:
    """日志管理器"""
    
    def __init__(self, target_dir: str):
        self.target_dir = Path(target_dir)
        self.logs_dir = self.target_dir / "logs"
        self.logs_dir.mkdir(parents=True, exist_ok=True)
        
        # 日志文件路径
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        self.report_file = self.logs_dir / f"report_{timestamp}.csv"
        self.mapping_file = self.logs_dir / f"mapping_{timestamp}.json"
        self.failures_file = self.logs_dir / f"failures_{timestamp}.txt"
        
        # 设置日志记录器
        self.logger = logging.getLogger('ImageNameCleaner')
        self.logger.setLevel(logging.INFO)
        
        # 文件处理器
        log_file = self.logs_dir / f"cleaner_{timestamp}.log"
        file_handler = logging.FileHandler(log_file, encoding='utf-8')
        file_handler.setLevel(logging.INFO)
        
        # 控制台处理器
        console_handler = logging.StreamHandler()
        console_handler.setLevel(logging.INFO)
        
        # 格式化器
        formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
        file_handler.setFormatter(formatter)
        console_handler.setFormatter(formatter)
        
        self.logger.addHandler(file_handler)
        self.logger.addHandler(console_handler)
        
        # 映射数据
        self.mapping_data = {}
        
    def log_operation(self, file_info: Dict[str, Any], success: bool, error: str = ""):
        """记录操作日志"""
        operation_id = f"{file_info['source_root']}::{file_info['relative_path']}"
        
        self.mapping_data[operation_id] = {
            'source_path': file_info['full_path'],
            'target_path': file_info.get('target_path', ''),
            'operation': file_info.get('operation', ''),
            'timestamp': file_info.get('timestamp', time.time()),
            'success': success,
            'error': error,
            'file_size': file_info['size'],
            'new_name': file_info['new_name']
        }
        
        if success:
            self.logger.info(f"成功 {file_info.get('operation', 'copy')}: {file_info['filename']} -> {file_info['new_name']}")
        else:
            self.logger.error(f"失败 {file_info.get('operation', 'copy')}: {file_info['filename']} - {error}")
    
    def save_logs(self, processed_files: List[Dict[str, Any]], failed_files: List[Dict[str, Any]]):
        """保存日志文件"""
        # 保存映射文件
        with open(self.mapping_file, 'w', encoding='utf-8') as f:
            json.dump(self.mapping_data, f, ensure_ascii=False, indent=2)
        
        # 保存报告CSV
        with open(self.report_file, 'w', newline='', encoding='utf-8-sig') as f:
            writer = csv.writer(f)
            writer.writerow(['源文件路径', '目标文件路径', '新文件名', '操作类型', '文件大小', '处理时间', '状态'])
            
            for file_info in processed_files:
                writer.writerow([
                    file_info['full_path'],
                    file_info.get('target_path', ''),
                    file_info['new_name'],
                    file_info.get('operation', ''),
                    file_info['size'],
                    datetime.fromtimestamp(file_info.get('timestamp', 0)).strftime('%Y-%m-%d %H:%M:%S'),
                    '成功'
                ])
            
            for failed_info in failed_files:
                file_info = failed_info['file_info']
                writer.writerow([
                    file_info['full_path'],
                    '',
                    file_info['new_name'],
                    file_info.get('operation', ''),
                    file_info['size'],
                    datetime.fromtimestamp(failed_info.get('timestamp', 0)).strftime('%Y-%m-%d %H:%M:%S'),
                    f"失败: {failed_info.get('error', '')}"
                ])
        
        # 保存失败文件列表
        if failed_files:
            with open(self.failures_file, 'w', encoding='utf-8') as f:
                f.write(f"处理失败的文件列表 - {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
                f.write("=" * 60 + "\n\n")
                
                for failed_info in failed_files:
                    file_info = failed_info['file_info']
                    f.write(f"文件: {file_info['full_path']}\n")
                    f.write(f"目标名称: {file_info['new_name']}\n")
                    f.write(f"错误: {failed_info.get('error', '')}\n")
                    f.write(f"时间: {datetime.fromtimestamp(failed_info.get('timestamp', 0)).strftime('%Y-%m-%d %H:%M:%S')}\n")
                    f.write("-" * 40 + "\n")
        
        self.logger.info(f"日志已保存到: {self.logs_dir}")
        return {
            'report_file': str(self.report_file),
            'mapping_file': str(self.mapping_file),
            'failures_file': str(self.failures_file) if failed_files else None
        }
    
    def load_previous_mapping(self) -> Dict[str, Any]:
        """加载之前的映射数据（用于幂等性）"""
        mapping_files = list(self.logs_dir.glob("mapping_*.json"))
        if not mapping_files:
            return {}
        
        # 使用最新的映射文件
        latest_mapping = max(mapping_files, key=lambda f: f.stat().st_mtime)
        
        try:
            with open(latest_mapping, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception as e:
            self.logger.warning(f"无法加载之前的映射文件 {latest_mapping}: {e}")
            return {}


class RollbackManager:
    """回滚管理器"""
    
    def __init__(self, mapping_file: str):
        self.mapping_file = Path(mapping_file)
        
    def can_rollback(self) -> bool:
        """检查是否可以回滚"""
        return self.mapping_file.exists()
    
    def rollback_operations(self) -> Dict[str, Any]:
        """执行回滚操作"""
        if not self.can_rollback():
            return {'success': False, 'error': '映射文件不存在'}
        
        try:
            with open(self.mapping_file, 'r', encoding='utf-8') as f:
                mapping_data = json.load(f)
        except Exception as e:
            return {'success': False, 'error': f'无法读取映射文件: {e}'}
        
        success_count = 0
        failed_count = 0
        errors = []
        
        for operation_id, operation_data in mapping_data.items():
            if not operation_data['success']:
                continue  # 跳过之前失败的操作
            
            source_path = Path(operation_data['source_path'])
            target_path = Path(operation_data['target_path'])
            operation = operation_data['operation']
            
            try:
                if operation == 'move' and target_path.exists():
                    # 移动操作的回滚：从目标移回源
                    if not source_path.parent.exists():
                        source_path.parent.mkdir(parents=True, exist_ok=True)
                    
                    shutil.move(str(target_path), str(source_path))
                    success_count += 1
                    
                elif operation == 'copy' and target_path.exists():
                    # 复制操作的回滚：删除目标文件
                    target_path.unlink()
                    success_count += 1
                    
            except Exception as e:
                failed_count += 1
                errors.append(f"{operation_id}: {e}")
        
        return {
             'success': True,
             'success_count': success_count,
             'failed_count': failed_count,
             'errors': errors
         }


class ThumbnailRefresher:
    """缩略图刷新器"""
    
    def __init__(self, config: Config):
        self.config = config
        self.logger = logging.getLogger('ImageNameCleaner.Thumbnail')
        
    def refresh_thumbnails(self, target_dir: str, processed_files: List[Dict[str, Any]]) -> bool:
        """刷新缩略图"""
        if self.config.thumbnail_refresh == "off":
            return True
            
        try:
            if self.config.thumbnail_refresh == "touch":
                return self._refresh_by_touch(target_dir, processed_files)
            elif self.config.thumbnail_refresh == "shell":
                return self._refresh_by_shell_notify(target_dir)
            elif self.config.thumbnail_refresh == "cache_clear_confirmed":
                return self._refresh_by_cache_clear(target_dir)
            else:
                return True
                
        except Exception as e:
            self.logger.warning(f"缩略图刷新失败: {e}")
            self._show_manual_refresh_tips(target_dir)
            return False
    
    def _refresh_by_touch(self, target_dir: str, processed_files: List[Dict[str, Any]]) -> bool:
        """通过更新时间戳刷新缩略图"""
        try:
            current_time = time.time()
            success_count = 0
            
            for file_info in processed_files:
                target_path = file_info.get('target_path')
                if target_path and os.path.exists(target_path):
                    try:
                        os.utime(target_path, (current_time, current_time))
                        success_count += 1
                    except Exception as e:
                        self.logger.debug(f"无法更新文件时间戳 {target_path}: {e}")
            
            self.logger.info(f"已更新 {success_count} 个文件的时间戳")
            return True
            
        except Exception as e:
            self.logger.error(f"时间戳刷新失败: {e}")
            return False
    
    def _refresh_by_shell_notify(self, target_dir: str) -> bool:
        """通过Windows Shell通知刷新缩略图"""
        if not HAS_WINAPI:
            self.logger.warning("Windows API不可用，无法使用Shell通知刷新")
            return False
            
        try:
            # 定义Windows API常量
            SHCNE_UPDATEDIR = 0x00001000
            SHCNF_PATH = 0x0001
            
            # 加载Shell32.dll
            shell32 = ctypes.windll.shell32
            
            # 调用SHChangeNotify
            shell32.SHChangeNotifyW(
                SHCNE_UPDATEDIR,
                SHCNF_PATH,
                ctypes.c_wchar_p(target_dir),
                None
            )
            
            self.logger.info(f"已发送Shell通知刷新目录: {target_dir}")
            return True
            
        except Exception as e:
            self.logger.error(f"Shell通知刷新失败: {e}")
            return False
    
    def _refresh_by_cache_clear(self, target_dir: str) -> bool:
        """通过清理缩略图缓存刷新（需要确认）"""
        try:
            # 获取缩略图缓存目录
            cache_dir = os.path.expandvars(r"%LocalAppData%\Microsoft\Windows\Explorer")
            
            if not os.path.exists(cache_dir):
                self.logger.warning("缩略图缓存目录不存在")
                return False
            
            # 查找缩略图缓存文件
            cache_files = []
            for file in os.listdir(cache_dir):
                if file.startswith("thumbcache_") and file.endswith(".db"):
                    cache_files.append(os.path.join(cache_dir, file))
            
            if not cache_files:
                self.logger.info("未找到缩略图缓存文件")
                return True
            
            # 尝试删除缓存文件
            deleted_count = 0
            for cache_file in cache_files:
                try:
                    os.remove(cache_file)
                    deleted_count += 1
                except Exception as e:
                    self.logger.debug(f"无法删除缓存文件 {cache_file}: {e}")
            
            if deleted_count > 0:
                self.logger.info(f"已删除 {deleted_count} 个缩略图缓存文件")
                
                # 尝试重启explorer.exe
                try:
                    subprocess.run(["taskkill", "/f", "/im", "explorer.exe"], 
                                 capture_output=True, check=False)
                    time.sleep(1)
                    subprocess.Popen(["explorer.exe"])
                    self.logger.info("已重启Windows资源管理器")
                except Exception as e:
                    self.logger.warning(f"重启资源管理器失败: {e}")
            
            return True
            
        except Exception as e:
            self.logger.error(f"缓存清理刷新失败: {e}")
            return False

    def _show_manual_refresh_tips(self, target_dir: str):
        """显示手动刷新提示"""
        tips = f"""
缩略图自动刷新失败，您可以尝试以下手动方法：

1. 在文件资源管理器中按 F5 刷新目录
2. 切换视图模式（列表 -> 大图标 -> 列表）
3. 重启Windows资源管理器：
   - 按 Ctrl+Shift+Esc 打开任务管理器
   - 找到"Windows资源管理器"进程
   - 右键选择"重新启动"

目标目录: {target_dir}
"""
        print(tips)
        self.logger.info("已显示手动刷新缩略图的提示")


class FileProcessor:
    """文件处理器"""
    
    def __init__(self, config: Config):
        self.config = config
        self.processed_files = []
        self.failed_files = []
        self.lock = threading.Lock()
        self.log_manager = None
        
    def process_files(self, files: List[Dict[str, Any]], target_dir: str) -> Dict[str, Any]:
        """处理文件列表"""
        target_path = Path(target_dir)
        
        # 创建目标目录和日志管理器
        if not self.config.dry_run:
            target_path.mkdir(parents=True, exist_ok=True)
            self.log_manager = LogManager(target_dir)
            
            # 加载之前的映射数据（幂等性支持）
            previous_mapping = self.log_manager.load_previous_mapping()
            files = self._filter_processed_files(files, previous_mapping, target_path)
        
        # 处理重名冲突
        files = self._resolve_conflicts(files, target_path)
        
        # 执行处理
        if self.config.dry_run:
            return self._dry_run(files, target_path)
        else:
            result = self._execute_operations(files, target_path)
            
            # 保存日志
            if self.log_manager:
                log_files = self.log_manager.save_logs(self.processed_files, self.failed_files)
                result['log_files'] = log_files
            
            # 刷新缩略图
            if self.processed_files:
                thumbnail_refresher = ThumbnailRefresher(self.config)
                thumbnail_refresher.refresh_thumbnails(target_dir, self.processed_files)
                
            return result

    def delete_source_files(self, processed_files: List[Dict[str, Any]]) -> Dict[str, int]:
        """在确认后删除成功复制的源文件（仅在复制模式）"""
        if self.config.operation != "copy":
            return {"deleted": 0, "failed": 0}
        deleted = 0
        failed = 0
        for fi in processed_files:
            src = fi.get('full_path')
            tgt = fi.get('target_path')
            try:
                if src and tgt and os.path.exists(tgt) and os.path.exists(src):
                    os.unlink(src)
                    deleted += 1
            except Exception:
                failed += 1
        if self.log_manager:
            self.log_manager.logger.info(f"删除源文件完成：成功 {deleted}，失败 {failed}")
        return {"deleted": deleted, "failed": failed}
    
    def _resolve_conflicts(self, files: List[Dict[str, Any]], target_path: Path) -> List[Dict[str, Any]]:
        """解决文件名冲突"""
        name_counts = defaultdict(int)
        
        for file_info in files:
            original_name = file_info['new_name']
            name_counts[original_name] += 1
            
            if name_counts[original_name] > 1:
                # 添加重复后缀
                name_parts = original_name.rsplit('.', 1)
                if len(name_parts) == 2:
                    base_name, ext = name_parts
                    new_name = f"{base_name}__dup{name_counts[original_name] - 1}.{ext}"
                else:
                    new_name = f"{original_name}__dup{name_counts[original_name] - 1}"
                    
                file_info['new_name'] = new_name
                name_counts[new_name] = 1  # 重置计数
                
        return files
    
    def _filter_processed_files(self, files: List[Dict[str, Any]], previous_mapping: Dict[str, Any], target_path: Path) -> List[Dict[str, Any]]:
        """过滤已处理的文件（幂等性支持）"""
        if not previous_mapping:
            return files
        
        filtered_files = []
        skipped_count = 0
        
        for file_info in files:
            operation_id = f"{file_info['source_root']}::{file_info['relative_path']}"
            
            # 检查是否已经处理过
            if operation_id in previous_mapping:
                prev_data = previous_mapping[operation_id]
                target_file = Path(prev_data.get('target_path', ''))
                
                # 如果目标文件存在且之前处理成功，跳过
                if prev_data.get('success', False) and target_file.exists():
                    skipped_count += 1
                    if self.log_manager:
                        self.log_manager.logger.info(f"跳过已处理文件: {file_info['filename']}")
                    continue
            
            filtered_files.append(file_info)
        
        if skipped_count > 0 and self.log_manager:
            self.log_manager.logger.info(f"跳过了 {skipped_count} 个已处理的文件")
        
        return filtered_files
    
    def _dry_run(self, files: List[Dict[str, Any]], target_path: Path) -> Dict[str, Any]:
        """干跑模式"""
        print(f"\n=== 干跑模式预览 ===")
        print(f"目标目录: {target_path}")
        print(f"操作模式: {self.config.operation}")
        print(f"文件总数: {len(files)}")
        print()
        
        for i, file_info in enumerate(files[:10]):  # 只显示前10个
            print(f"{i+1:3d}. {file_info['filename']} -> {file_info['new_name']}")
            
        if len(files) > 10:
            print(f"... 还有 {len(files) - 10} 个文件")
            
        return {
            'success_count': len(files),
            'failed_count': 0,
            'total_size': sum(f['size'] for f in files),
            'processed_files': files,
            'failed_files': []
        }
    
    def _execute_operations(self, files: List[Dict[str, Any]], target_path: Path) -> Dict[str, Any]:
        """执行实际操作"""
        progress_desc = f"{'移动' if self.config.operation == 'move' else '复制'}文件"
        
        if HAS_TQDM:
            progress_bar = tqdm(total=len(files), desc=progress_desc, unit="文件")
        else:
            progress_bar = None
            
        try:
            with ThreadPoolExecutor(max_workers=self.config.workers) as executor:
                futures = []
                
                for file_info in files:
                    future = executor.submit(self._process_single_file, file_info, target_path)
                    futures.append(future)
                
                for future in as_completed(futures):
                    try:
                        result = future.result()
                        with self.lock:
                            if result['success']:
                                self.processed_files.append(result['file_info'])
                                if self.log_manager:
                                    self.log_manager.log_operation(result['file_info'], True)
                            else:
                                self.failed_files.append(result)
                                if self.log_manager:
                                    self.log_manager.log_operation(result['file_info'], False, result.get('error', ''))
                                
                        if progress_bar:
                            progress_bar.update(1)
                            
                    except Exception as e:
                        print(f"处理文件时发生错误: {e}")
                        
        finally:
            if progress_bar:
                progress_bar.close()
        
        return {
            'success_count': len(self.processed_files),
            'failed_count': len(self.failed_files),
            'total_size': sum(f['size'] for f in self.processed_files),
            'processed_files': self.processed_files,
            'failed_files': self.failed_files
        }
    
    def _process_single_file(self, file_info: Dict[str, Any], target_path: Path) -> Dict[str, Any]:
        """处理单个文件"""
        source_file = Path(file_info['full_path'])
        target_file = target_path / file_info['new_name']
        
        try:
            if self.config.operation == "copy":
                shutil.copy2(source_file, target_file)
            else:  # move
                # 安全移动：先复制再删除
                shutil.copy2(source_file, target_file)
                
                # 验证复制成功
                if self._verify_file_integrity(source_file, target_file):
                    source_file.unlink()
                else:
                    target_file.unlink()  # 删除失败的副本
                    raise Exception("文件完整性验证失败")
            
            file_info['target_path'] = str(target_file)
            file_info['operation'] = self.config.operation
            file_info['timestamp'] = time.time()
            
            return {'success': True, 'file_info': file_info}
            
        except Exception as e:
            return {
                'success': False,
                'file_info': file_info,
                'error': str(e),
                'timestamp': time.time()
            }
    
    def _verify_file_integrity(self, source_file: Path, target_file: Path) -> bool:
        """验证文件完整性"""
        try:
            return (source_file.stat().st_size == target_file.stat().st_size and
                    self._calculate_hash(source_file) == self._calculate_hash(target_file))
        except Exception:
            return False
    
    def _calculate_hash(self, file_path: Path) -> str:
        """计算文件哈希"""
        hash_obj = hashlib.md5()
        
        try:
            with open(file_path, 'rb') as f:
                for chunk in iter(lambda: f.read(8192), b""):
                    hash_obj.update(chunk)
            return hash_obj.hexdigest()
        except Exception:
            return ""


def load_config(config_file: str = "config.ini") -> Config:
    """加载配置文件"""
    config = Config()
    
    if os.path.exists(config_file):
        parser = configparser.ConfigParser()
        parser.read(config_file, encoding='utf-8')
        
        # 通用设置
        if parser.has_section('general'):
            section = parser['general']
            if section.get('include_ext'):
                config.include_ext = [ext.strip() for ext in section.get('include_ext').split(',')]
            config.order = section.get('order', config.order)
            config.operation = section.get('operation', config.operation)
            config.dry_run = section.getboolean('dry_run', config.dry_run)
        
        # 命名设置
        if parser.has_section('naming'):
            section = parser['naming']
            config.naming.template = section.get('template', config.naming.template)
            config.naming.seq_config.scope = section.get('seq_scope', config.naming.seq_config.scope)
            config.naming.seq_config.start = section.getint('seq_start', config.naming.seq_config.start)
            config.naming.seq_config.width = section.get('seq_width', config.naming.seq_config.width)
            config.naming.parent_strategy = section.get('parent_strategy', config.naming.parent_strategy)
            config.naming.parent_hash_suffix = section.getboolean('parent_hash_suffix', config.naming.parent_hash_suffix)
            config.naming.orig_maxlen = section.getint('orig_maxlen', config.naming.orig_maxlen)
            config.naming.parent_maxlen = section.getint('parent_maxlen', config.naming.parent_maxlen)
        
        # 缩略图设置
        if parser.has_section('thumbnail'):
            section = parser['thumbnail']
            config.thumbnail_refresh = section.get('refresh', config.thumbnail_refresh)
        
        # 性能设置
        if parser.has_section('perf'):
            section = parser['perf']
            config.workers = section.getint('workers', config.workers)
            config.hash_dedup = section.get('hash_dedup', config.hash_dedup)
            config.hash_algo = section.get('hash_algo', config.hash_algo)
    
    return config


def main():
    """主函数"""
    print("大规模数据集重命名迁移工具 v1.0")
    print("研发者：QUILL | 许可协议：Apache-2.0")
    print("=" * 50)
    
    # 加载配置
    config = load_config()
    
    # 解析命令行参数
    parser = argparse.ArgumentParser(description="文件重命名迁移工具")
    parser.add_argument('--sources', nargs='+', help='源目录列表')
    parser.add_argument('--target', help='目标目录')
    parser.add_argument('--dry-run', action='store_true', help='干跑模式')
    parser.add_argument('--operation', choices=['copy', 'move'], help='操作模式')
    
    args = parser.parse_args()
    
    # 交互式输入或使用命令行参数
    if args.sources and args.target:
        source_dirs = args.sources
        target_dir = args.target
        if args.dry_run:
            config.dry_run = True
        if args.operation:
            config.operation = args.operation
    else:
        # 交互式输入
        source_dirs = []
        print("\n请输入源根目录（可输入多个，空行结束）：")
        while True:
            source = input(f"源根目录 #{len(source_dirs) + 1}（回车结束）: ").strip()
            if not source:
                break
            if os.path.exists(source):
                source_dirs.append(source)
                print(f"已添加: {source}")
            else:
                print(f"目录不存在: {source}")
        
        if not source_dirs:
            print("未指定有效的源目录，退出。")
            return
        
        target_dir = input("\n请输入目标导出目录: ").strip()
        if not target_dir:
            print("未指定目标目录，退出。")
            return
    
    try:
        # 扫描文件
        print(f"\n正在扫描 {len(source_dirs)} 个源目录...")
        scanner = FileScanner(config)
        files = scanner.scan_directories(source_dirs)
        
        if not files:
            print("未找到任何文件。")
            return
        
        print(f"找到 {len(files)} 个文件")
        
        # 生成新名称
        print("正在生成新文件名...")
        naming_engine = NamingEngine(config.naming)
        files = naming_engine.generate_names(files)
        
        # 处理文件
        processor = FileProcessor(config)
        result = processor.process_files(files, target_dir)
        
        # 输出结果
        print(f"\n处理完成！")
        print(f"成功: {result['success_count']} 个文件")
        print(f"失败: {result['failed_count']} 个文件")
        print(f"总大小: {result['total_size'] / (1024*1024):.2f} MB")
        
        if result['failed_count'] > 0:
            print(f"\n失败的文件:")
            for failed in result['failed_files'][:5]:
                print(f"  {failed['file_info']['filename']}: {failed['error']}")
            if len(result['failed_files']) > 5:
                print(f"  ... 还有 {len(result['failed_files']) - 5} 个失败文件")
        
        # 打开目标目录
        if not config.dry_run and os.path.exists(target_dir):
            try:
                os.startfile(target_dir)
            except Exception:
                print(f"请手动打开目标目录: {target_dir}")

        # 询问是否删除源文件（仅复制模式且非干跑）
        if not config.dry_run and config.operation == "copy" and result.get('processed_files'):
            try:
                ans = input("\n是否删除源目录中的原文件？输入 y 删除，其他键跳过: ").strip().lower()
                if ans == 'y':
                    del_res = processor.delete_source_files(result['processed_files'])
                    print(f"已删除源文件: {del_res['deleted']} 个，失败: {del_res['failed']} 个")
            except Exception as e:
                print(f"删除源文件步骤发生错误: {e}")

        
    except KeyboardInterrupt:
        print("\n\n操作被用户中断。")
    except Exception as e:
        print(f"\n发生错误: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    main()