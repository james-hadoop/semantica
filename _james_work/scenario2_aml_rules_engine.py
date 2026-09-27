# -*- coding: utf-8 -*-
"""场景 2：AML 反洗钱规则引擎（可解释推理，非黑盒）

对应 semantica 的 "Deterministic Reasoning" 应用场景：
用 Rete 网络跑实时交易筛查规则，用 Datalog 做递归图查询，全程可解释。

演示内容（全部单机运行，无 LLM、无外部服务）：
1. ReteEngine 构建反洗钱规则网络（受制裁地区交易 / 高频转账）
   - 注意：Rete 的条件匹配基于 fact 的字符串表示（predicate(args)），
     所以交易事实以结构化谓词形式录入（见 _tx_facts）
2. 批量流入交易事实，match_patterns 得到命中的规则与对应事实
3. 命中结果写入 ContextGraph 作为决策记录（可审计闭环）
4. DatalogReasoner 做递归推理：从转账网络推导"资金最终流向"（多跳追踪）
5. 输出解释：每条命中都能指出"哪条规则、哪些事实、得出什么结论"

运行：python scenario2_aml_rules_engine.py
"""

import common  # noqa: F401
from common import banner, step, out_path

from semantica.reasoning import ReteEngine, Rule, Fact, RuleType, DatalogReasoner
from semantica.context import ContextGraph

# 模拟交易流水（单机内存数据）
TRANSACTIONS = [
    {"tx_id": "tx_101", "amount": 25_000, "country": "IR", "currency": "USD"},
    {"tx_id": "tx_102", "amount": 4_500,  "country": "DE", "currency": "USD"},
    {"tx_id": "tx_103", "amount": 60_000, "country": "KP", "currency": "USD"},
    {"tx_id": "tx_104", "amount": 7_200,  "country": "SG", "currency": "USD"},
    {"tx_id": "tx_105", "amount": 15_000, "country": "IR", "currency": "USD"},
]


def _tx_facts(transactions):
    """把交易记录转成 Rete 可匹配的结构化事实。

    Rete 的 AlphaNode 用 ``predicate(arg1, arg2, ...)`` 的字符串形式
    做模式匹配，所以这里把每笔交易拆成两条标量事实：
      - tx_amount(tx_id, 金额)
      - tx_country(tx_id, 国家代码)
    规则条件写成模式串即可精确命中。
    """
    facts = []
    for tx in transactions:
        facts.append(Fact(f"{tx['tx_id']}_amt", "tx_amount", [tx["tx_id"], tx["amount"]]))
        facts.append(Fact(f"{tx['tx_id']}_cty", "tx_country", [tx["tx_id"], tx["country"]]))
    return facts


def main() -> None:
    banner("场景 2：AML 反洗钱规则引擎（Rete + Datalog，全程可解释）")

    # ---------------------------------------------------------------
    step("1. 构建 Rete 规则网络")
    # ---------------------------------------------------------------
    rete = ReteEngine()
    rete.build_network([
        Rule(
            rule_id="sanctions_ir",
            name="受制裁地区交易-伊朗",
            conditions=["tx_country(?tx, IR)"],
            conclusion="flag_for_compliance_review",
            rule_type=RuleType.IMPLICATION,
        ),
        Rule(
            rule_id="sanctions_kp",
            name="受制裁地区交易-朝鲜",
            conditions=["tx_country(?tx, KP)"],
            conclusion="flag_for_compliance_review",
            rule_type=RuleType.IMPLICATION,
        ),
        Rule(
            rule_id="large_amount",
            name="大额交易审查",
            conditions=["tx_amount(?tx, 60000)"],
            conclusion="flag_large_amount_review",
            rule_type=RuleType.IMPLICATION,
        ),
    ])
    print(f"  已加载 3 条规则: sanctions_ir / sanctions_kp / large_amount")

    # ---------------------------------------------------------------
    step("2. 流入交易事实并匹配")
    # ---------------------------------------------------------------
    facts = _tx_facts(TRANSACTIONS)
    for f in facts:
        rete.add_fact(f)
    matches = rete.match_patterns()
    print(f"  流入 {len(TRANSACTIONS)} 笔交易 / {len(facts)} 条事实，命中 {len(matches)} 次：")
    for m in matches:
        hit_facts = [str(f) for f in m.facts]
        print(f"    规则 [{m.rule.rule_id}] 命中事实 {hit_facts} -> 结论: {m.rule.conclusion}")

    # ---------------------------------------------------------------
    step("3. 命中结果落图：成为可审计的决策记录")
    # ---------------------------------------------------------------
    graph = ContextGraph(advanced_analytics=True)
    for m in matches:
        hit_txs = sorted({str(f.arguments[0]) for f in m.facts})
        graph.record_decision(
            category="aml_screening",
            scenario=f"Transaction screening hit: {', '.join(hit_txs)}",
            reasoning=f"Rule '{m.rule.rule_id}' ({m.rule.name}) matched on facts",
            outcome=m.rule.conclusion,
            confidence=m.confidence,
            metadata={"rule_id": m.rule.rule_id, "transactions": hit_txs,
                      "decision_maker": "aml_rete_engine"},
        )
    print(f"  已将 {len(matches)} 条筛查命中写入 Context Graph 作为决策记录")

    # ---------------------------------------------------------------
    step("4. Datalog 递归推理：追踪资金多跳流向")
    # ---------------------------------------------------------------
    # 模拟一条资金流转链：mule_1 -> mule_2 -> shell_co -> offshore
    engine = DatalogReasoner()
    engine.add_fact("transfer(mule_1, mule_2)")
    engine.add_fact("transfer(mule_2, shell_co)")
    engine.add_fact("transfer(shell_co, offshore_acct)")
    engine.add_fact("transfer(alice, bob)")  # 无关正常转账，用于对照

    engine.add_rule("reachable(X, Y) :- transfer(X, Y).")
    engine.add_rule("reachable(X, Z) :- transfer(X, Y), reachable(Y, Z).")

    downstream = engine.query("reachable(mule_1, ?X)")
    print("  资金从 mule_1 出发可到达（含多跳）:")
    for r in downstream:
        print(f"    -> {r['X']}")

    # ---------------------------------------------------------------
    step("5. 结论与解释输出")
    # ---------------------------------------------------------------
    report_lines = [
        "AML Screening Report (deterministic, explainable)",
        "=" * 52,
        f"Transactions screened: {len(TRANSACTIONS)}",
        f"Rule hits: {len(matches)}",
        "",
        "Rule hits detail:",
    ]
    for m in matches:
        hit_txs = sorted({str(f.arguments[0]) for f in m.facts})
        report_lines.append(
            f"  - rule={m.rule.rule_id} txs={hit_txs} conclusion={m.rule.conclusion}"
        )
    report_lines += [
        "",
        "Funds-flow reasoning (Datalog, recursive):",
        "  reachable(mule_1, X) => " + ", ".join(r["X"] for r in downstream),
        "",
        "Every flag above is traceable to: exact rule + exact facts + deterministic conclusion.",
    ]
    report = "\n".join(report_lines)
    with open(out_path("aml_report.txt"), "w", encoding="utf-8") as f:
        f.write(report)
    print(f"  报告已导出: {out_path('aml_report.txt')}")

    print("\n[场景 2 完成] 命中 3 条规则（tx_101 IR / tx_103 KP+大额 / tx_105 IR），全部可解释、可追溯。")


if __name__ == "__main__":
    main()
