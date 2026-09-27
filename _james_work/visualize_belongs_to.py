# -*- coding: utf-8 -*-
"""可视化 belongs_to_ontology.ttl（以及同目录的 belongs_to_graph.ttl）。

提供两种可视化方式（均纯单机，无需服务）：
1. 交互式 HTML（pyvis 力导向图）——推荐，浏览器打开可拖拽节点
   - 方式 1a：semantica 自带 OntologyVisualizer（interactive 输出）
   - 方式 1b：rdflib 解析 TTL -> networkx -> pyvis 自定义渲染（BELONGS_TO 高亮）
2. 静态 PNG（matplotlib）——适合嵌入文档/报告

运行：D:/_AllDocMap/06_Software/anaconda/python.exe visualize_belongs_to.py
产物（_james_work/output/ 下）：
- belongs_to_ontology_interactive.html  （semantica 官方可视化器）
- belongs_to_pyvis.html                 （自定义 pyvis 图，BELONGS_TO 高亮）
- belongs_to_ontology.png               （matplotlib 静态图）
"""

import common  # noqa: F401  初始化 sys.path
from common import banner, step, out_path, OUTPUT_DIR

import rdflib
import networkx as nx

TTL_ONTOLOGY = out_path("belongs_to_ontology.ttl")
TTL_GRAPH = out_path("belongs_to_graph.ttl")   # 含 BELONGS_TO 三元组，一起可视化

NS = rdflib.Namespace("https://semantica.dev/ns#")


def load_graph(ttl_path: str) -> rdflib.Graph:
    g = rdflib.Graph()
    g.parse(ttl_path, format="turtle")
    return g


def qname(uri) -> str:
    """把 IRI 缩短成可读标签（去掉命名空间前缀和解码 %20）。"""
    s = str(uri).replace(str(NS), "")
    return s.replace("%20", " ").replace("%26", "&") if s else str(uri)


# ---------------------------------------------------------------------------
# 方式 1a：semantica 官方 OntologyVisualizer（交互式 HTML）
# ---------------------------------------------------------------------------
def via_semantica_visualizer() -> None:
    from semantica.visualization import OntologyVisualizer

    viz = OntologyVisualizer()
    # 用 rdflib 图构建 ontology dict 供可视化器消费
    g = load_graph(TTL_ONTOLOGY)
    entities = []
    for s, p, o in g.triples((None, NS.text, None)):
        entities.append({"text": str(o), "label": "Entity", "confidence": 0.9})
    ontology = {
        "uri": "https://james.local/ontology/",
        "name": "BelongsTo Ontology",
        "classes": [{"name": "Entity", "description": "extracted entities"}],
        "properties": [
            {"name": "belongsTo", "label": "BELONGS_TO",
             "description": "membership relation", "domain": "PERSON", "range": "TEAM"},
        ],
        "imports": [], "metadata": {}, "entities": entities,
    }
    result = viz.visualize_semantic_model(
        semantic_model=ontology,
        output="interactive",
        file_path=out_path("belongs_to_ontology_interactive.html"),
    )
    print(f"  semantica 可视化器产物: {out_path('belongs_to_ontology_interactive.html')}")
    print(f"  返回: {type(result).__name__}" if result is not None else "  返回: None(已写文件)")


# ---------------------------------------------------------------------------
# 方式 1b：rdflib -> networkx -> pyvis（自定义高亮，完整展示所有 relationship）
# ---------------------------------------------------------------------------
# 图例配色
TYPE_COLOR = {"PERSON": "#3498db", "TEAM": "#1abc9c", "ORG": "#e67e22", "Entity": "#95a5a6"}
REL_COLOR = {"BELONGS_TO": "#e74c3c", "WORKS_FOR": "#2ecc71", "related_to": "#8e44ad"}


def via_pyvis() -> None:
    from pyvis.network import Network
    from collections import Counter

    g = load_graph(TTL_GRAPH)  # 只用含关系边的 graph.ttl，不混入 ontology 的哈希节点

    # 属性谓词（非关系边），其余谓词都视为 relationship
    ATTR_PREDS = {str(rdflib.RDF.type), str(NS.text), str(NS.confidence)}

    # 节点：IRI -> (可读名, 类型)
    names, types = {}, {}
    for s, _p, o in g.triples((None, rdflib.RDF.type, None)):
        names[str(s)] = qname(s)
        types[str(s)] = qname(o)
    for s, _p, o in g.triples((None, NS.text, None)):
        names[str(s)] = str(o)  # text 属性覆盖为可读名

    net = Network(height="650px", width="100%", directed=True,
                  bgcolor="#ffffff", font_color="#333333")
    net.set_options("""
    { "physics": { "solver": "forceAtlas2Based",
        "forceAtlas2Based": { "gravity": -60, "centralGravity": 0.01,
                              "springLength": 120, "springStrength": 0.05 },
        "stabilization": { "iterations": 200 } },
      "interaction": { "hover": true, "tooltipDelay": 120 } }
    """)

    # 节点（按类型着色）
    for iri, name in names.items():
        t = types.get(iri, "Entity")
        net.add_node(name, label=name, title=f"{name}\n类型: {t}",
                     color=TYPE_COLOR.get(t, "#95a5a6"), shape="dot", size=20)

    # 边：完整 relationship 作为 label 显示
    rel_counts = Counter()
    for s, p, o in g.triples((None, None, None)):
        if str(p) in ATTR_PREDS:
            continue
        rel = qname(p)  # 完整 relationship：BELONGS_TO / WORKS_FOR / ...
        subj = names.get(str(s), qname(s))
        obj = names.get(str(o), qname(o))
        c = REL_COLOR.get(rel, "#95a5a6")
        net.add_edge(subj, obj, label=rel,
                     title=f"{subj}  --[{rel}]-->  {obj}",
                     color=c, width=2.5, arrows="to",
                     font={"color": c, "size": 14, "background": "#ffffff",
                           "strokeWidth": 0})
        rel_counts[rel] += 1

    # physics 已在 net.set_options() 中配置（forceAtlas2Based），无需再调 force_atlas_2based
    html_path = out_path("belongs_to_pyvis.html")
    net.save_graph(html_path)

    # 注入图例（节点类型 + 关系类型）
    with open(html_path, "r", encoding="utf-8") as f:
        html = f.read()
    html = html.replace("</body>", _pyvis_legend(rel_counts) + "</body>")
    with open(html_path, "w", encoding="utf-8") as f:
        f.write(html)

    print(f"  pyvis 交互图产物: {html_path}")
    print(f"  关系边完整统计: {dict(rel_counts)}")


