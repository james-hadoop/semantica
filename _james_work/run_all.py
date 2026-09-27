# -*- coding: utf-8 -*-
"""一键运行三个场景。

用法：
    python run_all.py          # 依次运行场景 1 / 2 / 3
"""

import time
import traceback

import common  # noqa: F401  初始化 sys.path（semantica 源码路径）
import scenario1_decision_intelligence as s1
import scenario2_aml_rules_engine as s2
import scenario3_doc_to_kg_pipeline as s3


def main() -> None:
    scenarios = [
        ("场景1 决策智能与审计链", s1.main),
        ("场景2 AML 反洗钱规则引擎", s2.main),
        ("场景3 文档到知识图谱流水线", s3.main),
    ]
    results = []
    for name, fn in scenarios:
        t0 = time.time()
        print(f"\n{'#' * 76}\n# 运行 {name}\n{'#' * 76}")
        try:
            fn()
            results.append((name, "OK", f"{time.time() - t0:.1f}s"))
        except Exception:
            traceback.print_exc()
            results.append((name, "FAILED", f"{time.time() - t0:.1f}s"))

    print("\n" + "=" * 60)
    print("运行汇总")
    print("=" * 60)
    for name, status, dur in results:
        print(f"  [{status:>6}] {name}  ({dur})")


if __name__ == "__main__":
    main()
