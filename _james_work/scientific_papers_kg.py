# -*- coding: utf-8 -*-
"""科学论文场景：用 semantica 构建实体关系知识图谱并生成可视化网页。

覆盖的实体类型（11 类）：
  论文 Paper / 作者 Author / 期刊 Journal / 杂志 Magazine / 会议 Conference /
  来源 Source / 学科 Discipline / 年份 Year / 批次 Batch / 语言 Language / 机构 Institution

覆盖的关系类型（10 类，扩展自 semantica 的 relationship 体系）：
  AUTHORED_BY        论文 -- 作者（作者撰写论文）
  AFFILIATED_WITH    作者 -- 机构（作者隶属机构）
  PUBLISHED_IN       论文 -- 期刊/杂志（发表于）
  PRESENTED_AT       论文 -- 会议（宣讲于）
  HAS_DISCIPLINE     论文 -- 学科（属于某学科）
  PUBLISHED_IN_YEAR  论文 -- 年份（发表年份）
  HAS_LANGUAGE       论文 -- 语言（撰写语言）
  HAS_SOURCE         论文 -- 来源（收录于某文献数据库）
  IN_BATCH           论文 -- 批次（数据批次）
  BELONGS_TO         期刊/杂志/会议 -- 学科（载体归属学科，可选）

流程（全程单机、无 LLM、无外部服务、可复现）：
  1. 内置 14 篇论文样例数据（含作者/机构/载体/学科/年份/语言/来源/批次）
  2. 扩展 relationship 枚举（str, Enum）
  3. 用 ContextGraph 建图（add_node + add_edge）
  4. 图分析：节点度数/中心性（networkx），实体类型分布（get_graph_summary）
  5. RDF Turtle 导出（RDFExporter + to_kg_dict）
  6. pyvis 交互式网页可视化（节点按类型着色、大小按度数、边标注关系）

运行：
  D:/_AllDocMap/06_Software/anaconda/python.exe scientific_papers_kg.py

产物（_james_work/output/）：
  scientific_papers.ttl    —— RDF 知识图谱
  scientific_papers.html   —— 交互式可视化网页（主交付物）
  scientific_papers_stats.txt —— 图统计与中心性摘要
"""

import os
from enum import Enum
from collections import defaultdict

import common  # noqa: F401  初始化 sys.path（加入 semantica 源码）
from common import banner, step, out_path

from semantica.context import ContextGraph
from semantica.export import RDFExporter

# ===========================================================================
# 1. 扩展 relationship 枚举（论文领域）
# ===========================================================================
class PaperRelation(str, Enum):
    AUTHORED_BY = "AUTHORED_BY"
    AFFILIATED_WITH = "AFFILIATED_WITH"
    PUBLISHED_IN = "PUBLISHED_IN"
    PRESENTED_AT = "PRESENTED_AT"
    HAS_DISCIPLINE = "HAS_DISCIPLINE"
    PUBLISHED_IN_YEAR = "PUBLISHED_IN_YEAR"
    HAS_LANGUAGE = "HAS_LANGUAGE"
    HAS_SOURCE = "HAS_SOURCE"
    IN_BATCH = "IN_BATCH"
    BELONGS_TO = "BELONGS_TO"


# ===========================================================================
# 2. 数据：作者 -> 机构
# ===========================================================================
AUTHORS = {
    "Alice Zhang": "Tsinghua University",
    "Bob Liu": "Peking University",
    "Carol Wang": "MIT",
    "David Chen": "Stanford University",
    "Elena Johnson": "Harvard University",
    "Fernando Garcia": "Stanford University",
    "Gita Patel": "Johns Hopkins University",
    "Hyun Kim": "Seoul National University",
    "Inho Park": "KAIST",
    "Jun Tanaka": "University of Tokyo",
    "Klaus Müller": "ETH Zurich",
    "Luca Rossi": "Politecnico di Milano",
    "Maria Bianchi": "Sapienza University",
    "Nicole Dupont": "Sorbonne University",
    "Oliver Smith": "IBM Research",
    "王伟": "中国农业大学",
    "李娜": "南京农业大学",
    "张强": "武汉大学",
    "刘洋": "中国科学院物理研究所",
    "Petr Novak": "Charles University",
    "Qasim Ahmad": "University of Oxford",
    "Rita Silva": "Imperial College London",
}

