"""正式目录的精确定位。仅处理明确 ID、引号目标和常见指令外壳，其他表达交语义模块。"""

import re
import unicodedata

from shared.contracts import Candidate, Resolution


def normalize(value):
    # 保留 +、#、版本、小数及否定词，不将 C++ / C# 或 1.2 / 12 合并。
    return " ".join(unicodedata.normalize("NFKC", value).casefold().split())


def target_phrase(text):
    value = normalize(text).strip("?？。")
    quoted = re.fullmatch(r'.*?[“「"]([^”」"]+)[”」"].*', value)
    if quoted:
        return quoted.group(1)
    # 只去掉有边界的常见问句/操作外壳，不从实体标题的任意子串作确定性命中。
    update = re.fullmatch(
        r"(?:请)?(?:把|将)(.+?)(?:的)?(?:进度|状态)(?:更新为|改为|设为|改成|更新到|改到).+", value
    )
    if update:
        return update.group(1)
    question = re.fullmatch(
        r"(.+?)(?:现在|目前)?(?:的)?(?:进度怎样|进度如何|状态怎样|进度|状态|负责人是谁)", value
    )
    return question.group(1) if question else value


def resolve_exact(catalog, text, entity_type="task", limit=10):
    records = [e for e in catalog if e.is_active and e.entity_type == entity_type]
    ids = re.findall(r"(?i)(?<![\w-])TASK[-:# ](\d+)(?!\d)", text) if entity_type == "task" else []
    if ids:
        found = [e for e in records if str(e.entity_id) in ids]
        if {str(e.entity_id) for e in found} != set(ids):
            # 指定了不存在或项目外的 ID，不能忽略它而自动选剩余对象。
            return Resolution(outcome="not_found", index_version="authoritative-catalog-v1")
        reason = "explicit_id"
    else:
        phrase = target_phrase(text)
        found = [
            e
            for e in records
            if normalize(e.title) == phrase
            or any(normalize(alias) == phrase for alias in e.aliases)
        ]
        if not found:
            return None
        reason = "exact_title_or_alias"
    return Resolution(
        outcome="not_found" if not found else "resolved" if len(found) == 1 else "ambiguous",
        candidates=[
            Candidate(
                entity_type=e.entity_type, entity_id=e.entity_id, title=e.title, match_reason=reason
            )
            for e in found[:limit]
        ],
        index_version="authoritative-catalog-v1",
    )
