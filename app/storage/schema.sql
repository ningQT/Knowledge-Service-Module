-- KSM SQLite Schema
-- Reference: 详细设计文档 Section 9.3-9.4, 检索流程设计 Part 2 Section 7.1

CREATE TABLE IF NOT EXISTS schema_migrations (
    version TEXT PRIMARY KEY,
    description TEXT NOT NULL,
    applied_at TEXT NOT NULL DEFAULT (datetime('now'))
);

-- 实例表
CREATE TABLE IF NOT EXISTS instances /* 知识库实例表 */ (
    id TEXT PRIMARY KEY /* 实例ID，API 路由、索引和隔离的主键 */,
    name TEXT NOT NULL /* 实例显示名称 */,
    template_id TEXT NOT NULL /* 创建实例时使用的模板ID */,
    vault_path TEXT NOT NULL /* 实例对应的本地 vault 根路径 */,
    auto_map INTEGER NOT NULL DEFAULT 1 /* 是否在写入时自动生成知识地图，1=开启，0=关闭 */,
    config_json TEXT DEFAULT '{}' /* 实例级配置 JSON */,
    created_at TEXT NOT NULL /* 实例创建时间，ISO 字符串 */,
    updated_at TEXT NOT NULL /* 实例更新时间，ISO 字符串 */
);

-- 知识文件索引表
CREATE TABLE IF NOT EXISTS notes /* 知识笔记索引表 */ (
    id INTEGER PRIMARY KEY AUTOINCREMENT /* 内部自增主键，供 FTS content_rowid 使用 */,
    instance_id TEXT NOT NULL /* 所属知识库实例ID */,
    file_path TEXT NOT NULL /* vault 内相对路径，实例内唯一 */,
    title TEXT NOT NULL /* 笔记标题，通常来自 H1 或文件名 */,
    type TEXT /* 笔记类型，如 source/card/map */,
    domain TEXT /* 主领域，用于筛选和检索 */,
    kind TEXT /* 细分类别，用于筛选和检索 */,
    graph_layer INTEGER DEFAULT 0 /* 图谱层级：1=资料来源，2=知识卡片，3=知识地图 */,
    graph_role TEXT /* 图谱角色，如 source/concept/index */,
    verification TEXT DEFAULT 'unverified' /* 审核状态，如 unverified/verified/draft */,
    status TEXT DEFAULT 'active' /* 笔记生命周期状态 */,
    frontmatter TEXT DEFAULT '{}' /* 原始/规范化 frontmatter JSON */,
    search_text TEXT DEFAULT '' /* FTS 可重建的索引文本 */,
    content_hash TEXT /* 文件内容哈希，用于判断内容变化 */,
    indexed_at TEXT NOT NULL /* 最近索引时间，ISO 字符串 */,
    UNIQUE(instance_id, file_path),
    FOREIGN KEY (instance_id) REFERENCES instances(id)
);

-- 关系表
CREATE TABLE IF NOT EXISTS relations /* 知识图谱关系边表 */ (
    id INTEGER PRIMARY KEY AUTOINCREMENT /* 内部自增主键 */,
    instance_id TEXT NOT NULL /* 所属知识库实例ID，关系只在实例内生效 */,
    source_path TEXT NOT NULL /* 起点笔记 vault 相对路径 */,
    target_path TEXT NOT NULL /* 终点笔记 vault 相对路径 */,
    rel_type TEXT NOT NULL /* 关系类型，如 direct_link/source_trace/map_contains */,
    UNIQUE(instance_id, source_path, target_path, rel_type),
    FOREIGN KEY (instance_id) REFERENCES instances(id)
);

CREATE TABLE IF NOT EXISTS note_facets /* 笔记筛选维度表 */ (
    id INTEGER PRIMARY KEY AUTOINCREMENT /* 内部自增主键 */,
    instance_id TEXT NOT NULL /* 所属知识库实例ID */,
    file_path TEXT NOT NULL /* 对应笔记 vault 相对路径 */,
    field TEXT NOT NULL /* 维度字段名，如 domain/kind/aliases/concepts */,
    value TEXT NOT NULL /* 维度字段值，用于筛选与解析 */,
    UNIQUE(instance_id, file_path, field, value),
    FOREIGN KEY (instance_id) REFERENCES instances(id)
);