def _pyvis_legend(rel_counts) -> str:
    """构造叠加在图上的图例（节点类型 + 关系类型及条数）。"""
    node_items = "".join(
        f'<span class="li"><i style="background:{c}"></i>{t}</span>'
        for t, c in TYPE_COLOR.items()
    )
    rel_items = "".join(
        f'<span class="li"><i style="background:{REL_COLOR.get(r, "#95a5a6")};'
        f'height:4px;border-radius:2px"></i>{r} × {n}</span>'
        for r, n in sorted(rel_counts.items())
    )
    return f"""
<div style="position:fixed;top:16px;left:16px;z-index:10;background:#ffffffdd;
            padding:12px 15px;border-radius:10px;box-shadow:0 2px 10px #0002;
            font-family:-apple-system,Segoe UI,Microsoft YaHei,sans-serif;
            max-width:300px">
  <div style="font-size:14px;font-weight:700;margin-bottom:6px;color:#222">
    BELONGS_TO 关系图</div>
  <div style="font-size:12px;color:#555;margin-bottom:6px">节点类型</div>
  <div style="display:flex;flex-wrap:wrap;gap:8px;margin-bottom:10px">{node_items}</div>
  <div style="font-size:12px;color:#555;margin-bottom:6px">关系（边）</div>
  <div style="display:flex;flex-wrap:wrap;gap:8px">{rel_items}</div>
</div>
<style>
  .li {{ display:inline-flex;align-items:center;gap:4px;font-size:11px;color:#444 }}
  .li i {{ width:10px;height:10px;border-radius:50%;display:inline-block }}
</style>
"""


# ---------------------------------------------------------------------------
# 方式 2：matplotlib 静态 PNG（嵌入报告用）
# ---------------------------------------------------------------------------
def via_matplotlib() -> None:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    g = load_graph(TTL_GRAPH)  # 用含关系边的图

    # 节点：IRI -> 可读名
    names = {}
    for s, _p, o in g.triples((None, NS.text, None)):
        names[str(s)] = str(o)

    ATTR_PREDS = {str(rdflib.RDF.type), str(NS.text), str(NS.confidence)}
    G = nx.DiGraph()
    for s, p, o in g.triples((None, None, None)):
        if str(p) in ATTR_PREDS:
            continue  # 只保留关系谓词
        subj = names.get(str(s), qname(s))
        obj = names.get(str(o), qname(o))
        G.add_edge(subj, obj, label=qname(p))

    pos = nx.spring_layout(G, seed=42, k=1.2)
    plt.figure(figsize=(10, 7))

    edge_colors, edge_labels = [], {}
    for u, v, d in G.edges(data=True):
        lbl = d.get("label", "")
        edge_labels[(u, v)] = lbl
        edge_colors.append(REL_COLOR.get(lbl, "#95a5a6"))

    nx.draw_networkx_nodes(G, pos, node_color="#3498db", node_size=1600, alpha=0.85)
    nx.draw_networkx_labels(G, pos, font_size=8)
    nx.draw_networkx_edges(G, pos, edge_color=edge_colors,
                           arrows=True, arrowsize=18, width=2)
    nx.draw_networkx_edge_labels(G, pos, edge_labels=edge_labels, font_size=8)
    plt.title("BELONGS_TO / WORKS_FOR Relationship Graph")
    plt.axis("off")
    plt.tight_layout()
    png = out_path("belongs_to_ontology.png")
    plt.savefig(png, dpi=150, bbox_inches="tight")
    plt.close()
    print(f"  matplotlib 静态图产物: {png}")


def main() -> None:
    banner("可视化 belongs_to_ontology.ttl（+ belongs_to_graph.ttl）")

    step("方式 1a：semantica OntologyVisualizer（交互式 HTML）")
    try:
        via_semantica_visualizer()
    except Exception as e:
        print(f"  [跳过] {type(e).__name__}: {e}")

    step("方式 1b：rdflib -> networkx -> pyvis（BELONGS_TO 高亮交互图）")
    via_pyvis()

    step("方式 2：matplotlib 静态 PNG")
    via_matplotlib()

    print("\n[完成] 打开 output/ 下的 .html 文件即可交互浏览（拖拽/缩放/悬停看边）；")
    print("       .png 可直接嵌入文档。红色边 = BELONGS_TO 关系。")


if __name__ == "__main__":
    main()