# ===========================================================================
# 3. 数据：论文（含全部元数据）
#    venue_type: journal / magazine / conference
# ===========================================================================
PAPERS = [
    {"title": "Graph Neural Networks for Molecular Property Prediction",
     "authors": ["Alice Zhang", "Bob Liu"],
     "venue": "Nature Machine Intelligence", "venue_type": "journal",
     "disciplines": ["Computer Science", "Chemistry"],
     "year": 2023, "language": "English", "source": "Scopus", "batch": "2024_Q1"},

    {"title": "Transformer-based Protein Structure Prediction",
     "authors": ["Carol Wang", "David Chen"],
     "venue": "Science", "venue_type": "journal",
     "disciplines": ["Biology", "Computer Science"],
     "year": 2024, "language": "English", "source": "Web of Science", "batch": "2024_Q1"},

    {"title": "Causal Inference in Observational Studies",
     "authors": ["Elena Johnson"],
     "venue": "Journal of the American Statistical Association", "venue_type": "journal",
     "disciplines": ["Statistics"],
     "year": 2021, "language": "English", "source": "Scopus", "batch": "2021_Q1"},

    {"title": "Large Language Models for Clinical Diagnosis",
     "authors": ["Fernando Garcia", "Gita Patel"],
     "venue": "New England Journal of Medicine", "venue_type": "journal",
     "disciplines": ["Medicine", "Computer Science"],
     "year": 2024, "language": "English", "source": "PubMed", "batch": "2024_Q1"},

    {"title": "Efficient Federated Learning over Heterogeneous Devices",
     "authors": ["Hyun Kim", "Inho Park"],
     "venue": "NeurIPS", "venue_type": "conference",
     "disciplines": ["Computer Science"],
     "year": 2022, "language": "English", "source": "DBLP", "batch": "2022_Q4"},

    {"title": "Robust Speech Recognition in Noisy Environments",
     "authors": ["Jun Tanaka"],
     "venue": "ICASSP", "venue_type": "conference",
     "disciplines": ["Computer Science"],
     "year": 2023, "language": "English", "source": "IEEE Xplore", "batch": "2023_Q2"},

    {"title": "Quantum Error Correction with Surface Codes",
     "authors": ["Klaus Müller"],
     "venue": "Physical Review Letters", "venue_type": "journal",
     "disciplines": ["Physics"],
     "year": 2022, "language": "English", "source": "Web of Science", "batch": "2022_Q2"},

    {"title": "Deep Reinforcement Learning for Autonomous Driving",
     "authors": ["Luca Rossi", "Maria Bianchi"],
     "venue": "CVPR", "venue_type": "conference",
     "disciplines": ["Computer Science"],
     "year": 2023, "language": "English", "source": "DBLP", "batch": "2023_Q2"},

    {"title": "A Survey of Knowledge Graph Embedding Methods",
     "authors": ["Nicole Dupont"],
     "venue": "IEEE Transactions on Knowledge and Data Engineering", "venue_type": "journal",
     "disciplines": ["Computer Science"],
     "year": 2021, "language": "English", "source": "Scopus", "batch": "2021_Q2"},

    {"title": "气候变化对农业生产的影响",
     "authors": ["王伟", "李娜"],
     "venue": "中国农业科学", "venue_type": "journal",
     "disciplines": ["农学", "环境科学"],
     "year": 2020, "language": "中文", "source": "CNKI", "batch": "2020_Q4"},

    {"title": "The Road to Practical Quantum Advantage",
     "authors": ["Oliver Smith"],
     "venue": "Communications of the ACM", "venue_type": "magazine",
     "disciplines": ["Computer Science", "Physics"],
     "year": 2023, "language": "English", "source": "Scopus", "batch": "2023_Q3"},

    {"title": "低温超导材料研究进展",
     "authors": ["刘洋"],
     "venue": "物理", "venue_type": "magazine",
     "disciplines": ["物理学"],
     "year": 2022, "language": "中文", "source": "CNKI", "batch": "2022_Q1"},

    {"title": "Federated Graph Learning for Privacy-Preserving Analytics",
     "authors": ["Petr Novak"],
     "venue": "KDD", "venue_type": "conference",
     "disciplines": ["Computer Science"],
     "year": 2024, "language": "English", "source": "DBLP", "batch": "2024_Q2"},

    {"title": "Metaverse and Human-Computer Interaction",
     "authors": ["Qasim Ahmad", "Rita Silva"],
     "venue": "IEEE Spectrum", "venue_type": "magazine",
     "disciplines": ["Computer Science"],
     "year": 2024, "language": "English", "source": "IEEE Xplore", "batch": "2024_Q2"},

    {"title": "基于深度学习的遥感图像分类方法",
     "authors": ["张强"],
     "venue": "测绘学报", "venue_type": "journal",
     "disciplines": ["遥感科学"],
     "year": 2023, "language": "中文", "source": "CNKI", "batch": "2023_Q1"},
]


