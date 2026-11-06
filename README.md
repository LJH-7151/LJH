# 溯证

溯证是本机企业资料库，用于保存文字资料、查找原文并核对来源。本分支提供资料导入与关键词检索功能。

## 功能介绍

### 资料导入与保存

导入 UTF-8 编码的 TXT、Markdown 文件，单个文件最大 2 MiB。系统保存原件和 SHA-256，并将文字按段落整理；资料索引存放在本机 SQLite 中，重启后可继续查看。

### 关键词检索

在全部资料或指定资料中搜索关键词。多个关键词必须同时出现在同一文字片段中；结果显示资料名称、命中摘要及来源位置，可打开原文继续核对。

### 原文与原件核对

查看资料全文片段、原始行号和文件信息，下载未经修改的原件，并使用 SHA-256 检查文件完整性。

当前分支不包含数据表统计、模型分析或报告导出。需要这些功能时，可查看 [分析工作台分支](https://github.com/LJH-7151/LJH/tree/feature/enterprise-workspace-redesign)，并以该分支的实际功能为准。

## 环境与启动

需要 Python 3.12 或更高版本，当前分支无需额外安装 Python 依赖。

```bash
python main.py --open
```

Windows 也可运行 `start.cmd`。默认地址为 `http://127.0.0.1:8765`。可以通过 `--port` 和 `--data-dir` 指定端口和数据目录；按 `Ctrl+C` 停止服务。

```bash
python main.py --port 8766 --data-dir ./data-local --open
```

服务只监听本机回环地址，默认数据保存在 `data/`。请自行备份资料，不要将运行数据提交到公开仓库。

## 测试

```bash
python -m unittest discover -s tests -v
```
