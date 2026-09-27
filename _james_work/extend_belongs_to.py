# -*- coding: utf-8 -*-
"""扩展 BELONGS_TO relationship 的完整使用示例。

演示 BELONGS_TO（隶属关系）从定义 -> 抽取 -> 入图 -> 查询 -> 导出 -> 本体化的全链路：
1. 方式 B：重声明 (str, Enum) 加入 BELONGS_TO（推荐）
2. 抽取层：extract_relations_regex 用自定义正则从文本抽 BELONGS_TO
3. 图层：ContextGraph.add_edge(edge_type="BELONGS_TO") 建边
4. 查询：get_neighbors 沿 BELONGS_TO 遍历（查某人的所属组织 / 某组织的成员）
5. 导出：to_kg_dict + RDFExporter 导出 Turtle（谓词出现在 RDF 里）
6. 本体层：把 BELONGS_TO 生成 owl:ObjectProperty 纳入本体并校验

运行：D:/_AllDocMap/06_Software/anaconda/python.exe extend_belongs_to.py
"""

import common  # noqa: F401  初始化 sys.path（加入 semantica 源码）
from common import banner, step, out_path

from enum import Enum
from semantica.utils.types import RelationshipType

# ---------------------------------------------------------------------------
# 1. 扩展枚举：重声明 (str, Enum)，包含原有 13 值 + BELONGS_TO
#    （str, Enum 无法继承扩展，必须重新声明 mixin——实测 TypeError）
# ---------------------------------------------------------------------------
class ExtendedRelationshipType(str, Enum):
    # 原有 13 个（与 semantica/utils/types.py:145 保持一致）
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
    # ---- 扩展：隶属关系 ----
    BELONGS_TO = "BELONGS_TO"

BELONGS_TO = ExtendedRelationshipType.BELONGS_TO.value  # "BELONGS_TO"

# 语料：模拟 HR/组织文档
DOCS = {
    "doc1": "Alice Chen belongs to the Data Science team at Acme Corp.",
    "doc2": "Bob Lee belongs to the Finance department at Globex.",
    "doc3": "The Data Science team belongs to Acme Corp R&D division.",
    "doc4": "Peter Gibbons works for Initech Ltd.",  # 对照：走原有 WORKS_FOR 语义
}

# 语料中的实体（无 spaCy 环境下手动标注；装 spaCy 后可由 NER 自动产出）
ENTITIES = {
    "doc1": [("Alice Chen", "PERSON"), ("Data Science team", "TEAM"),
             ("Acme Corp", "ORG")],
    "doc2": [("Bob Lee", "PERSON"), ("Finance department", "TEAM"),
             ("Globex", "ORG")],
    "doc3": [("Data Science team", "TEAM"), ("Acme Corp R&D division", "ORG")],
    "doc4": [("Peter Gibbons", "PERSON"), ("Initech Ltd", "ORG")],
}


def build_entities(doc_id: str):
    """把 (text, label) 列表转为 semantica 的 Entity（记录字符偏移供抽取用）。"""
    from semantica.semantic_extract.types import Entity

    text = DOCS[doc_id]
    out = []
    for name, label in ENTITIES[doc_id]:
        start = text.find(name)
        out.append(Entity(text=name, label=label,
                          start_char=start, end_char=start + len(name),
                          confidence=0.9))
    return out


