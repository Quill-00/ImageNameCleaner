# 大规模数据集重命名迁移到目标文件夹脚本（任何文件后缀可用）
**版本**：v1.0（2025-10-28）  
**开发人员**：QUILL  
**许可协议**：Apache-2.0 License

---

## 1) 项目目标与范围
- 解决跨多级子文件夹中**同名文件**集中到同一目标目录时的冲突；支持**任何文件后缀**（不限图片）。  
- 支持**一次输入多个源根目录**；可反复输入新目录，**回车空行结束**。  
- 统一按“文档顺序”（默认**自然排序**）重命名导出。  
- 支持**复制**（保留源）与**移动**（删除源）两种模式。  
- 尽力触发/刷新 Windows 缩略图；若不可行则**跳过**且不影响主流程。  
- 可在**大规模数据集（≥ 5 万文件）**下稳定运行。

---

## 2) 核心命名规则（模板 + 序号配置 + 扩展名）
**模板（Template）**
```
{parent}_{orig}_{seq}{ext}
```

**序号配置（SeqConfig）**
- `scope=per_parent`（**每个父级文件夹**内单独计数）  
- `start=1`（从 1 开始）  
- `width=auto`（自动位宽 = 当前父级文件总数的位数；如 7→1 位，12→2 位，120→3 位）  
- `pad_char=0`（按位宽用 0 补齐）

**扩展名规则（Extension）**
- `{ext}` 含“**点号 + 小写**扩展名”，例如 `.png`、`.jpg`、`.zip`。  
- 对源文件的扩展名只做**小写化**，不做格式转换（`.JPEG`→`.jpeg`；不把`.jpeg`改成`.jpg`）。  
- **无扩展名**文件：`{ext}` 为空字符串（不追加点号）。

**父级摘要（{parent}）**
- 取**父级文件夹名**，经安全化处理：保留中文与字母数字，非法字符替换为 `_`，默认长度 ≤ 12。  
- 可选：`parent.hash_suffix=true` 时追加短哈希 `-a1b2` 以避免不同路径但同名父级的冲突。  

**原名字段（{orig}）**
- 取原始文件名（不含扩展名），做安全化（同上）。  
- 过长可截断（默认 ≤ 32），并保持唯一性（必要时在尾部追加 `__trim{n}`）。  

**示例**
- 源：`...\A\1.PNG` → 目标：`A_1_01.png`  
- 源：`...\B\001.MyRAW` → 目标：`B_001_1.myraw`  
- 源：`...\A\日本风景.JPEG` → `A_日本风景_02.jpeg`

> 解析器也需支持等价的**内嵌参数写法**（供将来扩展）：  
> `{parent}_{orig}_{seq:width=auto,scope=per_parent,start=1}{ext}`

---

## 3) 功能模块
1. **多源输入与交互**
   - 支持**连续输入多个源根目录**；用户输入空行（直接回车）结束。  
   - 输入：①源目录（可多个）②目标目录 ③排序方式 ④操作模式（复制/移动）⑤干跑预览（y/N）⑥父级摘要策略（slug/原样/拼音）⑦是否追加短哈希 ⑧是否尝试刷新缩略图。  
   - 亦支持命令行参数直传（便于自动化）。

2. **扫描与过滤**
   - 递归扫描**所有文件**（不限后缀）；可选白名单/黑名单过滤（如只处理图片）。  
   - 跳过隐藏/系统文件、0 字节、无读权限项；支持 Windows 长路径（`\\?\` 前缀）。

3. **排序（“文档顺序”）**
   - 默认：**自然排序**（先父级相对路径自然排序，再文件名自然排序）。  
   - 备选：按修改时间/创建时间（升/降）。

4. **命名渲染与冲突处理**
   - 按模板渲染 `{parent}/{orig}/{seq}/{ext}`。  
   - 若目标重名：自动追加 `__dup{n}`。  
   - 可选**内容哈希去重**（保留首个或全部保留并加 `__dupContent{n}`）。

5. **导出与一致性保障**
   - **复制模式**：复制到目标，必要时做哈希校验后继续。  
   - **移动模式**：先复制并校验成功后**删除源文件**（安全搬运）。  
   - 目标目录不存在则创建；空间不足中止并列出清单。

6. **缩略图刷新（尽力尝试，失败不阻断）**
   - 方案 A：调用 Windows Shell 变更通知（如 `SHChangeNotify`）。  
   - 方案 B：更新文件时间戳（touch）。  
   - 方案 C（默认关闭，需确认）：清理 `%LocalAppData%\Microsoft\Windows\Explorer\thumbcache_*` 并重启 `explorer.exe`。  
   - 无法刷新时提示“手动刷新方法”。

7. **日志与回滚**
   - 生成 `report.csv`、`mapping.json`（`src_path → dst_path`、时间、模式、状态）。  
   - `failures.txt` 记录失败项。  
   - 回滚说明：移动模式可依据 `mapping.json` 逆向搬回（在源路径仍可写且目标仍在的前提下）。

8. **幂等性与断点续跑**
   - 多次运行不重复处理已成功项（基于 `mapping.json` 与目标存在性判断）。  
   - 中断后可继续。

9. **性能**
   - 大量文件批处理；多线程/多进程可配置（并发复制上限、I/O 限流）。  
   - 进度条与 ETA（可选 `tqdm`）。

---

## 4) 交互流程（CLI 文案示例）
1. 请输入**源根目录 #1**（回车结束输入）：  
2. 请输入**源根目录 #2**（可继续输入；直接回车结束）：  
3. 请输入**目标导出目录**（若不存在将创建）：  
4. 选择**排序**：`1 自然(默认) / 2 修改时间升 / 3 修改时间降 / 4 创建时间升 / 5 创建时间降`：  
5. 选择**操作**：`1 复制保留源(默认) / 2 移动并删除源`：  
6. **父级摘要**：`1 slug(默认) / 2 原样 / 3 拼音`：  
7. 是否为父级摘要追加短哈希避免碰撞？(y/N)：  
8. 使用命名模板 `{parent}_{orig}_{seq}{ext}` 并启用 `scope=per_parent,start=1,width=auto`？(Y/n)：  
   - 如 n，可输入自定义模板或序号策略（保持兼容字段）：  
9. 是否 **Dry-Run** 预览（不写入，仅输出清单）？(y/N)：  
10. 是否尝试**刷新缩略图**？(y/N)：  
11. 确认开始（回车执行 / `q` 取消）。

> 执行完成后自动打开目标目录，并输出：统计信息、失败计数、日志与回滚提示。

---

## 5) 配置项（`config.ini`，可选）
```
[general]
include_ext=              ; 允许留空表示处理所有文件类型；也可设为 .png,.jpg 等白名单
order=natural             ; natural|mtime_asc|mtime_desc|ctime_asc|ctime_desc
operation=copy            ; copy|move
dry_run=false

