# -*- coding: utf-8 -*-
"""科学论文知识图谱 —— 交互式可视化网页 + SQLite 导入导出。

功能：
  1. 用 vis-network 渲染科学论文实体关系知识图谱（沿用 taste 美化的低饱和配色）
  2. SQLite 导入：点击「从 SQLite 导入」，从后端读取图谱数据并渲染
  3. SQLite 导出：点击「导出到 SQLite」，把当前图（含增删改）写回数据库
  4. 支持在网页里新增三元组（source --relation--> target），再导出持久化

SQLite 路径（用户指定，Git Bash 视角）：
    /usr/local/adm_data/sqlite/semantica/semantica.db
  —— 实际 Windows 路径为 D:/_AllDocMap/_DATA/sqlite/semantica/semantica.db
  （Anaconda 是 Windows 原生 Python，不识别 MSYS 的 /usr/local/adm_data，
   故脚本内部用 Windows 路径，界面上显示用户给的 Git Bash 路径）

数据库 schema（知识图谱通用）：
    nodes(id TEXT PRIMARY KEY, type TEXT, label TEXT)
    edges(id INTEGER PRIMARY KEY AUTOINCREMENT, source TEXT, target TEXT, relation TEXT)

运行：
    D:/_AllDocMap/06_Software/anaconda/python.exe semantica_sqlite_app.py
    然后浏览器打开 http://127.0.0.1:8899

单机、零外部依赖（仅 Python 标准库 sqlite3 + http.server + vis-network CDN）。
"""

import os
import sys
import json
import sqlite3
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse

# 复用之前脚本的图谱数据与配色
sys.path.insert(0, os.path.join(os.path.dirname(__file__)))
from scientific_papers_kg import (  # noqa: E402
    build_graph, TYPE_COLOR, TYPE_LABEL, REL_LABEL, PaperRelation,
)

# ---- SQLite 路径 ----
DB_DIR_MSYS = "/usr/local/adm_data/sqlite/semantica"      # 用户视角（Git Bash）
DB_DIR_WIN = "D:/_AllDocMap/_DATA/sqlite/semantica"       # 实际（Windows 原生）
DB_PATH = os.path.join(DB_DIR_WIN, "semantica.db")

PORT = 8899