def main() -> None:
    banner("BELONGS_TO 关系扩展与使用全链路示例")

    # -------------------------------------------------------------------
    step("1. 枚举扩展：ExtendedRelationshipType（13 + 1 = 14 个成员）")
    # -------------------------------------------------------------------
    print(f"  BELONGS_TO = {BELONGS_TO!r}")
    print(f"  枚举成员数: {len(list(ExtendedRelationshipType))}")
    print(f"  字符串等值: {BELONGS_TO == ExtendedRelationshipType.BELONGS_TO}")

    # -------------------------------------------------------------------
    step("2. 抽取层：自定义正则抽 BELONGS_TO（belongs to / part of 两种句式）")
    # -------------------------------------------------------------------
    from semantica.semantic_extract.methods import extract_relations_regex

    belongs_patterns = {
        "BELONGS_TO": [
            # "X belongs to [the] Y (at Z)." —— object 贪婪匹配但遇 "at" 停（负向前瞻）
            r"(?:the\s+)?(?P<subject>\w+(?:\s\w+)*)\s+belongs\s+to\s+(?:the\s+)?(?P<object>\w+(?:\s(?!at\b)[\w&]+)*)",
        ],
        "WORKS_FOR": [  # 对照：同时保留一个原有谓词（贪婪匹配到句号前，避免漏掉多词实体）
            r"(?P<subject>\w+(?:\s\w+)*)\s+works\s+for\s+(?P<object>\w+(?:\s\w+)*)",
        ],
    }

    all_rels = []
    for doc_id in DOCS:
        ents = build_entities(doc_id)
        rels = extract_relations_regex(DOCS[doc_id], ents, patterns=belongs_patterns)
        for r in rels:
            # extract_relations_regex 内部按 entity_map 小写精确匹配，
            # group 文本与实体文本不一致的关系会被自动过滤
            rec = {"subject": r.subject.text, "predicate": r.predicate,
                   "object": r.object.text, "source": doc_id,
                   "confidence": r.confidence}
            all_rels.append(rec)
            print(f"    {rec['subject']} --[{rec['predicate']}]--> {rec['object']} "
                  f"(conf={rec['confidence']}, src={doc_id})")

    # -------------------------------------------------------------------
    step("3. 图层：BELONGS_TO 边写入 ContextGraph")
    # -------------------------------------------------------------------
    from semantica.context import ContextGraph

    g = ContextGraph()
    # 装载实体节点
    seen = set()
    for doc_id, ents in ENTITIES.items():
        for name, label in ents:
            if name not in seen:
                g.add_node(name, label, name=name)
                seen.add(name)
    # 装载关系边（BELONGS_TO / WORKS_FOR）
    for rec in all_rels:
        if rec["subject"] in seen and rec["object"] in seen:
            g.add_edge(rec["subject"], rec["object"],
                       edge_type=rec["predicate"],  # 直接放 BELONGS_TO
                       source=rec["source"], confidence=rec["confidence"])
    print(f"  图节点 {len(seen)} 个；写入 {len(all_rels)} 条边（含 BELONGS_TO）")

    # -------------------------------------------------------------------
    step("4. 查询：沿 BELONGS_TO 遍历（成员→所属组织，2 跳可达公司）")
    # -------------------------------------------------------------------
    print("  Alice Chen 的 2 跳邻居:")
    for n in g.get_neighbors("Alice Chen", hops=2):
        print(f"    Alice Chen -[{n['relationship']}]-> {n['id']}  (hop={n['hop']})")

    print("  Data Science team 的 1 跳邻居:")
    for n in g.get_neighbors("Data Science team", hops=1):
        print(f"    Data Science team -[{n['relationship']}]-> {n['id']}")

    # -------------------------------------------------------------------
    step("5. 导出：RDF Turtle（BELONGS_TO 成为 RDF 谓词）")
    # -------------------------------------------------------------------
    from semantica.export import RDFExporter

    kg = g.to_kg_dict()
    RDFExporter().export(kg, out_path("belongs_to_graph.ttl"), format="turtle")
    print(f"  已导出: {out_path('belongs_to_graph.ttl')}")

    # -------------------------------------------------------------------
    step("6. 本体层：BELONGS_TO 生成为 owl:ObjectProperty 并校验")
    # -------------------------------------------------------------------
    from semantica.ontology import OntologyGenerator, OntologyValidator

    ents_for_ont = [{"text": name, "label": label, "confidence": 0.9}
                    for ents in ENTITIES.values() for name, label in ents]
    rels_for_ont = [{"subject": r["subject"], "predicate": r["predicate"],
                     "object": r["object"], "confidence": r["confidence"]}
                    for r in all_rels]

    gen = OntologyGenerator(base_uri="https://james.local/ontology/")
    ont = gen.generate_ontology({"entities": ents_for_ont, "relationships": rels_for_ont})

    # OntologyGenerator 会把谓词名规范化收敛（如 BELONGS_TO -> relatedTo），
    # 手动注入保留原始 BELONGS_TO 语义的对象属性：
    ont.setdefault("properties", []).append({
        "name": "belongsTo",
        "label": "BELONGS_TO",
        "@type": "owl:ObjectProperty",
        "uri": "https://james.local/ontology/belongsTo",
        "domain": "PERSON",
        "range": "TEAM",
        "description": "Membership relation: a person or team belongs to a team or division",
    })
    props = [p.get("name") for p in ont.get("properties", [])]
    print(f"  本体属性 {len(props)} 个: {props}")
    print(f"  'belongsTo' (BELONGS_TO) 是否入本体: {'belongsTo' in props}")

    report = OntologyValidator().validate(ont)
    print(f"  本体校验: valid={report.valid}")

    RDFExporter().export({"entities": ents_for_ont}, out_path("belongs_to_ontology.ttl"),
                         format="turtle")
    print(f"  本体已导出: {out_path('belongs_to_ontology.ttl')}")

    print("\n[BELONGS_TO 扩展完成] 链路: 枚举定义 → 正则抽取 → 图建边 → BFS 查询 → RDF 导出 → 本体化校验")


if __name__ == "__main__":
    main()