[naming]
template={parent}_{orig}_{seq}{ext}
seq_scope=per_parent      ; per_parent|global
seq_start=1
seq_width=auto            ; auto|1|2|3|...
seq_pad_char=0
parent_strategy=slug      ; slug|keep|pinyin
parent_hash_suffix=false
orig_maxlen=32
parent_maxlen=12

[thumbnail]
refresh=off               ; off|touch|shell|cache_clear_confirmed

[perf]
workers=8                 ; 并发度
hash_dedup=off            ; off|keep_first|suffix_all
hash_algo=md5             ; md5|sha1|xxh3 (若启用去重)
```

---

## 6) 失败与边界处理
- 非法/不可达路径、权限不足、只读卷、超长路径、Windows 保留名（`CON` 等）：跳过并记录。  
- 目标同名冲突自动加后缀 `__dup{n}`。  
- 断电/中断后可幂等重跑；遇到部分已存在项则跳过。  
- 无扩展名文件按无 `{ext}` 处理；隐藏文件可选是否纳入（默认跳过）。  
- 目标磁盘空间不足：中止并输出所需/剩余空间估算。

---

## 7) 测试用例（至少覆盖）
- **A 多源输入**：`A\1.png..100.png` 与 `B\1.png..100.png` → 目标名唯一，顺序正确。  
- **B 父级同名不同路径**：启用 `parent_hash_suffix=true` 后无冲突。  
- **C 任意后缀**：`.PNG .jpeg .ZIP .MyRAW（大小写混合、冷门后缀）` → 扩展名小写、保留原语义。  
- **D 无扩展名**：`file` → `A_file_01`（无点号）。  
- **E 干跑**：Dry-Run 输出与实跑一致；空间/权限预检查有效。  
- **F 复制 vs 移动**：移动后源确实删除且目标存在；复制不改源。  
- **G 大数据量**：≥5 万文件，进度可见，稳定完成。  
- **H 缩略图刷新**：`touch/shell` 可执行且失败不影响主流程。  
- **I 超长路径/中文路径/非法字符**：均被安全化处理并成功导出。

---

## 8) 打包与运行（内置 Python 与依赖）
- **首选**：使用 PyInstaller/Nuitka 打包为**单文件 EXE**（Win10+），内置运行时与依赖。  
- **备选**：项目附 `python-embed/`（内置 Python），`start.bat` 首次拉起自动 `pip install -r requirements.txt` 到私有目录后运行。  
- 依赖建议：`python-slugify`（可选，自写也行）、`tqdm`（可选），Windows API 调用通过 `ctypes` 或 `pywin32`（可选）。  
- 交付物：`ImageNameCleaner.exe` + `start.bat` + `LICENSE` +（可选）`config.ini`。

**启动脚本（start.bat）要求**
- `chcp 65001`，UTF-8 保存。  
- 自动检测 EXE 或内置 Python，择优运行主程序。  
- 执行后自动 `explorer` 打开目标目录；回显统计、失败数与日志路径。

---

## 9) 开源与署名
- **LICENSE 文件**：标准 **Apache-2.0** 文本置于项目根目录 `LICENSE`。  
- **源码文件头部版权声明（示例）**
```
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
```
- README 顶部展示：**研发者：QUILL｜License：Apache-2.0**。

---

## 10) 建议的项目结构
```
ImageNameCleaner/
  ├─ cleaner.py                # 主程序（实现本规格）
  ├─ start.bat                 # 双击启动
  ├─ config.ini                # 可选配置（覆盖交互输入）
  ├─ LICENSE                   # Apache-2.0
  ├─ README.md                 # 使用说明、CLI 示例、测试用例
  ├─ dist/ImageNameCleaner.exe # 打包产物（首选交付）
  └─ logs/
      ├─ report.csv
      ├─ mapping.json
      └─ failures.txt
```

---

### ✅ 验收清单（快速核对）
- [ ] 支持**多个源目录**输入，空行结束。  
- [ ] 目标命名遵循 `{parent}_{orig}_{seq}{ext}`，`seq` 为 **per_parent + auto 位宽**，`ext` 小写含点号。  
- [ ] 复制/移动两模式可选；移动模式安全搬运、校验后删除。  
- [ ] 排序默认自然排序并可改为时间序。  
- [ ] 任何后缀可用；无后缀文件可处理。  
- [ ] 日志与回滚信息完整；幂等、断点续跑。  
- [ ] 缩略图刷新“尽力而为”，失败不阻断、给出提示。  
- [ ] 大数据量性能达标、进度可见。  
- [ ] 项目包含**研发者 QUILL**署名与**Apache-2.0**协议。