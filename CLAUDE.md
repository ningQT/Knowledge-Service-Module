# CLAUDE.md

本文件为 KSM（Knowledge Service Module，知识服务模块）的项目级运行时指导，供 Claude Code 及后续会话在开发、评审、排障时遵循。项目治理的最高依据见 [`项目宪法`](.specify/memory/constitution.md)。

## 1. 语言

- 所有回复、流程说明、阶段说明、注释、文档一律使用**中文**。
- 代码、命令、路径、变量名、接口名、错误信息、日志、第三方库/框架/工具与官方专有名词可保留原文。
- 所有文档（含 Spec Kit 的 spec / plan / tasks / constitution 等产物）必须全中文撰写，即使官方模板为英文也不得沿用英文模板正文。

## 2. 项目概览

KSM 是面向 AI 业务系统的本地优先（local-first）知识服务模块，以 Obsidian Vault 目录标准为知识载体，将原始物料加工为可溯源、可检索、结构化的知识节点，通过标准目录、frontmatter 元数据、Wikilinks 与 SQLite（FTS5）索引组织数据。

### 技术栈（固定，勿擅自引入新框架）

| 层 | 技术 |
|----|------|
| 后端 | Python 3.11+ / FastAPI / SQLite（FTS5）/ 本地文件系统 |
| 前端 | React 19 / TypeScript / Vite / Tailwind CSS / shadcn-ui / Zustand / React Flow |
| 测试 | pytest / pytest-asyncio / pytest-cov（后端）；前端暂未配置测试框架 |
| 质量 | ruff / mypy（后端）；eslint + tsc（前端） |

## 3. 项目结构

```text
ksm/
├── app/                    # Python 后端
│   ├── api/                # FastAPI 路由与依赖注入（routes/ 下的 auth、ingest、search、graph、settings 等）
│   ├── config.py           # 环境变量配置（pydantic-settings，KSM_ 前缀）
│   ├── core/               # 业务服务（ingest_service、search_service、answer_service、ontology_service 等）
│   ├── llm/                # LLM 客户端、结构化输出、providers 注册表、prompts
│   ├── pipeline/           # 检索/回答管线（query_expander、graph_expander、answer_pipeline 等）
│   ├── storage/            # SQLite + FTS5、文件系统、schema.sql、语义索引
│   ├── schema/             # 文档解析、frontmatter 校验与规范化
│   ├── security/           # 请求防护、SSE token、URL/SSRF 校验
│   ├── shared_infra/       # 预算、截断、markdown 解析、strategy 等共享基础设施
│   ├── template/           # Vault 模板与脚手架
│   └── observability/      # 日志与上下文
├── frontend/               # React 前端（src/components、src/pages、src/services、src/stores）
├── configs/                # 策略配置（default.yaml、strategy_params.yaml）
├── templates/              # Vault 模板（standard_v1 等）
└── tests/                  # 测试套件（unit / integration / e2e，本地存在、不入版本库）
```

## 4. 常用命令

### 后端

```bash
# 启动（factory 模式）
uvicorn app.api.app:create_app --factory --host 127.0.0.1 --port 8900

# 依赖安装（任选其一）
pip install -r requirements.txt

# 测试
python -m pytest -q                     # 全部测试
pytest tests/unit/ -v                   # 单元测试
pytest tests/integration/ -v            # 集成测试
pytest tests/ --cov=app --cov-report=term-missing   # 带覆盖率

# 质量检查
ruff check .                           # lint（规则集 E/F/I/N/W/UP，行长 100）
mypy .                                 # 类型检查（strict）
```

### 前端

```bash
cd frontend
npm install
npm run dev                             # 开发服务器
npm run build                           # tsc -b && vite build
npm run lint                            # eslint
```

### 运维

```bash
docker compose up -d --build             # Docker 部署
```

## 5. 关键约定

- **配置体系**：环境变量统一 `KSM_` 前缀，由 `app/config.py` 的 `Settings` 加载；`.env` 按 `KSM_ENV`（test/prod/默认）选择 `.env.{env}` 或 `.env`。LLM 凭据不写入 `.env`，而是通过 Web 控制台 `/settings` 保存到数据库，运行时由 `get_effective_settings()` 合并（`.env` 基础 + DB 覆盖）。
- **API**：统一 `/api/v1` 前缀；核心路由为 `instances`、`ingest`、`search`、`graph`、`settings`、`ontology`、`auth`、`api_keys`。交互式文档运行后位于 `http://127.0.0.1:8900/docs`。
- **存储**：数据目录默认 `./data/vaults`，备份目录 `./data/backups`（`KSM_DATA_DIR` / `KSM_DB_BACKUP_DIR`）。数据库为本地 SQLite + FTS5 全文索引。
- **语义去重**：写入管线引入向量相似度去重（`KSM_DEDUP_SOURCE_THRESHOLD=0.92`、`KSM_DEDUP_CARD_THRESHOLD=0.88`、`KSM_DEDUP_MERGE_THRESHOLD=0.90`），embedding 配置为 `KSM_EMBEDDING_MODEL=text-embedding-3-small`、`KSM_EMBEDDING_DIMENSION=1536`。
- **策略配置**：检索/写入等可调策略参数位于 `configs/`（YAML），与代码分离，修改策略无需改代码。
- **安全**：默认开启 CSRF 防护、速率限制与 SSRF 防护；敏感信息（密钥、令牌、账号密码）不得写入代码、配置、文档或日志。
- **测试约定**：后端遵循「先确认、后写入；验证如实」，不得声称运行未实际运行的测试；测试失败须先定位修正，不得继续堆叠后续改动。

## 6. 治理与硬约束（摘要）

完整约束见 [`项目宪法`](.specify/memory/constitution.md) 与全局 `~/.claude/CLAUDE.md`。以下为本项目执行中必须遵守的核心点：

1. **先确认，后写入（不可协商）**：任何对项目文件的创建/修改/删除，须先说明任务目标、影响范围、最小修改边界、验证方式，获用户确认后方可执行。
2. **最小修改与复用优先**：只处理明确要求的内容，不得顺手优化、扩大范围、擅自改动接口/数据结构/配置/项目结构；优先复用既有实现，不复用须说明原因。
3. **文档全中文 + UTF-8 无 BOM**：所有待办项、方案文档（`task_plan/`）、状态文档（`PROJECT_STATUS.md`）、Spec Kit 产物一律中文；源文件以 UTF-8（无 BOM）保存，写入后校验无乱码。
4. **注释规范**：Python 用 Google 风格 docstring（含 Args/Returns/Raises），前端用 JSDoc（含 @param/@returns/@throws）；注释说明「为什么」而非「是什么」。
5. **验证如实**：使用项目既有测试/lint/类型检查验证；失败如实说明；临时产物结束前清理。

任务的详细分级、方案要求、执行规则、`PROJECT_STATUS.md` 维护规则、`task_plan/` 文档规范等 SOP，统一继承全局 `~/.claude/CLAUDE.md`，此处不重复展开。