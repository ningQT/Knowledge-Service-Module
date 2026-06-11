<div align="center">

# KSM — 知识服务模块

**面向 AI 业务系统的本地知识基础设施，基于 Obsidian Vault 标准。**

[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)
[![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.115-green.svg)](https://fastapi.tiangolo.com/)
[![React 19](https://img.shields.io/badge/React-19-61DAFB.svg)](https://react.dev/)

[English](README.md) | [中文](README.zh-CN.md)

</div>

---

## 什么是 KSM？

KSM 是一个面向 AI 业务系统的本地知识服务模块。系统以 Obsidian Vault 为底层知识载体，通过标准目录、frontmatter 元数据、Wikilinks 和 SQLite 索引，把原始资料加工成可追溯、可检索、可组织的结构化知识节点。

### 核心能力

| 能力 | 说明 |
|------|------|
| **实例管理** | 创建和管理隔离的知识库实例，生成标准 vault 目录结构 |
| **知识写入** | 将 Markdown 文档加工为资料来源、知识卡片和知识地图 |
| **异步入库** | SSE 驱动的 8 步管线，支持实时进度追踪 |
| **关系组织** | 解析和索引知识关系（source_trace、extracted_from、concept_overlap 等） |
| **结构化检索** | 基于意图的检索，返回 core_hits、related_cards、source_notes 和 maps |
| **知识图谱** | 基于 React Flow 的交互式可视化，支持三层筛选 |
| **Web 控制台** | 浏览器管理界面，包含仪表盘、图谱、入库、检索、笔记详情和设置 |
| **本地优先** | 数据存储在本地文件系统和 SQLite，便于调试、迁移和人工审阅 |

### 技术栈

| 层级 | 技术 |
|------|------|
| **后端** | Python 3.11+ / FastAPI / SQLite (FTS5) / 本地文件系统 |
| **前端** | React 19 / TypeScript / Vite / Tailwind CSS / shadcn/ui / Zustand / React Flow |

---

## 快速开始

### 前置要求

- Python 3.11+
- Node.js 18+
- LLM API Key（OpenAI、Anthropic 或兼容服务）

### 1. 克隆并配置后端

```bash
git clone https://github.com/yourname/ksm.git
cd ksm

python -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate

pip install -r requirements.txt
```

### 2. 启动后端

```bash
uvicorn app.api.app:create_app --factory --host 127.0.0.1 --port 8900
```

### 3. 配置 LLM

打开 http://127.0.0.1:8900/settings，在 Web 控制台中配置 LLM 提供商（API Key、模型、端点）。

### 4. 启动前端

```bash
cd frontend
npm install
npm run dev
```

打开 http://localhost:5173

---

## Docker 部署

```bash
docker compose up -d --build
```

生产环境配置、备份和回滚请参阅 [docs/production-deployment.md](docs/production-deployment.md)。

---

## API 概览

| 分类 | 端点 |
|------|------|
| **实例管理** | `POST/GET /api/v1/instances` |
| **文档入库** | `POST /api/v1/instances/{id}/ingest[/async]` |
| **知识检索** | `POST /api/v1/search` |
| **知识图谱** | `GET /api/v1/instances/{id}/graph` |
| **系统设置** | `GET/PUT /api/v1/settings/llm` |

运行时交互式文档：http://127.0.0.1:8900/docs

---

## Web 控制台

| 页面 | 路径 | 说明 |
|------|------|------|
| 仪表盘 | `/` | 实例列表与统计 |
| 图谱视图 | `/graph` | 知识图谱可视化 |
| 入库 | `/ingest` | 文档上传，SSE 实时进度 |
| 检索 | `/search` | 结构化知识检索 |
| 笔记详情 | `/note/:path` | Markdown 渲染与元数据 |
| 设置 | `/settings` | LLM 配置管理 |

支持亮色/暗色主题。

---

## 配置

LLM 设置通过 Web 控制台 `/settings` 页面管理，存储在数据库中。

主要环境变量：

| 变量 | 必填 | 默认值 | 说明 |
|------|------|--------|------|
| `KSM_DATA_DIR` | 否 | `./data/vaults` | 数据存储目录 |
| `KSM_PORT` | 否 | `8900` | HTTP 端口 |
| `KSM_ENABLE_DOCS` | 否 | `true` | 启用 `/docs` 端点 |

完整列表见 [docs/production-deployment.md](docs/production-deployment.md)。

---

## 测试

```bash
# 全量测试
python -m pytest -q

# 单元测试
pytest tests/unit/ -v

# 集成测试
pytest tests/integration/ -v

# 带覆盖率
pytest tests/ --cov=app --cov-report=term-missing
```

---

## 项目结构

```
ksm/
├── app/                    # Python 后端
│   ├── api/                # FastAPI 路由与依赖
│   ├── core/               # 业务服务
│   ├── llm/                # LLM 客户端与提示词
│   ├── pipeline/           # 检索管线
│   ├── storage/            # SQLite + FTS5
│   └── template/           # Vault 模板
├── frontend/               # React 前端
│   └── src/
│       ├── components/     # UI 组件
│       ├── pages/          # 页面组件
│       ├── services/       # API 调用
│       └── stores/         # Zustand 状态
├── configs/                # 策略配置
├── templates/              # Vault 模板
└── tests/                  # 测试套件
```

---

## 许可证

本项目基于 MIT 许可证开源 — 详见 [LICENSE](LICENSE)。
