# 溯证

溯证是面向本机使用的企业资料与证据分析工具，可将文档和数据表中的信息与其原始来源关联，支持资料管理、检索、统计和分析报告。

本分支包含资料分析工作台。仓库默认的 `main` 分支目前是基础资料库，功能范围与本分支不同。

## 功能

- 导入 TXT、Markdown、DOCX、文本 PDF、CSV 和 XLSX；图片及扫描 PDF 可使用 Windows OCR，复核后加入资料库。
- 保留原件和来源位置，管理资料属性、版本与归档状态，通过关键词或本地语义索引检索。
- 对数据表进行筛选、分组和统计，查看来源行，并关联统计结果进行分析。
- 使用资料摘录、本地模型或 Codex 生成分析；模型引用会检查是否与本次证据原文一致。
- 保存分析档案和人工核对记录，导出 Word 分析报告、Excel 引用清单与统计结果。
- 导入订单和退款记录，生成可追溯的核算快照；支持下载资料备份。

## 环境与启动

需要 Python 3.12 或更高版本。文本 PDF 解析依赖 `requirements.txt`。

```bash
python -m pip install -r requirements.txt
python main.py --open
```

Windows 也可运行 `start.cmd`。默认访问地址为 `http://127.0.0.1:8765`。可通过 `--port` 和 `--data-dir` 指定端口与数据目录；按 `Ctrl+C` 停止服务。

```bash
python main.py --port 8766 --data-dir ./data-local --open
```

服务只监听本机回环地址，适用于单机使用。默认运行数据位于 `data/`，应自行备份，勿提交到公开仓库。

## 模型与语义检索

资料摘录和表格统计无需模型。本地模型辅助使用 `127.0.0.1:18770` 的兼容服务，本地语义检索使用 `127.0.0.1:18771` 的向量服务；需要自行提供对应模型和运行环境，仓库不包含模型权重。`requirements-model.txt` 和 `tools/serve_local_models.py` 可用于本地模型部署。

选择 Codex 智能分析时，需先安装并登录 Codex，在页面确认后，问题、所选资料的检索证据、数据表字段信息和统计结果会交由 Codex 处理；请根据资料权限选择使用方式。模型输出的引用会核验原文，但结论与建议仍需人工审阅。

## 演示与测试

可在新的空目录创建虚构演示资料：

```bash
python tools/create_demo.py ./demo-data
python main.py --data-dir ./demo-data --open
```

演示目录必须为空；示例数据仅用于功能体验，不代表真实企业数据。

运行自动测试：

```bash
python -m unittest discover -s tests -v
```

`tools/import_previous_workspace.py` 可将受支持的旧版工作空间迁入新的空目录，并保留旧数据库快照。迁移后应检查跳过的资料、统计记录及分析档案，再使用新工作空间。