def _slug(prefix: str, text: str) -> str:
    """生成稳定、无空格的节点 ID。"""
    return f"{prefix}_{text.strip().lower().replace(' ', '_').replace('&', 'and')}"


# 节点类型标签（可视化图例用）
TYPE_LABEL = {
    "Paper": "论文", "Author": "作者", "Journal": "期刊", "Magazine": "杂志",
    "Conference": "会议", "Institution": "机构", "Discipline": "学科",
    "Year": "年份", "Batch": "批次", "Language": "语言", "Source": "来源",
}

# 节点类型配色（低饱和 Okabe-Ito 系色板，亮度统一、沉稳，拒绝高饱和撞色）
TYPE_COLOR = {
    "Paper":       "#D55E00",  # 朱红 —— 图中主角
    "Author":      "#0072B2",  # 蓝
    "Journal":     "#009E73",  # 蓝绿
    "Magazine":    "#56B4E9",  # 天蓝
    "Conference":  "#CC79A7",  # 紫红
    "Institution": "#E69F00",  # 橙
    "Discipline":  "#B8860B",  # 深金褐
    "Year":        "#8A8F98",  # 石板灰
    "Batch":       "#66C2A5",  # 浅绿
    "Language":    "#8DA0CB",  # 浅蓝紫
    "Source":      "#FC8D62",  # 浅橙
}

# 关系类型中文名（图例用）
REL_LABEL = {
    "AUTHORED_BY": "作者撰写", "AFFILIATED_WITH": "机构隶属",
    "PUBLISHED_IN": "发表于", "PRESENTED_AT": "宣讲于",
    "HAS_DISCIPLINE": "学科", "PUBLISHED_IN_YEAR": "年份",
    "HAS_LANGUAGE": "语言", "HAS_SOURCE": "来源", "IN_BATCH": "批次",
}

# 边配色：统一弱化为柔和灰，仅“作者↔论文 / 作者↔机构”两条关键关系略深，
# 让节点（尤其是论文）成为唯一视觉焦点，关系类型交给文字 label 表达。
EDGE_DEFAULT = "#C7D0DA"
REL_COLOR = {
    "AUTHORED_BY": "#8FA6BC",
    "AFFILIATED_WITH": "#8FA6BC",
}


