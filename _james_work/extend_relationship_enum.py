# -*- coding: utf-8 -*-
"""扩展 semantica relationship 枚举值 + 使用示例。

semantica 预定义的 relationship 枚举在两处：
1. RelationshipType (13 个值)  —— semantica/utils/types.py:145
2. _CAUSAL_EDGE_TYPES (3 个值) —— semantica/context/context_graph.py:543（仅决策因果边，强校验）

扩展方式（按推荐顺序）：
- 方式 A：运行时动态给 RelationshipType 添加成员（最轻量）
- 方式 B：重新声明一个 (str, Enum)，包含原有 13 个 + 新增值（最规范）
- 方式 C：functional API 一行合成（最简短）
- 方式 D：ContextGraph.add_edge 本身就接受任意 edge_type 字符串（对图边无枚举约束）
- 方式 E：关系抽取扩展——extract_relations_regex 自定义谓词 + 正则模式
         （注意：仅决策因果边 add_causal_relationship 是强校验的，不能扩展）

运行：D:/_AllDocMap/06_Software/anaconda/python.exe extend_relationship_enum.py
"""

import sys
from enum import Enum

import common  # noqa: F401  初始化 sys.path
from common import banner, step

from semantica.utils.types import RelationshipType

# 供应链领域的扩展枚举值
NEW_RELATIONS = {
    "SUPPLIES": "供应商向采购方供货",
    "OWNS": "所有权关系",
    "LICENSES_TO": "许可授权关系",
}


def method_a_dynamic() -> None:
    """方式 A：运行时给 RelationshipType 打补丁，追加新成员。

    注意：setattr 只添加普通属性，不会注册为真正的 Enum 成员
    （len(list(RelationshipType)) 仍是 13，且不出现在迭代中），
    但属性访问 RelationshipType.SUPPLIES 与字符串比较都可用。
    适合快速临时扩展；正式扩展请用方式 B。
    """
    for name, desc in NEW_RELATIONS.items():
        setattr(RelationshipType, name, name)  # str-Enum 可直接赋字符串
    print(f"  RelationshipType.SUPPLIES = {RelationshipType.SUPPLIES}")
    print(f"  字符串比较: {'SUPPLIES' == RelationshipType.SUPPLIES}")
    print(f"  注意: len(list(RelationshipType)) 仍为 {len(list(RelationshipType))}（动态属性不注册为成员）")


def method_b_subclass() -> Enum:
    """方式 B：重新声明 (str, Enum)，包含原有 + 新增（推荐，类型安全）。"""
    class ExtendedRelationshipType(str, Enum):
        # 原有 13 个（与 utils/types.py 保持一致）
        WORKS_FOR = "WORKS_FOR"
        LOCATED_IN = "LOCATED_IN"
        PART_OF = "PART_OF"
        RELATED_TO = "RELATED_TO"
        CAUSES = "CAUSES"
        AFFECTS = "AFFECTS"
        BEFORE = "BEFORE"
        AFTER = "AFTER"
        DURING = "DURING"
        SAME_AS = "SAME_AS"
        DIFFERENT_FROM = "DIFFERENT_FROM"
        SIMILAR_TO = "SIMILAR_TO"
        UNKNOWN = "UNKNOWN"
        # ---- 新增（供应链领域）----
        SUPPLIES = "SUPPLIES"
        OWNS = "OWNS"
        LICENSES_TO = "LICENSES_TO"

    print(f"  ExtendedRelationshipType 成员数: {len(list(ExtendedRelationshipType))}")
    print(f"  新增成员: {[m.name for m in ExtendedRelationshipType if m.name in NEW_RELATIONS]}")
    return ExtendedRelationshipType


def method_c_functional():
    """方式 C：functional API 一行合并原有枚举 + 新值。"""
    merged = Enum("MergedRelationshipType", {m.name: m.value for m in RelationshipType} | NEW_RELATIONS)
    print(f"  MergedRelationshipType 成员数: {len(list(merged))}")
    return merged


def method_d_graph_edges() -> None:
    """方式 D：ContextGraph.add_edge 接受任意 edge_type（图边无枚举约束）。"""
    from semantica.context import ContextGraph

    g = ContextGraph()
    g.add_node("initech", "Organization", name="Initech Ltd")
    g.add_node("acme", "Organization", name="Acme Corp")
    g.add_node("globex", "Organization", name="Globex")
    g.add_node("semaphore", "Organization", name="Semaphore Ltd")

    # 直接用自定义类型建边（可枚举值，也可任意字符串）
    g.add_edge("initech", "acme", edge_type="SUPPLIES", since="2024")
    g.add_edge("globex", "semaphore", edge_type="OWNS", acquired="2023-06")

    neighbors = g.get_neighbors("initech", hops=1)
    for n in neighbors:
        print(f"  Initech -[{n['relationship']}]-> {n['id']}")

    kg = g.to_kg_dict()
    for r in kg.get("relationships", []):
        print(f"  edge: {r.get('type') or r.get('relationship')}  (source={r.get('source', '?')})")


def method_e_extraction() -> None:
    """方式 E：关系抽取扩展——自定义谓词 + 正则（semantica/semantic_extract/methods.py:1564）。"""
    from semantica.semantic_extract.methods import extract_relations_regex
    from semantica.semantic_extract.types import Entity

    text = "Initech supplies Acme. Globex owns Semaphore Ltd."
    ents = [
        Entity(text="Initech", label="ORG", start_char=0, end_char=7),
        Entity(text="Acme", label="ORG", start_char=17, end_char=21),
        Entity(text="Globex", label="ORG", start_char=23, end_char=29),
        Entity(text="Semaphore Ltd", label="ORG", start_char=36, end_char=48),
    ]

    # 自定义谓词（= 新枚举值）与对应的抽取正则
    custom_patterns = {
        "SUPPLIES": [r"(?P<subject>\w+)\s+supplies\s+(?P<object>\w+)"],
        "OWNS": [r"(?P<subject>\w+)\s+owns\s+(?P<object>\w+(?:\s\w+)*)"],
    }
    rels = extract_relations_regex(text, ents, patterns=custom_patterns)
    for r in rels:
        print(f"  {r.subject.text} --[{r.predicate}]--> {r.object.text}  "
              f"(conf={r.confidence}, method={r.metadata.get('extraction_method')})")
    print("  → 抽出的 predicate 'SUPPLIES'/'OWNS' 即扩展后的枚举值，可直接入图（见方式 D）")


def main() -> None:
    banner("方式 A：运行时动态扩展 RelationshipType")
    method_a_dynamic()

    banner("方式 B：重新声明 (str, Enum)（推荐）")
    method_b_subclass()

    banner("方式 C：functional API 合并")
    method_c_functional()

    banner("方式 D：ContextGraph 自定义 edge_type 建边")
    method_d_graph_edges()

    banner("方式 E：自定义谓词 + 正则做关系抽取")
    method_e_extraction()

    print("\n[注意] add_causal_relationship() 的 CAUSED/INFLUENCED/PRECEDENT_FOR 是强校验元组，"
          "\n       定义于 context_graph.py:543，不能扩展；但 add_edge() 无此限制。")


if __name__ == "__main__":
    main()
