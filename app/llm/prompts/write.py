"""Prompt templates for each write pipeline step."""

STEP1_CLASSIFY = """你是一个知识管理专家。请分析以下 Markdown 文档，判断其类型、领域和主题。

{language_instruction}

文档内容：
{content}

领域与种类输出要求：
1. 如果用户没有额外提供领域提示，domain 必须使用简体中文短标签，例如“记忆管理”“智能体”“自然语言处理”“编程”“产品设计”。
2. kind 必须使用简体中文短标签，例如“架构”“方法”“概念”“工具”“案例”“报告”。
3. 不要为 domain 或 kind 输出英文、拼音、下划线命名或斜杠组合。
4. topics 最多返回 5 个，只保留最核心主题。

请返回 JSON 格式：
{{
  "doc_type": "文档类型（paper/article/note/report）",
  "domain": "简体中文知识领域短标签",
  "kind": "简体中文细分类别短标签",
  "topics": ["主题1", "主题2"]
}}"""

STEP2_PATH_DECISION = """你是一个知识管理专家。
根据文档分类结果，决定资料来源笔记的命名和候选卡片清单。

{language_instruction}

文档标题：{filename}
文档分类：{classification}
已有资料来源：{existing_sources}

候选卡片要求：
1. candidate_cards 最多返回 8 个。
2. 只选择最核心、最可复用的候选卡片名。
3. 不要按目录逐条穷举标题。
4. 如果不确定，返回更少候选也可以。

请返回 JSON 格式：
{{
  "source_name": "资料来源笔记文件名（不含路径和扩展名）",
  "existing_source": null,
  "candidate_cards": ["候选卡片名1", "候选卡片名2"]
}}"""

STEP3_SOURCE_NOTE = """你是一个知识管理专家。请为以下原始文档生成一份结构化的资料来源笔记。

{language_instruction}

原始文档标题：{filename}
文档领域：{domain}
文档内容：
{content}

输出数量要求：
1. extractable_knowledge_points 最多 20 个，只保留最适合后续成卡的知识点。
2. concepts 最多 15 个，只保留核心概念。

请返回 JSON 格式：
{{
  "title": "资料来源标题",
  "summary": "原始文档概述（200-500字）",
  "extractable_knowledge_points": ["可抽取的知识点1", "可抽取的知识点2"],
  "concepts": ["核心概念1", "核心概念2"]
}}"""

STEP4_FILTER_CARDS = """你是一个知识管理专家。
请从以下可抽取知识点中，筛选出值得形成独立知识卡片的知识点。

{language_instruction}

可抽取知识点：
{knowledge_points}

已有知识卡片：{existing_cards}

筛选原则：
1. 知识点应具有独立性和复用价值
2. 避免过度碎片化
3. 避免与已有卡片明显重复
4. 每个卡片应承载一个相对稳定的知识单元

请返回 JSON 格式：
{{
  "selected": ["值得成卡片的知识点1", "知识点2"],
  "rejected": ["不值得的知识点"],
  "reasons": {{"知识点": "拒绝原因"}}
}}"""

STEP4_KNOWLEDGE_LOCATE = """请在这篇 Markdown 文档中定位可复用知识点，并返回 JSON。

{language_instruction}

返回字段要求：
- knowledge_points：数组，元素格式为 {{name, section_id, section_title, estimated_tokens}}
- rejected：被拒绝的知识点名称数组
- total_points：整数
- density_map：section_id 到 density_score 的映射

文档分类：{classification}
候选卡片：{candidate_cards}
已有卡片：{existing_cards}

## Section ID 映射（必须严格使用这些 ID）
{section_map_text}

文档上下文：
{body_context}"""