def build_graph():
    """用 ContextGraph 构建科学论文知识图谱。返回 (graph, 节点/边清单)。"""
    g = ContextGraph()
    # 记录 (node_id, type, display_name) 与边 (src_id, dst_id, rel)
    nodes = {}      # node_id -> (type, label)
    edges = []      # (src_id, dst_id, rel)

    def add_node(nid, ntype, label):
        # content 会导出为 RDF 的 semantica:text（可读名），name 留作属性
        g.add_node(nid, ntype, content=label, name=label)
        nodes[nid] = (ntype, label)

    # 机构 + 作者
    for author, inst in AUTHORS.items():
        iid = _slug("inst", inst)
        add_node(iid, "Institution", inst)
        aid = _slug("author", author)
        add_node(aid, "Author", author)
        g.add_edge(aid, iid, edge_type=PaperRelation.AFFILIATED_WITH.value)
        edges.append((aid, iid, "AFFILIATED_WITH"))

    # 论文及其关系
    for idx, p in enumerate(PAPERS, 1):
        pid = _slug("paper", f"{idx}_{p['title']}")
        add_node(pid, "Paper", p["title"])

        # 作者
        for a in p["authors"]:
            aid = _slug("author", a)
            g.add_edge(pid, aid, edge_type=PaperRelation.AUTHORED_BY.value)
            edges.append((pid, aid, "AUTHORED_BY"))

        # 载体（期刊/杂志/会议）
        vtype = {"journal": "Journal", "magazine": "Magazine",
                 "conference": "Conference"}[p["venue_type"]]
        vid = _slug("venue", p["venue"])
        add_node(vid, vtype, p["venue"])
        rel = PaperRelation.PRESENTED_AT.value if vtype == "Conference" \
            else PaperRelation.PUBLISHED_IN.value
        g.add_edge(pid, vid, edge_type=rel)
        edges.append((pid, vid, rel))

        # 学科
        for d in p["disciplines"]:
            did = _slug("disc", d)
            add_node(did, "Discipline", d)
            g.add_edge(pid, did, edge_type=PaperRelation.HAS_DISCIPLINE.value)
            edges.append((pid, did, "HAS_DISCIPLINE"))

        # 年份
        yid = _slug("year", str(p["year"]))
        add_node(yid, "Year", str(p["year"]))
        g.add_edge(pid, yid, edge_type=PaperRelation.PUBLISHED_IN_YEAR.value)
        edges.append((pid, yid, "PUBLISHED_IN_YEAR"))

        # 语言
        lid = _slug("lang", p["language"])
        add_node(lid, "Language", p["language"])
        g.add_edge(pid, lid, edge_type=PaperRelation.HAS_LANGUAGE.value)
        edges.append((pid, lid, "HAS_LANGUAGE"))

        # 来源
        sid = _slug("src", p["source"])
        add_node(sid, "Source", p["source"])
        g.add_edge(pid, sid, edge_type=PaperRelation.HAS_SOURCE.value)
        edges.append((pid, sid, "HAS_SOURCE"))

        # 批次
        bid = _slug("batch", p["batch"])
        add_node(bid, "Batch", p["batch"])
        g.add_edge(pid, bid, edge_type=PaperRelation.IN_BATCH.value)
        edges.append((pid, bid, "IN_BATCH"))

    return g, nodes, edges


def build_networkx(nodes, edges):
    """把节点/边清单转成 networkx 图（供可视化与中心性计算）。"""
    import networkx as nx
    G = nx.DiGraph()
    for nid, (ntype, label) in nodes.items():
        G.add_node(nid, type=ntype, label=label)
    for s, t, rel in edges:
        G.add_edge(s, t, relation=rel)
    return G


