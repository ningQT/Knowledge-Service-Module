"""pydantic-ai agent instruction prompts."""

STEP1_CLASSIFY_INSTRUCTIONS = (
    "对文档进行分类，只返回最终结构化输出。除非领域提示覆盖 domain，否则 domain 和 kind 使用简体中文短标签。"
)
STEP2_PATH_INSTRUCTIONS = "选择资料来源笔记名称，并生成候选知识卡片清单。"
STEP3_SOURCE_INSTRUCTIONS = "根据上传文档生成结构化资料来源笔记摘要。"
STEP4_FILTER_INSTRUCTIONS = "将候选知识点筛选为可复用的知识卡片。"
STEP4_LOCATE_INSTRUCTIONS = "定位可复用知识点，只能使用提供的整数 section_id。"
STEP5_CARD_INSTRUCTIONS = "根据提供的来源上下文生成一张高质量知识卡片。"
STEP6_MAP_INSTRUCTIONS = "生成一份组织所给卡片的知识地图。"
STEP7_RELATION_INSTRUCTIONS = "描述新增卡片为知识网络引入的关系。"
