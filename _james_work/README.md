# _james_work — semantica 三种应用场景（单机实现）

基于本机源码 `D:\_AllDocMap\02_Project\github\semantica` 实现的三个应用场景演示。
**全部单机运行**：不依赖 Neo4j/Qdrant 等外部服务，不调用云 LLM API。

## 运行方式

```bash
# 用已配置好的 Python 环境（依赖已装齐）
cd D:\_AllDocMap\02_Project\github\semantica\_james_work

# 一键运行全部三个场景
python run_all.py

# 用本机 Anaconda Python（依赖已装齐：rdflib/networkx/loguru/structlog 等）
D:\_AllDocMap\06_Software\anaconda\python.exe run_all.py

# 或单独运行某个场景
python scenario1_decision_intelligence.py
python scenario2_aml_rules_engine.py
python scenario3_doc_to_kg_pipeline.py
```

> 说明：以下两个 Python 环境均已验证可运行——
> 1. `D:\_AllDocMap\06_Software\anaconda\python.exe`（3.12.7，已补装 rdflib 等缺失依赖）
> 2. `C:\Users\jiangqian\.workbuddy-ai\binaries\python\envs\default\Scripts\python.exe`
> （含 gensim、fastembed，`find_similar_decisions` 语义检索效果更好）。

## 三个场景

| 场景 | 文件 | semantica 能力 |
| --- | --- | --- |
| **1. 决策智能与可审计决策链** | `scenario1_decision_intelligence.py` | ContextGraph、决策记录、因果溯源（trace_decision_chain）、判例检索（find_similar_decisions）、影响分析、合规门、ProvenanceManager（W3C PROV-O）、RDFExporter |
| **2. AML 反洗钱规则引擎** | `scenario2_aml_rules_engine.py` | ReteEngine 规则网络（受制裁地区/大额交易筛查）、DatalogReasoner 递归推理（资金多跳流向追踪）、命中结果落图成可审计决策 |
| **3. 文档 → 知识图谱 → 本体 → RDF** | `scenario3_doc_to_kg_pipeline.py` | FileIngestor 目录摄取、TextSplitter 实体感知分块、NER/关系抽取、GraphBuilder 实体合并建图、OntologyGenerator/Validator、RDF 导出、ContextGraph BFS 查询 |

## 共享配置

`common.py` 负责把 semantica 源码目录加入 `sys.path`（无需 pip install），
所有产物统一写到 `output/` 目录。

## 输出产物（output/）

- `audit_prov.db` / `audit_provenance.ttl` — 场景 1 的 PROV-O 审计痕迹与溯源库
- `audit_trail.ttl` — 场景 1 的决策图 RDF（监管提交格式）
- `aml_report.txt` — 场景 2 的可解释 AML 筛查报告
- `corpus/` — 场景 3 的模拟合同语料（3 个 txt）
- `knowledge_graph.ttl` / `ontology.ttl` — 场景 3 的 KG 与本体 RDF

## 已知事项

- 未安装 spaCy，NER 自动回退到内置模式抽取（无外部模型依赖，纯本地），
  关系抽取结果有噪音（大量 `related_to`），属预期降级行为。
- fastembed 本地 ONNX 嵌入模型首次运行会下载约 30MB 模型文件（有缓存后离线可用）。
- Rete 条件匹配基于 fact 字符串模式（`predicate(arg...)`），README 也声明了
  该匹配器当前版本较简单，生产合规门需自行校验。