STEP5_GENERATE_CARD = """你是一个知识管理专家。请为以下知识点生成一张高质量、可复用的知识卡片。

{language_instruction}

知识点：{knowledge_point}
文档领域：{domain}
文档分类：{classification}
原始文档上下文：{context}

生成要求：
1. 卡片标题要稳定、规范，并使用知识库语言。
2. summary 用 1-3 句话概括这张卡片承载的知识。
3. sections 必须根据材料类型和知识点内容自适应生成 3-6 个章节，不要套用固定模板。
4. 人物传记可使用“生平概述、关键经历、时代背景、历史影响”等章节；历史事件可使用“事件背景、经过、结果、影响”等章节；概念/方法可使用“概述、核心要点、适用条件、判断标准”等章节。请按实际内容选择，不要机械照抄示例。
5. concepts 字段要准确反映卡片核心概念，最多 8 个。
6. wikilinks 要充分但克制，最多 10 个，只放真正相关的其他知识名；系统会过滤不存在的目标。
7. summary、sections、relations、sources_text 都不要输出 Obsidian wikilink 语法，不要写 [[...]]；候选链接只能放入 wikilinks 字段。
8. 来源要明确；如果上下文不足，请如实保持简洁，不要编造。

请返回 JSON 格式：
{{
  "title": "卡片标题",
  "summary": "这张卡片的简要概述",
  "sections": [
    {{"heading": "自适应章节标题", "content": "章节正文"}},
    {{"heading": "自适应章节标题", "content": "章节正文"}}
  ],
  "relations": "与其他知识的关系",
  "sources_text": "来源引用",
  "concepts": ["概念1", "概念2"],
  "graph_role": "concept 或 method",
  "wikilinks": ["相关概念名1", "相关概念名2"]
}}"""

STEP6_GENERATE_MAP = """你是一个知识管理专家。请根据以下信息生成一份知识地图。

{language_instruction}

主题：{topic}
领域：{domain}
相关卡片：{cards}
真实来源笔记（必须原样使用 path，不要改写）：{source_ref}
原始文档概述：{summary}

语言要求：
1. title、topic_overview、summary、reason 和 description 必须跟随知识库语言。
2. 专有名词、原文中不可自然翻译的术语、文件路径和卡片路径除外。

路径约束：
1. source_materials 只能使用“真实来源笔记”里的 path。
2. core_concepts 和 reading_path 的 card 只能使用“相关卡片”里已有的 path。
3. 如果无法确认 linked_maps 的真实 path，请省略 path，只保留 title 和 reason。

数量约束：
1. concepts 最多 15 个。
2. core_concepts 和 reading_path 最多各 10 个。
3. key_relations 最多 20 个。
4. linked_maps 最多 10 个。

请返回 JSON 格式：
{{
  "title": "知识地图标题",
  "topic_overview": "主题概述（100-300字）",
  "related_cards": ["卡片路径1", "卡片路径2"],
  "relationship_context": "关系脉络说明",
  "concepts": ["核心概念1", "核心概念2"],
  "core_concepts": [
    {{"title": "概念名", "role": "core", "card": "02-知识卡片/xxx.md", "summary": "简要说明"}},
    {{"title": "概念名", "role": "hub", "card": "02-知识卡片/yyy.md", "summary": "简要说明"}}
  ],
  "reading_path": [
    {{"order": 1, "title": "入门概念", "card": "02-知识卡片/xxx.md", "reason": "阅读理由"}}
  ],
  "key_relations": [
    {{"from": "概念A", "relation": "依赖/对比/组成", "to": "概念B", "description": "关系说明"}}
  ],
  "source_materials": [
    {{"title": "来源笔记", "path": "01-资料来源/xxx.md", "reason": "来源价值"}}
  ],
  "linked_maps": [
    {{"title": "相关地图", "path": "03-知识地图/xxx.md", "reason": "关联理由"}}
  ]
}}"""

STEP7_RELATION_DESC = """你是一个知识管理专家。请为本次新增卡片生成少量可靠关系说明。

{language_instruction}

本次新增卡片：{new_cards}
本次领域：{domain}
本次类别：{kind}
核心主题：{topics}

输出要求：
1. new_connections 最多 10 条，只保留最可靠的关系。
2. source 和 target 必须严格使用“本次新增卡片”中的卡片名，不要编造卡片名。
3. source 不能等于 target。
4. relation_type 只能是 dependency、comparison、composition、extension 之一。
5. description 使用短句，不要输出 Obsidian wikilink 语法，不要写 [[...]]。

请返回 JSON 格式：
{{
  "description": "本次写入对知识网络的关系说明",
  "new_connections": [
    {{"source": "卡片A", "target": "卡片B", "relation_type": "dependency", "description": "关系说明"}}
  ]
}}"""


# Prompt registry
PROMPTS = {
    "classify": STEP1_CLASSIFY,
    "path_decision": STEP2_PATH_DECISION,
    "source_note": STEP3_SOURCE_NOTE,
    "filter_cards": STEP4_FILTER_CARDS,
    "generate_card": STEP5_GENERATE_CARD,
    "generate_map": STEP6_GENERATE_MAP,
    "relation_desc": STEP7_RELATION_DESC,
}