CREATE TABLE IF NOT EXISTS link_references /* 可诊断链接引用表 */ (
    id INTEGER PRIMARY KEY AUTOINCREMENT /* 内部自增主键 */,
    instance_id TEXT NOT NULL /* 所属知识库实例ID */,
    source_path TEXT NOT NULL /* 产生引用的笔记 vault 相对路径 */,
    target_text TEXT NOT NULL /* 原始链接目标文本或 frontmatter 引用目标 */,
    target_path TEXT /* 成功解析后的目标笔记 vault 相对路径 */,
    link_kind TEXT NOT NULL /* 链接来源类型，如 body_wikilink/frontmatter_wikilink */,
    source_field TEXT NOT NULL /* 引用所在字段，如 body/sources/aliases */,
    resolved INTEGER NOT NULL DEFAULT 0 /* 是否已在当前实例内解析到真实笔记 */,
    UNIQUE(instance_id, source_path, target_text, link_kind, source_field),
    FOREIGN KEY (instance_id) REFERENCES instances(id)
);

-- 写入任务表
CREATE TABLE IF NOT EXISTS ingest_jobs /* 写入任务状态表 */ (
    job_id TEXT PRIMARY KEY /* 写入任务ID */,
    instance_id TEXT NOT NULL /* 所属知识库实例ID */,
    input_file TEXT /* 用户上传或传入的原始文件名 */,
    status TEXT NOT NULL DEFAULT 'running' /* 任务状态，如 running/success/failed/partial_failed */,
    created_files TEXT DEFAULT '[]' /* 本次任务创建的文件路径列表 JSON */,
    updated_files TEXT DEFAULT '[]' /* 本次任务更新的文件路径列表 JSON */,
    warnings TEXT DEFAULT '[]' /* 写入过程警告列表 JSON */,
    started_at TEXT NOT NULL /* 任务开始时间，ISO 字符串 */,
    finished_at TEXT /* 任务结束时间，ISO 字符串 */,
    FOREIGN KEY (instance_id) REFERENCES instances(id)
);

-- FTS5 全文索引（external content table + trigram tokenizer 支持中文子串匹配）
-- Reference: 详细设计文档 §9.3 R-07: 查询用子查询而非 JOIN
CREATE VIRTUAL TABLE IF NOT EXISTS notes_fts /* FTS5 trigram 全文检索表 */ USING fts5(
    title /* 笔记标题全文索引列 */,
    search_text /* 标题、正文关键内容与结构化元数据的组合索引文本 */,
    content=notes,
    content_rowid=id,
    tokenize='trigram'
);

-- 索引
CREATE INDEX IF NOT EXISTS idx_notes_instance ON notes(instance_id);
CREATE INDEX IF NOT EXISTS idx_notes_layer ON notes(instance_id, graph_layer);
CREATE INDEX IF NOT EXISTS idx_notes_domain ON notes(instance_id, domain);
CREATE INDEX IF NOT EXISTS idx_notes_title ON notes(instance_id, title);
CREATE INDEX IF NOT EXISTS idx_relations_source ON relations(instance_id, source_path);
CREATE INDEX IF NOT EXISTS idx_relations_target ON relations(instance_id, target_path);
CREATE INDEX IF NOT EXISTS idx_relations_type ON relations(instance_id, rel_type);
CREATE INDEX IF NOT EXISTS idx_note_facets_lookup ON note_facets(instance_id, field, value);
CREATE INDEX IF NOT EXISTS idx_note_facets_note ON note_facets(instance_id, file_path);
CREATE INDEX IF NOT EXISTS idx_link_refs_source ON link_references(instance_id, source_path);
CREATE INDEX IF NOT EXISTS idx_link_refs_target ON link_references(instance_id, target_text);
CREATE INDEX IF NOT EXISTS idx_link_refs_resolved ON link_references(instance_id, resolved);
CREATE INDEX IF NOT EXISTS idx_ingest_instance ON ingest_jobs(instance_id);

