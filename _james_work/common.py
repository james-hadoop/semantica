# -*- coding: utf-8 -*-
"""共享配置：让 _james_work 下的所有脚本都能直接引用本机 semantica 源码。

单机环境约定：
- 不安装任何外部服务（Neo4j / Qdrant / Oxigraph 服务端等一概不用）
- 不调用任何云 LLM API
- semantica 直接从本机源码目录 D:/_AllDocMap/02_Project/github/semantica 导入
- 向量检索使用 inmemory 后端 + fastembed 本地 ONNX 嵌入模型
"""

import os
import sys

# 本机 semantica 源码路径
SEMANTICA_SRC = r"D:\_AllDocMap\02_Project\github\semantica"

# 输出目录（每个场景的产物都写到这里，便于统一查看）
OUTPUT_DIR = os.path.join(SEMANTICA_SRC, "_james_work", "output")

# 首次运行会下载 fastembed 的本地 ONNX 模型（约 30MB，之后有缓存）。
# 如果想完全离线（接受随机回退嵌入），把下面这行改为 False。
ALLOW_MODEL_DOWNLOAD = True


def setup():
    """把 semantica 源码目录加入 sys.path，并准备输出目录。"""
    if SEMANTICA_SRC not in sys.path:
        sys.path.insert(0, SEMANTICA_SRC)
    os.makedirs(OUTPUT_DIR, exist_ok=True)


# import common 即完成初始化
setup()


def out_path(name: str) -> str:
    """返回输出目录下的绝对路径。"""
    return os.path.join(OUTPUT_DIR, name)


def banner(title: str) -> None:
    line = "=" * 72
    print(f"\n{line}\n  {title}\n{line}")


def step(msg: str) -> None:
    print(f"\n--- {msg} ---")
