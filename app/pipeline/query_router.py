"""Rule-based query intent routing."""


def route_query(normalized_query: str, raw_query: str = "") -> str:
    """Route a query to one of the supported search intent types."""
    q = f"{normalized_query} {raw_query}".lower()

    if _contains_any(q, ["source", "citation", "reference", "origin", "来源", "来自", "引用", "出处", "哪篇", "资料", "源自", "参考"]):
        return "source_trace"
    if _contains_any(q, ["compare", "difference", " versus ", " vs ", "区别", "差异", "对比", "比较", "不同"]):
        return "compare"
    if _contains_any(q, ["relation", "related", "link", "dependency", "关系", "关联", "相关", "依赖", "链接"]):
        return "relation"
    if _contains_any(q, ["list", "overview", "summary", "landscape", "which", "有哪些", "哪些", "列出", "总览", "概览", "体系", "清单"]):
        return "topic_scan"
    if _contains_any(q, ["what is", "define", "definition", "principle", "什么是", "定义", "原理", "如何理解"]):
        return "concept"
    if len(q.strip()) >= 2:
        return "concept"
    return "fallback"


def _contains_any(text: str, needles: list[str]) -> bool:
    return any(needle in text for needle in needles)