def main() -> None:
    banner("科学论文场景：semantica 实体关系知识图谱 + 可视化网页")

    step("1. 构建知识图谱（ContextGraph）")
    graph, nodes, edges = build_graph()
    summary = graph.get_graph_summary()
    print(f"  节点总数: {summary['nodes']}   边总数: {summary['edges']}")
    for t, c in sorted(summary["node_types"].items(), key=lambda x: -x[1]):
        print(f"    {t:<12} {TYPE_LABEL.get(t, t):<4} {c} 个")
    print("  关系类型分布:")
    for t, c in sorted(summary["edge_types"].items(), key=lambda x: -x[1]):
        print(f"    {t:<20} {c} 条")

    step("2. 图分析（度数 / 中心性，networkx）")
    G = build_networkx(nodes, edges)
    import networkx as nx
    degree = dict(G.degree())
    # 按度数取最重要的前 8 个节点
    top = sorted(degree.items(), key=lambda x: -x[1])[:8]
    print("  度数 Top8（图中心节点）:")
    for nid, d in top:
        ntype, label = nodes[nid]
        print(f"    {label:<48} [{TYPE_LABEL.get(ntype, ntype)}] 度={d}")

    step("3. RDF Turtle 导出（RDFExporter）")
    kg = graph.to_kg_dict()
    RDFExporter().export(kg, out_path("scientific_papers.ttl"), format="turtle")
    print(f"  已导出: {out_path('scientific_papers.ttl')}")

    step("4. 生成交互式可视化网页（pyvis）")
    html_path = render_pyvis(G, nodes, degree, top)
    print(f"  已生成: {html_path}")

    step("5. 写图统计摘要")
    stats_path = out_path("scientific_papers_stats.txt")
    with open(stats_path, "w", encoding="utf-8") as f:
        f.write("Scientific Papers Knowledge Graph — Statistics\n")
        f.write("=" * 56 + "\n\n")
        f.write(f"Nodes: {summary['nodes']}  Edges: {summary['edges']}\n\n")
        f.write("Entity type distribution:\n")
        for t, c in sorted(summary["node_types"].items(), key=lambda x: -x[1]):
            f.write(f"  {t:<12} {TYPE_LABEL.get(t, t):<6} {c}\n")
        f.write("\nRelationship type distribution:\n")
        for t, c in sorted(summary["edge_types"].items(), key=lambda x: -x[1]):
            f.write(f"  {t:<20} {c}\n")
        f.write("\nTop nodes by degree:\n")
        for nid, d in top:
            ntype, label = nodes[nid]
            f.write(f"  {label:<48} [{TYPE_LABEL.get(ntype, ntype)}] {d}\n")
    print(f"  已生成: {stats_path}")

    print("\n[完成] 打开 output/scientific_papers.html 交互浏览图谱；")
    print("       ttl 为 RDF 图、txt 为统计摘要。")


def render_pyvis(G, nodes, degree, top_nodes) -> str:
    """用 pyvis 渲染交互式网页：节点按类型着色（低饱和）、大小按度数，边弱化为灰。"""
    from pyvis.network import Network

    net = Network(height="760px", width="100%", directed=True,
                  bgcolor="#fafafa", font_color="#3a3a3a")
    net.set_options("""
    {
      "physics": {
        "solver": "forceAtlas2Based",
        "forceAtlas2Based": { "gravity": -80, "centralGravity": 0.008,
                              "springLength": 110, "springStrength": 0.06 },
        "stabilization": { "iterations": 220 }
      },
      "interaction": { "hover": true, "tooltipDelay": 120 }
    }
    """)

    # 节点：按类型着色、按度数设大小，统一白描边
    max_deg = max(degree.values()) if degree else 1
    for nid, data in G.nodes(data=True):
        ntype = data["type"]
        label = data["label"]
        size = 9 + 20 * (degree.get(nid, 1) / max_deg)
        net.add_node(nid, label=label,
                     title=f"{label}\n类型: {TYPE_LABEL.get(ntype, ntype)}\n度数: {degree.get(nid, 0)}",
                     color={"background": TYPE_COLOR.get(ntype, "#9aa0a6"),
                            "border": "#ffffff", "highlight": {"background": TYPE_COLOR.get(ntype, "#9aa0a6"), "border": "#ffffff"}},
                     size=size,
                     font={"color": "#3a3a3a", "size": 13})

    # 边：统一浅灰，仅关键关系略深；关系类型用文字 label 表达
    for s, t, data in G.edges(data=True):
        rel = data["relation"]
        c = REL_COLOR.get(rel, EDGE_DEFAULT)
        w = 2.0 if rel in REL_COLOR else 1.2
        net.add_edge(s, t, label=REL_LABEL.get(rel, rel),
                     title=f"{s}  --[{rel}]-->  {t}",
                     color=c, width=w, arrows="to",
                     font={"color": "#9aa0a6", "size": 10, "background": "#ffffff",
                           "strokeWidth": 0})

    html_path = out_path("scientific_papers.html")
    net.save_graph(html_path)

    # 注入标题区 + 图例
    with open(html_path, "r", encoding="utf-8") as f:
        html = f.read()
    overlay = _build_overlay(summary_stats(nodes, G))
    html = html.replace("</body>", overlay + "</body>")
    with open(html_path, "w", encoding="utf-8") as f:
        f.write(html)
    return html_path


