#!/usr/bin/env python3
"""One bounded content-subsystem follow-up inside the SAME 200k evaluation ledger.

This does not replace or relabel the failed full game episode as passed.
"""
import argparse
import asyncio
import json
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/"backend"))


async def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument("--live",action="store_true")
    args=parser.parse_args()
    if not args.live:parser.error("No calls made; --live is required")
    from agents import ModelSettings
    from npc_director.config import Settings
    from npc_director.agents.content_author import build_content_author_agent
    from npc_director.agents.content_reviewer import build_content_reviewer_agent
    from npc_director.contracts.content import ContentNeed,ContentPolicy,ContentFact,ContentAuthorInput,ContentCandidate,ContentReviewerInput,ContentReview
    from npc_director.governance.content_review import bind_candidate_objectives,validate_content_review
    from npc_director.state.content_store import ContentStore
    from last_light.director import DirectorBridge,JOB_CONTEXT,_json
    directory=ROOT/"artifacts/live-qwen-budget"
    output=ROOT/"artifacts/content-subsystem-report.json"
    if output.exists():raise SystemExit("This follow-up has already been attempted; not rerunning")
    report={"kind":"isolated Author/Reviewer + ContentStore follow-up", "full_game_episode_passed":False,
        "model":"qwen3.8-flash","status":"started","author":"not_run","reviewer":"not_run","published":[]}
    output.write_text(json.dumps(report,ensure_ascii=False,indent=2))
    bridge=DirectorBridge(directory,lambda sid:None,lambda sid:None,model="qwen3.8-flash",token_budget=200000)
    context=JOB_CONTEXT.set(("content_subsystem","content_subsystem"))
    settings=Settings(model="qwen3.8-flash",model_profile="idealab_qwen")
    need=ContentNeed(need_id="n",purpose="写简报",content_kind="background",reuse_checked=True,allowed_kinds=["background"])
    policy=ContentPolicy(session_id="s",npc_id="lin",allowed_kinds=["background"],
        canonical_facts=[ContentFact(fact_key="f",statement="列车停车，主照明断电。")],
        hard_constraints=["不增添事实。"],max_new_quests=0)
    try:
        author=build_content_author_agent(settings).clone(model_settings=ModelSettings(max_tokens=512))
        payload=ContentAuthorInput(need=need,policy=policy)
        result=await bridge.transport(author,_json(payload.model_dump(mode="json",exclude_defaults=True,exclude_none=True)),ContentCandidate)
        candidate=bind_candidate_objectives(result.output,policy)
        report.update(author="passed",candidate=candidate.model_dump(mode="json"))
        output.write_text(json.dumps(report,ensure_ascii=False,indent=2))
        reviewer=build_content_reviewer_agent(settings).clone(model_settings=ModelSettings(max_tokens=128))
        payload=ContentReviewerInput(need=need,candidate=candidate,policy=policy)
        result=await bridge.transport(reviewer,_json(payload.model_dump(mode="json",exclude_defaults=True,exclude_none=True)),ContentReview)
        report.update(reviewer="returned",review=result.output.model_dump(mode="json"))
        reviewed=validate_content_review(need,candidate,result.output,policy)
        report["reviewer"]="passed"
        store=ContentStore(directory/"content-probe.sqlite")
        staged=store.stage_reviewed("s","e","t","lin",reviewed)
        store.freeze_turn_policy("s","t",staged.policy_digest)
        # Persist full content before the mock receiver acknowledges actual delivery.
        (directory/"content-delivery.json").write_text(candidate.model_dump_json(indent=2))
        with store.transaction() as connection:
            store.publish_turn_in_connection(connection,"s","t",expected_policy_digest=staged.policy_digest)
        report["published"]=[r.content_id for r in store.list_published("s")]
        report["status"]="passed" if report["published"] else "not_published"
    except Exception as error:
        report.update(status="not_completed",error_type=type(error).__name__,diagnostic=getattr(bridge.transport,"last_diagnostic",{}))
    finally:
        JOB_CONTEXT.reset(context)
        report["usage"]=bridge.ledger.report()
        output.write_text(json.dumps(report,ensure_ascii=False,indent=2)+"\n")
        await bridge.close()
    print(json.dumps({"status":report["status"],"author":report["author"],"reviewer":report["reviewer"],
        "total_charged_tokens":report["usage"]["charged_tokens"]},ensure_ascii=False))


if __name__=="__main__":asyncio.run(main())
