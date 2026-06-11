"""Answer synthesis prompts."""

ANSWER_BATCH_SUMMARY_SYSTEM_PROMPT = "只返回严格 JSON。不要编造引用。只能使用提供的卡片内容和允许的 citation id。"
ANSWER_BATCH_SUMMARY_USER_PROMPT = """请把本批知识卡片压缩为结构化摘要，用于后续最终答案合成。
只能使用 payload 中每张卡片的 allowed_citation_ids，不得创造新的 citation id。
请返回 JSON：{{"card_summaries": [{{"card_path": string, "title": string, "relevance_to_query": string, "key_points": string[], "source_citation_ids": string[], "conflicts_or_limits": string[]}}], "batch_summary": {{"batch_id": string, "card_paths": string[], "summary": string, "key_points": string[], "citation_ids": string[]}}}}。
每张卡片最多 4 个 key_points；batch_summary 最多 8 个 key_points。语言跟随用户问题和知识内容。

{payload}"""

ANSWER_SYNTHESIS_SYSTEM_PROMPT = "只返回严格 JSON。不要编造引用。只能使用提供的知识地图、批次摘要、主题摘要、覆盖账本和引用上下文。"
ANSWER_SYNTHESIS_RETRY_SYSTEM_PROMPT = "只返回严格且紧凑的 JSON。答案保持简洁。不要编造引用。"

ANSWER_SYNTHESIS_USER_PROMPT = """基于知识地图、批次摘要和主题摘要整理答案，引用只能使用提供的 source note citation id。
请返回 JSON：{{"answer": string, "key_points": string[], "sections": [{{"id": string, "title": string, "summary": string, "key_points": string[], "citations": string[], "batch_ids": string[], "card_paths": string[], "coverage_status": "covered"|"partial"|"untraced", "remaining_card_count": number, "expandable": boolean, "continuation_hint": string}}], "citation_notes": object[], "process_summaries": object[]}}。
process_summaries 是可公开的阶段摘要，不要输出原始私密推理。
不要要求读取更多原始卡片正文；payload 中的 batch_summaries 和 topic_summaries 已经是本轮最终合成上下文。
sections 是面向用户展示的结构化知识报告。每个 section 只使用 payload 中已有 batch_ids、card_paths 和 citation id；不得编造 citation id。

{payload}"""

ANSWER_SECTION_SYNTHESIS_SYSTEM_PROMPT = "只返回严格 JSON。只整理 payload 中的单个主题。不要编造 citation、batch 或 card id。不要输出 HTML。"
ANSWER_SECTION_SYNTHESIS_USER_PROMPT = """请基于 payload 中的单个 topic 与相关 batch_summaries，生成一个面向用户的结构化 section。
只能使用 payload.allowed_citation_ids、payload.allowed_batch_ids、payload.allowed_card_paths 中存在的值。
请返回 JSON：{{"section": {{"id": string, "title": string, "summary": string, "content_md": string, "key_points": string[], "citations": string[], "batch_ids": string[], "card_paths": string[], "coverage_status": "covered"|"partial"|"untraced", "remaining_card_count": number, "expandable": boolean, "continuation_hint": string}}}}。
summary 控制在 2 句以内，作为章节预览。
content_md 是 Markdown 正文，面向用户直接阅读，可包含段落、三级标题、列表、表格和 `[S1]` 形式的引用；不要使用二级标题 `##`，不要包含“参考来源”章节，不要输出 HTML。
key_points 最多 6 条；citations 最多 6 个。不要返回 process_summaries。

{payload}"""

ANSWER_OVERVIEW_SYNTHESIS_SYSTEM_PROMPT = "只返回严格 JSON。只基于已生成的 sections 生成总览答案。不要编造引用。"
ANSWER_OVERVIEW_SYNTHESIS_USER_PROMPT = """请基于 payload.sections、coverage_ledger 和 citations 生成总览答案。
不要重新展开所有细节；不要返回 sections；不要返回 process_summaries。
请返回 JSON：{{"answer": string, "key_points": string[]}}。
answer 控制在 1200 字以内；key_points 最多 8 条。引用只能使用 payload 中已有 citation id。

{payload}"""