def summary_stats(nodes, G) -> dict:
    """统计信息，供标题区展示。"""
    from collections import Counter
    type_counts = Counter(v[0] for v in nodes.values())
    n_papers = type_counts.get("Paper", 0)
    n_authors = type_counts.get("Author", 0)
    n_edges = G.number_of_edges()
    return {"nodes": len(nodes), "edges": n_edges,
            "papers": n_papers, "authors": n_authors}


def _build_overlay(st) -> str:
    """标题区 + 分组图例（克制配色、清晰层次、充足留白）。"""
    node_items = "".join(
        f'<span class="lg"><i style="background:{c}"></i>{TYPE_LABEL.get(t, t)}</span>'
        for t, c in TYPE_COLOR.items()
    )
    rel_items = "".join(
        f'<span class="lg">{REL_LABEL.get(r, r)}</span>' for r in REL_LABEL
    )
    return f"""
<div class="overlay">
  <div class="ov-title">科学论文知识图谱</div>
  <div class="ov-sub">Scientific Papers Knowledge Graph</div>
  <div class="ov-rule"></div>
  <div class="ov-stats">
    {st['nodes']} 节点 · {st['edges']} 边 · {st['papers']} 篇论文 · {st['authors']} 位作者
  </div>
  <div class="ov-group">节点类型</div>
  <div class="ov-chips">{node_items}</div>
  <div class="ov-group">关系类型</div>
  <div class="ov-chips">{rel_items}</div>
</div>
<style>
  .overlay {{
    position:fixed; top:18px; left:18px; z-index:10;
    background:#fffffff2; border:1px solid #e8e8ea; border-radius:12px;
    padding:18px 20px; max-width:340px;
    font-family:-apple-system,"Segoe UI","PingFang SC","Microsoft YaHei",sans-serif;
    box-shadow:0 1px 2px rgba(0,0,0,.04);
  }}
  .ov-title {{ font-size:20px; font-weight:650; color:#1a1a1a; letter-spacing:.5px; }}
  .ov-sub  {{ font-size:11px; color:#9aa0a6; letter-spacing:1.2px; text-transform:uppercase; margin-top:3px; }}
  .ov-rule {{ height:1px; background:#eee; margin:14px 0 12px; }}
  .ov-stats{{ font-size:12px; color:#6b7280; line-height:1.5; }}
  .ov-group{{ font-size:10px; color:#b0b4ba; letter-spacing:1.5px; text-transform:uppercase; margin:16px 0 8px; }}
  .ov-chips{{ display:flex; flex-wrap:wrap; gap:7px 10px; }}
  .lg {{ display:inline-flex; align-items:center; gap:5px; font-size:12px; color:#4a4a4a; }}
  .lg i {{ width:10px; height:10px; border-radius:50%; display:inline-block; }}
</style>
"""


if __name__ == "__main__":
    main()