# ===========================================================================
# SQLite 读写
# ===========================================================================
def init_db():
    """建表；若数据库为空，则把内置论文图谱数据首次导入。"""
    os.makedirs(DB_DIR_WIN, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("""CREATE TABLE IF NOT EXISTS nodes(
        id TEXT PRIMARY KEY, type TEXT NOT NULL, label TEXT NOT NULL)""")
    cur.execute("""CREATE TABLE IF NOT EXISTS edges(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        source TEXT NOT NULL, target TEXT NOT NULL, relation TEXT NOT NULL)""")
    conn.commit()

    cur.execute("SELECT COUNT(*) FROM nodes")
    if cur.fetchone()[0] == 0:
        _, nodes, edges = build_graph()
        for nid, (ntype, label) in nodes.items():
            cur.execute("INSERT INTO nodes(id,type,label) VALUES(?,?,?)",
                        (nid, ntype, label))
        for s, t, rel in edges:
            cur.execute("INSERT INTO edges(source,target,relation) VALUES(?,?,?)",
                        (s, t, rel))
        conn.commit()
        print(f"[init] 首次导入内置图谱数据到 SQLite: {len(nodes)} 节点 / {len(edges)} 边")
    conn.close()


def import_from_sqlite():
    """读全部节点与边，返回 {nodes: [...], edges: [...]}。"""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    nodes = [{"id": r["id"], "type": r["type"], "label": r["label"]}
             for r in cur.execute("SELECT id,type,label FROM nodes")]
    edges = [{"source": r["source"], "target": r["target"], "relation": r["relation"]}
             for r in cur.execute("SELECT source,target,relation FROM edges")]
    conn.close()
    return {"nodes": nodes, "edges": edges}


def export_to_sqlite(payload):
    """把前端传来的 {nodes, edges} 全量写回（清空后重建，前端图即唯一真源）。"""
    nodes = payload.get("nodes", [])
    edges = payload.get("edges", [])
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("DELETE FROM edges")
    cur.execute("DELETE FROM nodes")
    for n in nodes:
        cur.execute("INSERT INTO nodes(id,type,label) VALUES(?,?,?)",
                    (n.get("id"), n.get("type", "Entity"), n.get("label", n.get("id"))))
    for e in edges:
        cur.execute("INSERT INTO edges(source,target,relation) VALUES(?,?,?)",
                    (e.get("source"), e.get("target"), e.get("relation", "related_to")))
    conn.commit()
    n_nodes = cur.execute("SELECT COUNT(*) FROM nodes").fetchone()[0]
    n_edges = cur.execute("SELECT COUNT(*) FROM edges").fetchone()[0]
    conn.close()
    return {"ok": True, "nodes": n_nodes, "edges": n_edges}


def db_status():
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    n_nodes = cur.execute("SELECT COUNT(*) FROM nodes").fetchone()[0]
    n_edges = cur.execute("SELECT COUNT(*) FROM edges").fetchone()[0]
    conn.close()
    return {"path": DB_DIR_MSYS, "nodes": n_nodes, "edges": n_edges,
            "type_color": TYPE_COLOR, "type_label": TYPE_LABEL, "rel_label": REL_LABEL}


# ===========================================================================
# HTML 页面（vis-network + 导入导出工具栏）
# ===========================================================================
HTML = r"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<title>科学论文知识图谱 · SQLite</title>
<script src="https://cdnjs.cloudflare.com/ajax/libs/vis-network/9.1.2/dist/vis-network.min.js"></script>
<style>
  :root { --ink:#1a1a1a; --muted:#9aa0a6; --line:#e8e8ea; --bg:#fafafa; }
  * { box-sizing:border-box; }
  body { margin:0; font-family:-apple-system,"Segoe UI","PingFang SC","Microsoft YaHei",sans-serif;
         background:var(--bg); color:var(--ink); }
  .bar { position:fixed; top:0; left:0; right:0; z-index:20; background:#fffffff5;
         border-bottom:1px solid var(--line); padding:12px 20px;
         display:flex; align-items:center; gap:16px; flex-wrap:wrap; }
  .bar h1 { font-size:17px; font-weight:650; margin:0; letter-spacing:.5px; }
  .bar .sub { font-size:11px; color:var(--muted); letter-spacing:1px; text-transform:uppercase; }
  .bar .path { font-size:11px; color:#6b7280; background:#f3f4f6; border:1px solid var(--line);
               border-radius:6px; padding:4px 9px; font-family:ui-monospace,Consolas,monospace; }
  .bar .stat { font-size:12px; color:#6b7280; }
  .bar .sp { flex:1; }
  button { font-size:12px; padding:7px 14px; border-radius:8px; cursor:pointer;
           border:1px solid var(--line); background:#fff; color:#333; transition:all .15s; }
  button:hover { border-color:#b9c2cc; background:#f7f8fa; }
  button.primary { background:#1a1a1a; color:#fff; border-color:#1a1a1a; }
  button.primary:hover { background:#333; }
  #net { position:fixed; top:0; bottom:0; left:0; right:0; margin-top:56px; }
  #status { position:fixed; bottom:16px; right:16px; z-index:20; font-size:12px; color:#4a4a4a;
            background:#fffffff0; border:1px solid var(--line); border-radius:8px;
            padding:8px 12px; box-shadow:0 1px 2px rgba(0,0,0,.04); display:none; }
  #addpanel { position:fixed; bottom:16px; left:16px; z-index:20; background:#fffffff2;
              border:1px solid var(--line); border-radius:10px; padding:14px 16px;
              box-shadow:0 1px 3px rgba(0,0,0,.05); width:280px; }
  #addpanel h3 { margin:0 0 10px; font-size:11px; color:var(--muted); letter-spacing:1.5px;
                 text-transform:uppercase; font-weight:600; }
  #addpanel input, #addpanel select { width:100%; margin-bottom:8px; padding:7px 9px; font-size:12px;
        border:1px solid var(--line); border-radius:6px; background:#fff; color:#333; }
  #addpanel button { width:100%; }
  .legend { position:fixed; top:68px; left:16px; z-index:19; background:#fffffff2;
            border:1px solid var(--line); border-radius:10px; padding:12px 14px; max-width:250px; }
  .legend .grp { font-size:10px; color:var(--muted); letter-spacing:1.2px; text-transform:uppercase; margin:10px 0 6px; }
  .legend .grp:first-child { margin-top:0; }
  .lg { display:inline-flex; align-items:center; gap:5px; font-size:12px; color:#4a4a4a; margin:2px 8px 2px 0; }
  .lg i { width:10px; height:10px; border-radius:50%; display:inline-block; }
</style>
</head>
<body>
  <div class="bar">
    <div>
      <h1>科学论文知识图谱</h1>
      <div class="sub">Scientific Papers Knowledge Graph</div>
    </div>
    <span class="path" id="path">/usr/local/adm_data/sqlite/semantica/semantica.db</span>
    <span class="stat" id="stat">—</span>
    <div class="sp"></div>
    <button id="btnImport" onclick="doImport()">从 SQLite 导入</button>
    <button class="primary" id="btnExport" onclick="doExport()">导出到 SQLite</button>
  </div>

  <div class="legend" id="legend"></div>

  <div id="addpanel">
    <h3>新增三元组（再点「导出」持久化）</h3>
    <input id="fSource" placeholder="主体 source（节点名）">
    <select id="fRel"></select>
    <input id="fTarget" placeholder="客体 target（节点名）">
    <select id="fType" placeholder="节点类型"></select>
    <button onclick="addTriple()">添加节点与关系</button>
  </div>

  <div id="status"></div>
  <div id="net"></div>

<script>
const TYPE_COLOR = __TYPE_COLOR__;
const TYPE_LABEL = __TYPE_LABEL__;
const REL_LABEL = __REL_LABEL__;

const nodes = new vis.DataSet([]);
const edges = new vis.DataSet([]);
const container = document.getElementById('net');
const network = new vis.Network(container, {nodes, edges}, {
  physics: { solver:'forceAtlas2Based', forceAtlas2Based:{ gravity:-80, centralGravity:0.008, springLength:110, springStrength:0.06 }, stabilization:{iterations:200} },
  interaction: { hover:true, tooltipDelay:120 },
  nodes: { shape:'dot', font:{ color:'#3a3a3a', size:13 }, borderWidth:2 },
  edges: { color:{ color:'#C7D0DA', highlight:'#8FA6BC' }, font:{ color:'#9aa0a6', size:10, background:'#fff', strokeWidth:0 }, arrows:'to' }
});

function colorOf(t){ return TYPE_COLOR[t] || '#9aa0a6'; }
function sizeOf(nid){
  const deg = edges.get().filter(e=>e.source===nid || e.target===nid).length;
  return 8 + 20 * Math.min(1, deg/12);
}
function applyData(d){
  const nds = d.nodes.map(n=>({ id:n.id, label:n.label||n.id, __type:n.type, title:(n.label||n.id)+'\n类型: '+(TYPE_LABEL[n.type]||n.type), color:{background:colorOf(n.type), border:'#fff', highlight:{background:colorOf(n.type), border:'#fff'}} }));
  const eds = d.edges.map((e,i)=>({ id:i, from:e.source, to:e.target, label:REL_LABEL[e.relation]||e.relation, title:e.source+' --['+e.relation+']--> '+e.target }));
  nodes.clear(); edges.clear();
  nodes.add(nds); edges.add(eds);
  // 节点大小按度数
  nodes.update(nds.map(n=>({ id:n.id, size:sizeOf(n.id) })));
}
function flash(msg){ const s=document.getElementById('status'); s.textContent=msg; s.style.display='block'; setTimeout(()=>s.style.display='none',2200); }
function refreshStat(){ const s=document.getElementById('stat'); s.textContent = nodes.length+' 节点 · '+edges.length+' 边'; }

async function doImport(){
  const r = await fetch('/api/import'); const d = await r.json();
  applyData(d); refreshStat();
  flash('已从 SQLite 导入 '+d.nodes.length+' 节点 / '+d.edges.length+' 边');
}
async function doExport(){
  const payload = {
    nodes: nodes.get().map(n=>({ id:n.id, label:n.label, type: n.__type || 'Entity' })),
    edges: edges.get().map(e=>({ source:e.from, target:e.to, relation: e.__rel || 'related_to' }))
  };
  const r = await fetch('/api/export', { method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify(payload) });
  const d = await r.json();
  flash('已导出到 SQLite：'+d.nodes+' 节点 / '+d.edges+' 边');
}
function addTriple(){
  const src=document.getElementById('fSource').value.trim();
  const tgt=document.getElementById('fTarget').value.trim();
  const rel=document.getElementById('fRel').value;
  const typ=document.getElementById('fType').value;
  if(!src||!tgt){ flash('请填写主体和客体'); return; }
  const sid='n_'+src.replace(/\W+/g,'_'); const tid='n_'+tgt.replace(/\W+/g,'_');
  if(!nodes.get(sid)) nodes.add({ id:sid, label:src, __type:typ, title:src, color:{background:colorOf(typ), border:'#fff'} });
  if(!nodes.get(tid)) nodes.add({ id:tid, label:tgt, __type:'Entity', title:tgt, color:{background:colorOf('Entity'), border:'#fff'} });
  const eid='e_'+Date.now();
  edges.add({ id:eid, from:sid, to:tid, label:REL_LABEL[rel]||rel, __rel:rel, title:src+' --['+rel+']--> '+tgt });
  refreshStat(); flash('已添加三元组（记得点「导出」保存）');
}
function buildUI(){
  // 图例
  const lg=document.getElementById('legend');
  lg.innerHTML = '<div class="grp">节点类型</div>' + Object.keys(TYPE_COLOR).map(t=>'<span class="lg"><i style="background:'+TYPE_COLOR[t]+'"></i>'+(TYPE_LABEL[t]||t)+'</span>').join('');
  // 关系下拉
  const rel=document.getElementById('fRel');
  rel.innerHTML = Object.keys(REL_LABEL).map(r=>'<option value="'+r+'">'+REL_LABEL[r]+' ('+r+')</option>').join('');
  // 类型下拉
  const typ=document.getElementById('fType');
  typ.innerHTML = '<option value="Paper">论文 Paper</option><option value="Author">作者 Author</option><option value="Institution">机构 Institution</option><option value="Journal">期刊 Journal</option><option value="Conference">会议 Conference</option><option value="Discipline">学科 Discipline</option><option value="Entity">通用 Entity</option>';
  document.getElementById('path').textContent = '/usr/local/adm_data/sqlite/semantica/semantica.db';
}
buildUI();
doImport();
</script>
</body>
</html>
"""

# 注入配色 / 类型 / 关系映射到前端 JS
HTML = (
    HTML.replace("__TYPE_COLOR__", json.dumps(TYPE_COLOR))
        .replace("__TYPE_LABEL__", json.dumps(TYPE_LABEL, ensure_ascii=False))
        .replace("__REL_LABEL__", json.dumps(REL_LABEL, ensure_ascii=False))
)


# ===========================================================================
# HTTP 服务
# ===========================================================================
class Handler(BaseHTTPRequestHandler):
    def _send(self, code, body, ctype="application/json; charset=utf-8"):
        data = body if isinstance(body, bytes) else body.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        path = urlparse(self.path).path
        if path == "/":
            self._send(200, HTML, "text/html; charset=utf-8")
        elif path == "/api/import":
            self._send(200, json.dumps(import_from_sqlite(), ensure_ascii=False))
        elif path == "/api/status":
            self._send(200, json.dumps(db_status(), ensure_ascii=False))
        else:
            self._send(404, json.dumps({"error": "not found"}))

    def do_POST(self):
        path = urlparse(self.path).path
        if path == "/api/export":
            length = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(length).decode("utf-8")
            try:
                payload = json.loads(body)
                result = export_to_sqlite(payload)
                self._send(200, json.dumps(result, ensure_ascii=False))
            except Exception as e:  # noqa: BLE001
                self._send(400, json.dumps({"error": str(e)}))
        else:
            self._send(404, json.dumps({"error": "not found"}))

    def log_message(self, *args):
        pass  # 静默访问日志


def main():
    init_db()
    print("=" * 60)
    print("科学论文知识图谱 · SQLite 导入导出服务")
    print(f"  SQLite : {DB_DIR_MSYS}/semantica.db")
    print(f"  网页    : http://127.0.0.1:{PORT}")
    print("  接口    : GET /api/import  |  POST /api/export  |  GET /api/status")
    print("  按 Ctrl+C 停止")
    print("=" * 60)
    server = HTTPServer(("127.0.0.1", PORT), Handler)
    server.serve_forever()


if __name__ == "__main__":
    main()
