# 溯证

溯证是本机企业资料库，用于保存文字资料、查找原文并核对来源。本分支提供资料导入与关键词检索功能。

## 功能

- 导入 UTF-8 编码的 TXT、Markdown 文件，单个文件最大 2 MiB。
- 浏览文字片段及原始行号，按关键词搜索全部资料或指定资料。
- 保存原始文件与 SHA-256，支持下载原件并核对完整性。
- 使用本机 SQLite 保存资料索引，重启后可继续使用。

当前分支不包含数据表统计、模型分析或报告导出。需要这些功能时，可查看 `feature/enterprise-workspace-redesign` 分支，并以该分支的实际功能为准。

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
