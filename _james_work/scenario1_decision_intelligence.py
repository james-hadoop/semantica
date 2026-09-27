# -*- coding: utf-8 -*-
"""场景 1：决策智能与可审计决策链（Decision Intelligence + Audit Trail）

对应 semantica 的核心应用场景："每个 AI 决策都是一个可查询、可审计的图节点"。

演示内容（全部单机运行，无 LLM、无外部服务）：
1. 用 ContextGraph 记录一条完整的贷款审批决策链（申请 -> 核保 -> 定价）
2. 建立决策之间的因果关系（CAUSED / INFLUENCED）
3. 回答审计问题："这个利率是怎么定出来的？" -> trace_decision_chain 因果溯源
4. 语义判例检索：find_similar_decisions 找历史相似决策
5. 影响分析：analyze_decision_impact 查一个决策影响了哪些下游决策
6. 政策合规门：check_decision_rules 检查决策是否满足监管规则
7. 用 ProvenanceManager 记录实体数据来源，导出 W3C PROV-O 审计痕迹
8. 用 RDFExporter 把整张图导出为 Turtle 文件（监管提交格式）

运行：python scenario1_decision_intelligence.py
"""

import common  # noqa: F401  (调用 setup()，加入 semantica 源码路径)
from common import banner, step, out_path

from semantica.context import ContextGraph
from semantica.provenance import ProvenanceManager
from semantica.export import RDFExporter


