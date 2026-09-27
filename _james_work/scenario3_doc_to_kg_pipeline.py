# -*- coding: utf-8 -*-
"""场景 3：本地文档 -> 知识图谱 -> 本体 -> RDF（Ketchup 到 KG 的全流水线）

对应 semantica 的 "Knowledge Pipeline" 应用场景：
多源文档摄取 -> NER 实体抽取 -> 关系抽取 -> 知识图谱构建（实体合并）
-> 本体生成与校验 -> RDF 导出。外加实体感知分块（GraphRAG 前置）。

演示内容（全部单机运行，无 LLM、无外部服务）：
1. 在本地创建模拟"合同文档"语料（纯本地 txt 文件）
2. FileIngestor 摄取目录
3. TextSplitter 实体感知分块（不把实体切在两半）
4. NamedEntityRecognizer + RelationExtractor 抽取实体与关系
   （spaCy 未安装时自动回退到内置模式抽取，依旧可用）
5. GraphBuilder 构建知识图谱（跨文档实体合并）
6. OntologyGenerator 从抽取结果生成本体，OntologyValidator 校验
7. RDFExporter 导出 KG 与本体为 Turtle
8. ContextGraph 可视化查询：BFS 遍历 + 2 跳邻居

运行：python scenario3_doc_to_kg_pipeline.py
"""

import os

import common  # noqa: F401
from common import banner, step, out_path, OUTPUT_DIR

from semantica.ingest import FileIngestor
from semantica.split import TextSplitter
from semantica.semantic_extract import NamedEntityRecognizer, RelationExtractor
from semantica.kg import GraphBuilder
from semantica.ontology import OntologyGenerator, OntologyValidator
from semantica.export import RDFExporter
from semantica.context import ContextGraph

# 模拟合同语料（写入本地目录，展示真实文件摄取流程）
CORPUS = {
    "doc1_contract_acme_globex.txt": (
        "Alice Chen is CTO of Acme Corp. Acme Corp signed a contract with Globex. "
        "The contract value is 2.4 million USD. Alice Chen approved the renewal in Q1 2024."
    ),
    "doc2_contract_bob_globex.txt": (
        "Bob Lee works at Globex as CFO. Globex and Acme Corp are partners. "
        "Bob Lee approved the invoice for 300000 USD."
    ),
    "doc3_press_initech.txt": (
        "Initech Ltd signed a partnership with Acme Corp in March 2024. "
        "Peter Gibbons is a consultant for Initech Ltd."
    ),
}


def create_corpus() -> str:
    """在输出目录下生成模拟合同文件。"""
    corpus_dir = os.path.join(OUTPUT_DIR, "corpus")
    os.makedirs(corpus_dir, exist_ok=True)
    for fname, text in CORPUS.items():
        with open(os.path.join(corpus_dir, fname), "w", encoding="utf-8") as f:
            f.write(text)
    return corpus_dir


def main() -> None:
    banner("场景 3：本地文档 -> 知识图谱 -> 本体 -> RDF 全流水线")

    # ---------------------------------------------------------------
    step("1. 生成本地模拟合同语料")
    # ---------------------------------------------------------------
    corpus_dir = create_corpus()
    print(f"  语料目录: {corpus_dir}  ({len(CORPUS)} 个文件)")

    # ---------------------------------------------------------------
    step("2. FileIngestor 摄取目录")
    # ---------------------------------------------------------------
    docs = FileIngestor().ingest_directory(corpus_dir, recursive=True)
    print(f"  摄取文档数: {len(docs)}")
    for d in docs:
        print(f"    - {d.name}  ({len(_doc_text(d))} chars)")

    run_pipeline(docs)


def _doc_text(d) -> str:
    """兼容 FileObject.text / content(bytes) 两种形式取出文本。"""
    text = getattr(d, "text", None) or ""
    if not text:
        content = getattr(d, "content", None)
        if content:
            text = content.decode("utf-8", errors="ignore") if isinstance(content, bytes) else str(content)
    return text


