"""Common LLM prompt snippets."""

RETURN_STRICT_JSON_ONLY = "只返回严格 JSON，不要输出 Markdown、代码块或额外说明。"

LANGUAGE_INSTRUCTIONS = {
    "zh": (
        "输出语言要求：请以简体中文为主要表达语言。除 agent、LLM、BERT、API、"
        "模型名、论文名、产品名、专有名词、行业常用缩写和原文中不可自然翻译的术语外，"
        "标题、摘要、解释、判断、关系说明和普通概念表达都应使用中文。"
    ),
    "en": (
        "输出语言要求：请以英文为主要表达语言。保留原文中的模型名、论文名、产品名、"
        "专有名词、行业常用缩写和不可自然翻译的术语。"
    ),
}

DEFAULT_LANGUAGE = "zh"