def main() -> None:
    banner("场景 1：决策智能与可审计决策链（贷款审批全流程）")

    # ---------------------------------------------------------------
    step("1. 创建 Context Graph 并记录贷款审批决策链")
    # ---------------------------------------------------------------
    graph = ContextGraph(advanced_analytics=True)

    # 第一环：信贷申请初审
    app_id = graph.record_decision(
        category="credit_application",
        scenario="Personal loan, $85k income, 31% DTI, 3yr employment",
        reasoning="Income meets threshold; employment stable; no adverse credit events",
        outcome="proceed_to_underwriting",
        confidence=0.88,
        metadata={"applicant_id": "A-7291", "decision_maker": "underwriting_bot_v1"},
    )
    print(f"  初审决策节点: {app_id[:8]}...")

    # 第二环：核保
    uw_id = graph.record_decision(
        category="loan_underwriting",
        scenario="Underwriting review for A-7291",
        reasoning="DTI within policy; clean 36-month credit history",
        outcome="approved",
        confidence=0.94,
        metadata={"applicant_id": "A-7291", "decision_maker": "underwriting_bot_v1"},
    )
    print(f"  核保决策节点: {uw_id[:8]}...")

    # 第三环：利率定价
    rate_id = graph.record_decision(
        category="interest_rate",
        scenario="Rate assignment for approved loan A-7291",
        reasoning="Prime + 2.4% based on risk tier B2",
        outcome="rate_set_8.9pct",
        confidence=0.99,
        metadata={"applicant_id": "A-7291", "decision_maker": "pricing_engine_v2"},
    )
    print(f"  定价决策节点: {rate_id[:8]}...")

    # ---------------------------------------------------------------
    step("2. 建立决策间因果关系（CAUSED / INFLUENCED）")
    # ---------------------------------------------------------------
    graph.add_causal_relationship(app_id, uw_id, relationship_type="CAUSED")
    graph.add_causal_relationship(uw_id, rate_id, relationship_type="INFLUENCED")
    print("  A-7291 初审 --CAUSED--> 核保 --INFLUENCED--> 利率定价")

    # ---------------------------------------------------------------
    step("3. 审计提问：'这笔 8.9% 的利率是怎么定出来的？'")
    # ---------------------------------------------------------------
    chain = graph.trace_decision_chain(rate_id)
    for trace in chain:
        print(f"  跳数 {trace['hop_count']} | 距离带 {trace['distance_band']}")
        for hop in trace["hops"]:
            print(f"    {hop['from_scenario'][:48]:<50} --{hop['type']}--> {hop['to_scenario'][:48]}")
        print(f"    解读: {trace['interpretation']}")

    # ---------------------------------------------------------------
    step("4. 判例检索：'找历史相似决策'（语义相似，非关键词匹配）")
    # ---------------------------------------------------------------
    # 再录入几条历史决策，构成判例库
    graph.record_decision(
        category="credit_application",
        scenario="Personal loan, $62k income, 28% DTI, 5yr employment",
        reasoning="Stable employment, low DTI",
        outcome="approved",
        confidence=0.91,
        metadata={"applicant_id": "A-8103", "decision_maker": "underwriting_bot_v1"},
    )
    graph.record_decision(
        category="credit_application",
        scenario="Auto loan refinance, $110k income, 22% DTI",
        reasoning="High income, strong collateral",
        outcome="approved",
        confidence=0.93,
        metadata={"applicant_id": "A-9112", "decision_maker": "underwriting_bot_v1"},
    )

    similar = graph.find_similar_decisions(
        "personal loan approval, moderate DTI, stable employment", max_results=3
    )
    print(f"  相似判例 {len(similar)} 条：")
    for s in similar:
        d = s.get("decision", s)
        print(f"    [{d.get('category')}] {d.get('scenario', '')[:56]}  (conf={d.get('confidence')})")

    # ---------------------------------------------------------------
    step("5. 影响分析：'核保这个决策影响了哪些下游决策？'")
    # ---------------------------------------------------------------
    impact = graph.analyze_decision_impact(uw_id)
    print(f"  直接影响: {impact['direct_influence']}")
    print(f"  间接影响: {impact['indirect_influence']}")
    print(f"  总影响决策数: {impact['total_influenced']}")

    # ---------------------------------------------------------------
    step("6. 政策合规门：check_decision_rules")
    # ---------------------------------------------------------------
    compliant = graph.check_decision_rules(
        {"category": "loan_underwriting", "confidence": 0.94, "outcome": "approved",
         "decision_maker": "underwriting_bot_v1"}
    )
    print(f"  合规: {compliant['compliant']}")
    if compliant.get("violations"):
        print(f"  违规项: {compliant['violations']}")
    print(f"  政策规则: {compliant['policy_rules']}")

    # 再演示一个"不合规"决策（缺少 decision_maker）
    bad = graph.check_decision_rules({"category": "loan_underwriting", "confidence": 0.5})
    print(f"  低置信度示例 -> 合规: {bad['compliant']}, 违规: {bad['violations']}")

    # ---------------------------------------------------------------
    step("7. 数据来源追溯：ProvenanceManager + W3C PROV-O")
    # ---------------------------------------------------------------
    prov = ProvenanceManager(storage_path=out_path("audit_prov.db"))
    prov.track_entity(
        "applicant_A7291", source="crm/applicants_2026.json",
        metadata={"extractor": "NamedEntityRecognizer"},
    )
    prov.track_entity(
        "credit_report_A7291", source="bureau/experian_pull_20260901.json",
        metadata={"extractor": "FieldMapper"},
    )
    prov_tl = prov.export_prov(format="turtle")
    with open(out_path("audit_provenance.ttl"), "w", encoding="utf-8") as f:
        f.write(prov_tl)
    print(f"  PROV-O 审计痕迹已导出: {out_path('audit_provenance.ttl')}")
    print(f"  审计日志条目: {len(prov.audit_log(format='json'))}")

    # ---------------------------------------------------------------
    step("8. 整图导出为 RDF Turtle（监管提交格式）")
    # ---------------------------------------------------------------
    kg = graph.to_kg_dict()
    RDFExporter().export(kg, out_path("audit_trail.ttl"), format="turtle")
    print(f"  决策图已导出: {out_path('audit_trail.ttl')}")

    print("\n[场景 1 完成] 输出文件在 _james_work/output/ 下：audit_prov.db / audit_provenance.ttl / audit_trail.ttl")


if __name__ == "__main__":
    main()
