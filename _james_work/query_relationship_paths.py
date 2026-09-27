# -*- coding: utf-8 -*-
"""按「节点名称 + relationship + 跳数」在图谱中查找所有符合条件的节点，并打印完整路径。

功能：
  给定一个起点节点、一个 relationship（关系/边类型）和一个最大跳数，
  沿该 relationship 的边做有界遍历，找出所有 ≤ 跳数 内可达的节点，
  并打印从起点到每个目标节点的完整路径（含每一跳的关系方向）。

数据源：
  任意 RDF Turtle 图（semantica RDFExporter 导出的 ttl）。节点名优先取
  semantica:text 属性，其次取 IRI 尾段；边只取"关系谓词"（自动排除
  rdf:type / semantica:text / semantica:confidence 这类属性）。

用法：
  python query_relationship_paths.py \
      --graph output/belongs_to_graph.ttl \
      --start "Data Science team" \
      --relation BELONGS_TO \
      --hops 2 \
      --direction both

  --direction: out=沿出边 / in=沿入边 / both=双向（默认 both）

演示示例（在本项目 output 下）：
  # 1) belongs_to 图：从"数据科学团队"沿 BELONGS_TO 找 2 跳
  python query_relationship_paths.py --graph output/belongs_to_graph.ttl \
      --start "Data Science team" --relation BELONGS_TO --hops 2 --direction both

  # 2) 科学论文图：从作者 Alice Zhang 沿 AUTHORED_BY（反向）找其论文
  python query_relationship_paths.py --graph output/scientific_papers.ttl \
      --start "author_alice_zhang" --relation AUTHORED_BY --hops 1 --direction in
"""

import argparse
import sys

import common  # noqa: F401  初始化 sys.path
from common import out_path

import rdflib
import networkx as nx
from rdflib import Namespace, RDF

NS = Namespace("https://semantica.dev/ns#")


# ---------------------------------------------------------------------------
# 1. 从 ttl 加载为 networkx 有向图
# ---------------------------------------------------------------------------
def qname(uri) -> str:
    """把 IRI 缩短为可读标签（去命名空间、解码 %20 / %26）。"""
    s = str(uri)
    if s.startswith(str(NS)):
        s = s[len(str(NS)):]
    return s.replace("%20", " ").replace("%26", "&")


def load_graph_from_ttl(ttl_path: str) -> nx.DiGraph:
    """解析 ttl，返回带 relation 属性的 networkx 有向图。

    - 节点名：优先 semantica:text，其次 IRI 尾段（qname）
    - 边：只保留关系谓词（排除 rdf:type / text / confidence）
    """
    g = rdflib.Graph()
    g.parse(ttl_path, format="turtle")

    ATTR = {str(RDF.type), str(NS.text), str(NS.confidence)}

    names, types = {}, {}
    for s, _p, o in g.triples((None, RDF.type, None)):
        names[str(s)] = qname(s)
        types[str(s)] = qname(o)
    for s, _p, o in g.triples((None, NS.text, None)):
        names[str(s)] = str(o)

    G = nx.DiGraph()
    for s, p, o in g.triples((None, None, None)):
        if str(p) in ATTR:
            continue
        rel = qname(p)
        subj = names.get(str(s), qname(s))
        obj = names.get(str(o), qname(o))
        G.add_node(subj, type=types.get(str(s), "Entity"))
        G.add_node(obj, type=types.get(str(o), "Entity"))
        G.add_edge(subj, obj, relation=rel)
    return G


# ---------------------------------------------------------------------------
# 2. 核心：沿指定 relationship 的有界遍历，枚举所有简单路径
# ---------------------------------------------------------------------------
def _neighbors(G: nx.DiGraph, node, relation, direction):
    """返回 (邻接节点, 方向标记) 列表。方向标记 '->' 表示 node 是主语，
    '<-' 表示 node 是宾语（即反向沿边到达邻接节点）。"""
    out = []
    if direction in ("out", "both"):
        for nbr, data in G[node].items():
            if data.get("relation") == relation:
                out.append((nbr, "->"))
    if direction in ("in", "both"):
        for pred, data in G.pred[node].items():
            if data.get("relation") == relation:
                out.append((pred, "<-"))
    return out