def run_pipeline(docs):
    # ---------------------------------------------------------------
    step("3. 实体感知分块（GraphRAG 前置）")
    # ---------------------------------------------------------------
    splitter = TextSplitter(method="entity_aware", chunk_size=200)
    n_chunks = 0
    for d in docs:
        chunks = splitter.split(_doc_text(d))
        n_chunks += len(chunks)
    print(f"  分块总数: {n_chunks}  (实体不跨块边界)")

    # ---------------------------------------------------------------
    step("4. NER + 关系抽取")
    # ---------------------------------------------------------------
    ner = NamedEntityRecognizer(confidence_threshold=0.5)
    rel_ext = RelationExtractor(confidence_threshold=0.3)

    sources = []
    all_entity_dicts = []
    for i, d in enumerate(docs):
        text = _doc_text(d)
        src = getattr(d, "name", f"doc{i}")
        ents = ner.extract_entities(text)
        rels = rel_ext.extract_relations(text, ents)

        ent_dicts = [
            {"id": f"doc{i}_e{j}", "text": e.text, "label": e.label,
             "confidence": e.confidence, "source": src}
            for j, e in enumerate(ents)
        ]
        rel_dicts = [
            {"subject": r.subject.text, "predicate": r.predicate,
             "object": r.object.text, "confidence": r.confidence, "source": src}
            for r in rels
        ]
        sources.append({
            "id": f"doc{i}", "title": getattr(d, "name", f"Doc {i}"),
            "text": text, "source": src,
            "entities": ent_dicts, "relationships": rel_dicts,
        })
        all_entity_dicts.append((src, ent_dicts, rel_dicts))
        print(f"    {os.path.basename(str(src))}: 实体 {len(ent_dicts)} 个 / 关系 {len(rel_dicts)} 条")

    # ---------------------------------------------------------------
    step("5. GraphBuilder 构建知识图谱（跨文档实体合并）")
    # ---------------------------------------------------------------
    kg = GraphBuilder(merge_entities=True, enable_temporal=True).build(sources)
    kg_ents = kg.get("entities", [])
    kg_rels = kg.get("relationships", [])
    print(f"  KG 实体: {len(kg_ents)}  关系: {len(kg_rels)}")
    for r in kg_rels:
        print(f"    R: {r.get('subject')} --{r.get('predicate')}--> {r.get('object', r.get('target'))}")

    # ---------------------------------------------------------------
    step("6. 本体生成 + SHACL 风格校验")
    # ---------------------------------------------------------------
    flat_entities = [e for _, ents, _ in all_entity_dicts for e in ents]
    flat_rels = [r for _, _, rels in all_entity_dicts for r in rels]
    gen = OntologyGenerator(base_uri="https://james.local/ontology/")
    ont = gen.generate_ontology({"entities": flat_entities, "relationships": flat_rels})
    print(f"  本体类: {len(ont.get('classes', []))}  属性: {len(ont.get('properties', []))}")

    validator = OntologyValidator()
    report = validator.validate(ont)
    print(f"  本体校验: valid={report.valid}")
    if not report.valid:
        for issue in (report.issues or [])[:5]:
            print(f"    issue: {issue}")

    # ---------------------------------------------------------------
    step("7. 导出 KG 与本体为 RDF Turtle")
    # ---------------------------------------------------------------
    RDFExporter().export(kg, out_path("knowledge_graph.ttl"), format="turtle")
    RDFExporter().export(
        {"entities": flat_entities}, out_path("ontology.ttl"), format="turtle"
    )
    print(f"  KG 已导出: {out_path('knowledge_graph.ttl')}")
    print(f"  本体已导出: {out_path('ontology.ttl')}")

    # ---------------------------------------------------------------
    step("8. 图查询：BFS 遍历 + 2 跳邻居")
    # ---------------------------------------------------------------
    cg = ContextGraph(advanced_analytics=True)
    # 把 KG 实体与关系装载进 ContextGraph 做交互式查询
    for e in kg_ents:
        eid = e.get("id") or e.get("text")
        if eid:
            cg.add_node(eid, e.get("label") or "Entity", name=e.get("text", eid))
    for r in kg_rels:
        subj, obj = r.get("subject"), r.get("object", r.get("target"))
        if subj and obj:
            try:
                cg.add_edge(subj, obj, edge_type=r.get("predicate", "related_to"),
                            source=r.get("source"))
            except Exception:
                pass  # 端点不在图中时跳过（pattern 抽取偶发）

    neighbors = cg.get_neighbors("Acme Corp", hops=2)
    print(f"  'Acme Corp' 的 2 跳邻居:")
    if isinstance(neighbors, dict):
        for nid, info in list(neighbors.items())[:10]:
            print(f"    - {nid}  {info if isinstance(info, str) else ''}")
    elif isinstance(neighbors, list):
        for n in neighbors[:10]:
            print(f"    - {n}")

    print("\n[场景 3 完成] 产物在 _james_work/output/ 下：corpus/ knowledge_graph.ttl ontology.ttl")


if __name__ == "__main__":
    main()
