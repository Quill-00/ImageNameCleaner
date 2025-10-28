# 图片名称清洗器：用户功能说明（简明版） / Image Name Cleaner: User Guide (Brief)
**版本/Version**：v1.0（2025-10-28）｜**开发人员/Author**：QUILL｜**License**：Apache-2.0

---

## 能做什么？ / What does it do?
把多个文件夹里的同名文件，重命名后**集中导出**到一个目标文件夹，**任何后缀都支持**。  
Collect files with duplicate names across multiple folders, rename them, and **export them into one target folder**. **Any file extension is supported.**

---

## 默认命名 / Default Naming
```
{parent}_{orig}_{seq}{ext}
```
- `{parent}` = 父级文件夹名（安全化）  
  `{parent}` = Parent folder name (sanitized)
- `{orig}` = 原文件名（不含后缀，安全化）  
  `{orig}` = Original filename without extension (sanitized)
- `{seq}` = 每个父级内从 1 开始连续编号，位宽自动  
  `{seq}` = Per-parent sequential number starting at 1, width auto-determined
- `{ext}` = 原后缀的小写，含点号（如 `.png`）；没有后缀就不加  
  `{ext}` = Lowercased original extension with dot (e.g., `.png`); omit if no extension

---

## 如何使用（最少 3 步） / How to Use (3 Steps)
1) **启动 / Launch**：双击 `start.bat`（或运行 `ImageNameCleaner.exe`）。  
   Double-click `start.bat` (or run `ImageNameCleaner.exe`).

2) **输入目录 / Enter Directories**：  
   - 依次输入**源根目录**（可输入多个），当你不再输入时**直接回车结束**；  
     Enter **source root directories** one by one (you can add multiple). **Press Enter on an empty line to finish**.  
   - 输入**目标目录**（不存在会自动创建）。  
     Enter the **target directory** (it will be created if missing).

3) **选择 / Choose Options**：  
   - 排序方式（默认“自然排序”）；  
     Sorting method (default: *natural*).  
   - 操作：`复制（保留源）` 或 `移动（删除源）`；  
     Operation: `Copy (keep source)` or `Move (delete source after verified copy)`.  
   - 是否 **Dry-Run** 预览；  
     Enable **Dry-Run** preview or not.  
   - 可选“尝试刷新缩略图”。  
     Optionally “try to refresh thumbnails”.

运行完成后会**自动打开目标目录**，并生成日志：`report.csv`、`mapping.json`、（失败项）`failures.txt`。  
After completion, the tool **opens the target folder** and generates logs: `report.csv`, `mapping.json`, and `failures.txt` (if any).

---

## 小提示 / Tips
- “移除模式”会在**复制并校验成功后**删除源文件，更安全。  
  In **Move** mode, sources are deleted **only after copy & verification**, which is safer.
- 如果缩略图没刷新，手动刷新或重启资源管理器即可。  
  If thumbnails don’t refresh, manually refresh or restart Windows Explorer.
- 支持超长/中文路径；非法字符会自动替换为 `_`。  
  Supports long/Unicode paths; illegal characters are auto-replaced with `_`.

就这些，开箱即用。需要更细设置请看开发规格文档。  
That’s it—ready to use. For advanced settings, see the developer spec.