def find_paths(G: nx.DiGraph, start, relation, max_hops, direction="both"):
    """从 start 出发，沿 relation 边，枚举所有 ≤ max_hops 跳的简单路径。

    返回列表，每项为 (节点序列, 方向序列)：
      - 节点序列 node_path: [start, n1, n2, ...]
      - 方向序列 arrow_path: arrow_path[i] 是 node_path[i] -> node_path[i+1]
        的方向，'->' 出边 / '<-' 入边（相对遍历前进方向而言，标注关系真实方向）
    """
    if max_hops < 1:
        return []
    results = []

    def dfs(node, node_path, arrow_path):
        if len(node_path) - 1 >= max_hops:  # 已达最大跳数
            return
        for nbr, arrow in _neighbors(G, node, relation, direction):
            if nbr in node_path:  # 避免环
                continue
            dfs(nbr, node_path + [nbr], arrow_path + [arrow])
            results.append((node_path + [nbr], arrow_path + [arrow]))

    dfs(start, [start], [])
    return results


# ---------------------------------------------------------------------------
# 3. 打印
# ---------------------------------------------------------------------------
def format_path(node_path, arrow_path, relation) -> str:
    """把节点序列 + 方向序列渲染成一行完整路径。"""
    parts = [node_path[0]]
    for i, arrow in enumerate(arrow_path):
        if arrow == "->":
            parts.append(f" -[{relation}]-> {node_path[i + 1]}")
        else:
            parts.append(f" <-[{relation}]- {node_path[i + 1]}")
    return "".join(parts)


def print_results(G, start, relation, max_hops, direction):
    paths = find_paths(G, start, relation, max_hops, direction)

    # 按跳数分组，去重目标节点
    targets = {}  # 目标节点 -> 首次路径
    for node_path, arrow_path in paths:
        target = node_path[-1]
        targets.setdefault(target, (node_path, arrow_path))

    print(f"\n起点节点   : {start}")
    print(f"关系类型   : {relation}")
    print(f"最大跳数   : {max_hops}   (方向: {direction})")
    print(f"符合条件的节点 : {len(targets)} 个")
    print("-" * 72)

    if not targets:
        print("  （未找到任何符合条件的节点）")
        return targets

    # 按跳数排序输出
    for target, (node_path, arrow_path) in sorted(
        targets.items(), key=lambda kv: (len(kv[1][0]) - 1, kv[0])
    ):
        hops = len(node_path) - 1
        ntype = G.nodes[target].get("type", "Entity")
        print(f"\n  [{hops} 跳] {target}  (类型: {ntype})")
        print(f"    完整路径: {format_path(node_path, arrow_path, relation)}")

    # 汇总：各跳数命中的节点
    print("\n" + "-" * 72)
    by_hop = {}
    for target, (node_path, _) in targets.items():
        by_hop.setdefault(len(node_path) - 1, []).append(target)
    for h in sorted(by_hop):
        print(f"  {h} 跳可达 {len(by_hop[h])} 个: {', '.join(by_hop[h])}")
    return targets


# ---------------------------------------------------------------------------
# 4. main
# ---------------------------------------------------------------------------
def main():
    ap = argparse.ArgumentParser(description="按节点+relationship+跳数查找完整路径")
    ap.add_argument("--graph", required=True, help="RDF Turtle 图路径")
    ap.add_argument("--start", required=True, help="起点节点名称")
    ap.add_argument("--relation", required=True, help="relationship（边类型），如 BELONGS_TO / AUTHORED_BY")
    ap.add_argument("--hops", type=int, default=2, help="最大跳数（默认 2）")
    ap.add_argument("--direction", choices=["out", "in", "both"], default="both",
                    help="遍历方向（默认 both）")
    args = ap.parse_args()

    G = load_graph_from_ttl(args.graph)

    # 起点节点名容错：精确匹配失败时给出候选
    if args.start not in G.nodes:
        print(f"[警告] 图中不存在节点 '{args.start}'")
        candidates = [n for n in G.nodes if args.start.lower() in n.lower()]
        if candidates:
            print(f"  相似的节点名（可任选其一作为 --start）:")
            for c in candidates[:15]:
                print(f"    - {c}")
        else:
            print(f"  图中共 {len(G.nodes)} 个节点，可用 --start 的值例如:")
            for c in list(G.nodes)[:15]:
                print(f"    - {c}")
        sys.exit(1)

    print_results(G, args.start, args.relation, args.hops, args.direction)


if __name__ == "__main__":
    main()