-- 实例级检索词表：用于维护知识库实例内的 alias / synonym 检索规则
CREATE TABLE IF NOT EXISTS instance_search_lexicon (
    id TEXT PRIMARY KEY,
    instance_id TEXT NOT NULL,
    relation_type TEXT NOT NULL CHECK(relation_type IN ('alias', 'synonym')),
    canonical_term TEXT NOT NULL,
    canonical_term_norm TEXT NOT NULL,
    variant_terms_json TEXT NOT NULL DEFAULT '[]',
    enabled INTEGER NOT NULL DEFAULT 1,
    notes TEXT DEFAULT '',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE(instance_id, relation_type, canonical_term_norm),
    FOREIGN KEY (instance_id) REFERENCES instances(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_search_lexicon_instance ON instance_search_lexicon(instance_id);
CREATE INDEX IF NOT EXISTS idx_search_lexicon_enabled ON instance_search_lexicon(instance_id, enabled);

-- 设置表 (Phase 3: LLM 配置热更新持久化)
-- 优先级链: settings 表 > .env 文件 > 代码默认值
CREATE TABLE IF NOT EXISTS settings /* 系统设置表 */ (
    key         TEXT PRIMARY KEY /* 设置键名 */,
    value       TEXT NOT NULL /* 设置值，按调用方约定解析 */,
    updated_at  TEXT NOT NULL DEFAULT (datetime('now')) /* 最近更新时间 */
);

CREATE INDEX IF NOT EXISTS idx_settings_prefix ON settings(key);

-- 管理控制台管理员账户
CREATE TABLE IF NOT EXISTS admin_users (
    id TEXT PRIMARY KEY,
    username TEXT NOT NULL UNIQUE,
    password_hash TEXT NOT NULL,
    password_salt TEXT NOT NULL,
    password_iterations INTEGER NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

-- 管理控制台会话，token 只保存 hash
CREATE TABLE IF NOT EXISTS admin_sessions (
    token_hash TEXT PRIMARY KEY,
    user_id TEXT NOT NULL,
    created_at TEXT NOT NULL,
    last_seen_at TEXT NOT NULL,
    expires_at TEXT NOT NULL,
    FOREIGN KEY (user_id) REFERENCES admin_users(id) ON DELETE CASCADE
);

-- 外部系统 API Key 客户端，key 明文只在创建/轮换时返回一次
CREATE TABLE IF NOT EXISTS api_clients (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    key_prefix TEXT NOT NULL,
    key_hash TEXT NOT NULL UNIQUE,
    scope TEXT NOT NULL CHECK(scope IN ('read', 'write')),
    enabled INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    last_used_at TEXT
);

CREATE TABLE IF NOT EXISTS api_client_instances (
    client_id TEXT NOT NULL,
    instance_id TEXT NOT NULL,
    PRIMARY KEY (client_id, instance_id),
    FOREIGN KEY (client_id) REFERENCES api_clients(id) ON DELETE CASCADE,
    FOREIGN KEY (instance_id) REFERENCES instances(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_admin_sessions_user ON admin_sessions(user_id);
CREATE INDEX IF NOT EXISTS idx_admin_sessions_expires ON admin_sessions(expires_at);
CREATE INDEX IF NOT EXISTS idx_api_clients_enabled ON api_clients(enabled);
CREATE INDEX IF NOT EXISTS idx_api_client_instances_instance ON api_client_instances(instance_id);

-- ============================================================================
-- 本体系统运行态表 (Phase 8)
-- ============================================================================

-- 本体类型表
CREATE TABLE IF NOT EXISTS ontology_types (
    id TEXT PRIMARY KEY,
    instance_id TEXT NOT NULL,
    name TEXT NOT NULL,
    name_norm TEXT NOT NULL,
    description TEXT DEFAULT '',
    parent_type_id TEXT DEFAULT NULL,
    status TEXT NOT NULL DEFAULT 'active',
    searchable INTEGER NOT NULL DEFAULT 1,
    source TEXT DEFAULT 'manual',
    confidence REAL DEFAULT 1.0,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE(instance_id, name_norm),
    FOREIGN KEY (instance_id) REFERENCES instances(id) ON DELETE CASCADE,
    FOREIGN KEY (parent_type_id) REFERENCES ontology_types(id) ON DELETE SET NULL
);

-- 本体实体表
CREATE TABLE IF NOT EXISTS ontology_entities (
    id TEXT PRIMARY KEY,
    instance_id TEXT NOT NULL,
    name TEXT NOT NULL,
    name_norm TEXT NOT NULL,
    entity_type_id TEXT DEFAULT NULL,
    description TEXT DEFAULT '',
    status TEXT NOT NULL DEFAULT 'active',
    searchable INTEGER NOT NULL DEFAULT 1,
    source TEXT DEFAULT 'manual',
    confidence REAL DEFAULT 1.0,
    metadata_json TEXT DEFAULT '{}',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE(instance_id, name_norm),
    FOREIGN KEY (instance_id) REFERENCES instances(id) ON DELETE CASCADE,
    FOREIGN KEY (entity_type_id) REFERENCES ontology_types(id) ON DELETE SET NULL
);

-- 实体别名表
CREATE TABLE IF NOT EXISTS ontology_entity_aliases (
    id TEXT PRIMARY KEY,
    instance_id TEXT NOT NULL,
    entity_id TEXT NOT NULL,
    alias_text TEXT NOT NULL,
    alias_norm TEXT NOT NULL,
    source TEXT DEFAULT 'manual',
    created_at TEXT NOT NULL,
    UNIQUE(instance_id, entity_id, alias_norm),
    FOREIGN KEY (instance_id) REFERENCES instances(id) ON DELETE CASCADE,
    FOREIGN KEY (entity_id) REFERENCES ontology_entities(id) ON DELETE CASCADE
);

-- 实体关系表
CREATE TABLE IF NOT EXISTS ontology_relations (
    id TEXT PRIMARY KEY,
    instance_id TEXT NOT NULL,
    source_entity_id TEXT NOT NULL,
    target_entity_id TEXT NOT NULL,
    relation_type TEXT NOT NULL,
    description TEXT DEFAULT '',
    status TEXT NOT NULL DEFAULT 'active',
    searchable INTEGER NOT NULL DEFAULT 1,
    source TEXT DEFAULT 'manual',
    confidence REAL DEFAULT 1.0,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE(instance_id, source_entity_id, target_entity_id, relation_type),
    FOREIGN KEY (instance_id) REFERENCES instances(id) ON DELETE CASCADE,
    FOREIGN KEY (source_entity_id) REFERENCES ontology_entities(id) ON DELETE CASCADE,
    FOREIGN KEY (target_entity_id) REFERENCES ontology_entities(id) ON DELETE CASCADE
);

-- 关系证据表
CREATE TABLE IF NOT EXISTS ontology_relation_evidence (
    id TEXT PRIMARY KEY,
    instance_id TEXT NOT NULL,
    relation_id TEXT NOT NULL,
    file_path TEXT NOT NULL,
    evidence_type TEXT DEFAULT 'mention',
    snippet TEXT DEFAULT '',
    confidence REAL DEFAULT 1.0,
    status TEXT NOT NULL DEFAULT 'active',
    created_at TEXT NOT NULL,
    FOREIGN KEY (instance_id) REFERENCES instances(id) ON DELETE CASCADE,
    FOREIGN KEY (relation_id) REFERENCES ontology_relations(id) ON DELETE CASCADE
);

-- 实体-文档桥接表
CREATE TABLE IF NOT EXISTS ontology_entity_note_links (
    id TEXT PRIMARY KEY,
    instance_id TEXT NOT NULL,
    entity_id TEXT NOT NULL,
    file_path TEXT NOT NULL,
    link_type TEXT DEFAULT 'mention',
    snippet TEXT DEFAULT '',
    confidence REAL DEFAULT 1.0,
    status TEXT NOT NULL DEFAULT 'active',
    created_at TEXT NOT NULL,
    UNIQUE(instance_id, entity_id, file_path, link_type),
    FOREIGN KEY (instance_id) REFERENCES instances(id) ON DELETE CASCADE,
    FOREIGN KEY (entity_id) REFERENCES ontology_entities(id) ON DELETE CASCADE
);

-- 类型层级表
CREATE TABLE IF NOT EXISTS ontology_type_hierarchy (
    id TEXT PRIMARY KEY,
    instance_id TEXT NOT NULL,
    parent_type_id TEXT NOT NULL,
    child_type_id TEXT NOT NULL,
    depth INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL,
    UNIQUE(instance_id, parent_type_id, child_type_id),
    FOREIGN KEY (instance_id) REFERENCES instances(id) ON DELETE CASCADE,
    FOREIGN KEY (parent_type_id) REFERENCES ontology_types(id) ON DELETE CASCADE,
    FOREIGN KEY (child_type_id) REFERENCES ontology_types(id) ON DELETE CASCADE
);

-- 本体表索引
CREATE INDEX IF NOT EXISTS idx_ontology_types_instance ON ontology_types(instance_id);
CREATE INDEX IF NOT EXISTS idx_ontology_types_searchable ON ontology_types(instance_id, searchable);
CREATE INDEX IF NOT EXISTS idx_ontology_types_parent ON ontology_types(parent_type_id);
CREATE INDEX IF NOT EXISTS idx_ontology_types_name_norm ON ontology_types(instance_id, name_norm);

CREATE INDEX IF NOT EXISTS idx_ontology_entities_instance ON ontology_entities(instance_id);
CREATE INDEX IF NOT EXISTS idx_ontology_entities_searchable ON ontology_entities(instance_id, searchable);
CREATE INDEX IF NOT EXISTS idx_ontology_entities_type ON ontology_entities(entity_type_id);
CREATE INDEX IF NOT EXISTS idx_ontology_entities_name_norm ON ontology_entities(instance_id, name_norm);

CREATE INDEX IF NOT EXISTS idx_ontology_aliases_instance ON ontology_entity_aliases(instance_id);
CREATE INDEX IF NOT EXISTS idx_ontology_aliases_entity ON ontology_entity_aliases(entity_id);
CREATE INDEX IF NOT EXISTS idx_ontology_aliases_norm ON ontology_entity_aliases(instance_id, alias_norm);

CREATE INDEX IF NOT EXISTS idx_ontology_relations_instance ON ontology_relations(instance_id);
CREATE INDEX IF NOT EXISTS idx_ontology_relations_source ON ontology_relations(source_entity_id);
CREATE INDEX IF NOT EXISTS idx_ontology_relations_target ON ontology_relations(target_entity_id);
CREATE INDEX IF NOT EXISTS idx_ontology_relations_searchable ON ontology_relations(instance_id, searchable);

CREATE INDEX IF NOT EXISTS idx_ontology_evidence_instance ON ontology_relation_evidence(instance_id);
CREATE INDEX IF NOT EXISTS idx_ontology_evidence_relation ON ontology_relation_evidence(relation_id);
CREATE INDEX IF NOT EXISTS idx_ontology_evidence_file ON ontology_relation_evidence(instance_id, file_path);

CREATE INDEX IF NOT EXISTS idx_ontology_note_links_instance ON ontology_entity_note_links(instance_id);
CREATE INDEX IF NOT EXISTS idx_ontology_note_links_entity ON ontology_entity_note_links(entity_id);
CREATE INDEX IF NOT EXISTS idx_ontology_note_links_file ON ontology_entity_note_links(instance_id, file_path);

CREATE INDEX IF NOT EXISTS idx_ontology_hierarchy_instance ON ontology_type_hierarchy(instance_id);
CREATE INDEX IF NOT EXISTS idx_ontology_hierarchy_parent ON ontology_type_hierarchy(parent_type_id);
CREATE INDEX IF NOT EXISTS idx_ontology_hierarchy_child ON ontology_type_hierarchy(child_type_id);

-- 本体全局开关默认开启
INSERT OR IGNORE INTO settings (key, value) VALUES ('ontology.enabled', '1');
