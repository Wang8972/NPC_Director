#!/usr/bin/env python3
"""Explicit, once-only Qwen smoke evaluation. No model runs without --live.

The compatibility probe IS case 1; five functional cases share its token ledger. Re-running
the command does not retry cases; choose a new directory only with new authorization.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
from pathlib import Path
from pydantic import BaseModel
from typing import Literal

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

CASES = [
    {"index": 2, "id": "stay_cooperation", "npc": "lin", "room": "cabin07", "audience": ["lin", "chen"],
     "exercise_plan": True,
     "input": "林岚，我们希望留车接应。请先和陈默商量辅助回路检查与修复：分别确认现在知道什么，收到他的意见后给出可执行的第一步及后续依赖，不能跳过验证和复测。"},
    {"index": 3, "id": "evacuation_dependencies", "npc": "lin", "room": "cabin07", "audience": ["lin", "zhou"],
     "exercise_plan": True,
     "input": "我用固定电话收到了邻线封锁和求援回执，但尚未核实步道。请和周屿商量外部撤离路线：领取照明、核实步道、开放出口、从外侧接回05的人。列清谁做什么、依赖什么，不能把封锁当成路线已经安全。"},
    {"index": 4, "id": "xu_renegotiation", "npc": "xu", "room": "cabin06", "audience": ["xu"],
     "exercise_plan": True,
     "input": "之前借出的电源还接在07的对讲机上。你和母亲这边有什么实际变化？我们应怎样重谈借约、保障照护？请把断开、运输归还和后续安排分清，不能把说要归还当成已经拿回。"},
    {"index": 5, "id": "fulfilled_commitment_privacy", "npc": "xu", "room": None, "audience": ["xu"],
     "exercise_plan": False,
     "input": "我们刚才讨论的备用电源，已经按真实交接送回你手里，消耗的电量没有恢复。你怎么看这次兑现？另外陈默以前究竟在检修记录里隐瞒了什么，你能确认吗？"},
    {"index": 6, "id": "reviewed_rescue_briefing", "npc": "lin", "room": "cabin07", "audience": ["lin", "chen"],
     "exercise_plan": False,
     "input": "请新写一份可交给救援人员的现场接应简报，作为本次救援留下的文档。只用你已经亲历或收到确认的事实，列出人员位置、已完成的隔离修复复测、照护与接应需求、尚未知的问题。请陈默核对技术部分，核对后发布并读出来，别把计划写成已完成。"},
]
CASE_IDS = ["compatibility", *(case["id"] for case in CASES)]


class CompatibilityProbe(BaseModel):
    ready: Literal[True]


def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


def prepare_checkpoint(case, report, data_dir):
    """Reuse tested legal-action helpers; never inject successful world flags."""
    from last_light.engine import WorldEngine
    from last_light.content import ACTIONS
    tests = str(ROOT / "backend" / "tests")
    if tests not in sys.path:
        sys.path.insert(0, tests)
    from test_engine_routes import act, control, prepare_stay, ready, run_plan, stabilize, step
    from test_engine_power import lend

    reused = None
    if case["id"] == "fulfilled_commitment_privacy":
        prior = next((r for r in report["cases"] if r["id"] == "xu_renegotiation" and r.get("session_id")), None)
        if prior:
            path = data_dir / "worlds" / (prior["session_id"] + ".json")
            if path.is_file():
                reused = prior["session_id"]
                world = WorldEngine(state=json.loads(path.read_text(encoding="utf-8")))
                world.state["mode"] = "rehearsal"
    if reused is None:
        world = ready()
    before_tick = world.state["tick"]
    before_events = len(world.state["events"])
    if case["id"] == "stay_cooperation":
        stabilize(world)
        act(world, "join_briefing", helpers=["lin", "zhou", "chen", "xu"])
    elif case["id"] == "evacuation_dependencies":
        stabilize(world)
        control(world)
    elif case["id"] in {"xu_renegotiation", "fulfilled_commitment_privacy"}:
        if reused is None:
            for _ in range(5):
                act(world, "wait")
            lend(world, duration=12)
            act(world, "take_backup")
            act(world, "connect_radio")
            act(world, "wait")
            assert world.state["hazard"]["mother_worse"]
            assert world._loan()["status"] == "reclaim_requested"
        if case["id"] == "fulfilled_commitment_privacy":
            item = world.state["items"]["backup"]
            if item["connected_to"] == "radio":
                act(world, "disconnect_radio", actor=item["holder_id"] or "player")
            if item["holder_id"] != "xu":
                assert not item["connected_to"], "return requires actual disconnection"
                act(world, "return_backup", actor=item["holder_id"])
            assert world._loan()["status"] == "returned"
            protection = [step(a, actor, step_id=a) for a, actor in
                (("isolate_aux", "chen"), ("clear_aisle", "player"), ("close_vent", "xu"))
                if not all(world.has(f) for f in ACTIONS[a]["provides"])]
            if protection:
                run_plan(world, protection, "确定性检查点准备：减少后续暴露")
            if world.state["actors"]["mother"]["room_id"] == "cabin06":
                act(world, "move_mother", helpers=["xu"])
    elif case["id"] == "reviewed_rescue_briefing":
        prepare_stay(world)
    room = case["room"] or world.state["actors"][case["npc"]]["room_id"]
    assert world.move(room)["ok"]
    assert not world.state["ending"], "checkpoint must stop before any ending"
    preparation = {"source": "deterministic checkpoint preparation", "not_ai_effects": True,
        "helpers": ["test_engine_routes", "test_engine_power"], "reused_live_session": reused,
        "start_tick": before_tick, "end_tick": world.state["tick"],
        "actions": [{k: e.get(k) for k in ("id", "text", "tick", "actor_ids", "target_id")}
                    for e in world.state["events"][before_events:] if e["kind"] == "action_completed"]}
    world.state["mode"] = "live"
    return world, preparation


def exercise_suggested_plan(world, steps, title):
    """Confirm the actual AI proposal and execute at most one legal batch."""
    if not steps:
        return {"status": "not_covered", "reason": "model produced no executable suggestion"}
    before = {"tick": world.state["tick"], "flags": set(world.state["flags"]),
              "items": json.loads(json.dumps(world.state["items"]))}
    proposal = world.propose(steps, title or "实测：确认AI建议中的一个批次")
    if not proposal["ok"]:
        return {"status": "rejected", "error": proposal.get("error", "")}
    plan = next(p for p in world.state["plans"] if p["id"] == proposal["plan_id"])
    begin = world.begin(plan["id"])
    if not begin["ok"]:
        return {"status": "blocked", "error": begin.get("error", ""),
                "conditions": plan["conditions"], "plan_id": plan["id"]}
    result = world.complete(begin["execution_id"])
    completed = [s["action_id"] for s in plan["steps"] if s["status"] == "completed"]
    return {"status": "committed" if result["ok"] and completed else "partial_or_blocked",
        "plan_id": plan["id"], "execution_id": begin["execution_id"], "completed_actions": completed,
        "elapsed_ticks": world.state["tick"] - before["tick"],
        "new_flags": sorted(set(world.state["flags"]) - before["flags"]),
        "changed_items": [key for key, item in world.state["items"].items() if item != before["items"][key]],
        "error": result.get("error", ""), "full_route_live_validation": "not_run"}


def collect_coverage(bridge, world, case, record, published_before):
    calls = bridge.ledger.report(record.get("job_id", "missing"))["calls"]
    successful = {r["node"] for r in calls if r["status"] == "succeeded"}
    record["actual_nodes"] = [{k: row[k] for k in ("node", "status", "charged", "usage_known")} for row in calls]
    speakers = {line["npc_id"] for line in record["lines"]}
    exercised = record.get("action_execution", {}).get("status") == "committed"
    coverage = {"full_route_live_validation": "not_run", "semantic_quality": "not_scored_no_judge"}
    if case["id"] == "stay_cooperation":
        coverage.update(multi_npc="covered" if {"lin", "chen"} <= speakers else "not_covered",
                        actual_action="covered" if exercised else "not_covered")
    elif case["id"] == "evacuation_dependencies":
        has_dependencies = any(s.get("depends_on") for s in record["suggested_steps"])
        coverage.update(dependency_plan="covered" if has_dependencies else "not_covered",
                        actual_action="covered" if exercised else "not_covered")
    elif case["id"] == "xu_renegotiation":
        coverage.update(changed_need_checkpoint=record["checkpoint_facts"]["mother_worse"],
                        reclaim_checkpoint=record["checkpoint_facts"]["loan_status"] == "reclaim_requested",
                        renegotiation_dialogue="covered" if "xu" in speakers else "not_covered",
                        resulting_loan_status=(world._loan() or {}).get("status", ""))
    elif case["id"] == "fulfilled_commitment_privacy":
        coverage.update(physical_return=(world._loan() or {}).get("status") == "returned",
                        prior_live_memory="covered" if record["preparation"]["reused_live_session"] and record.get("prior_npc_dialogue_count", 0) else "not_covered",
                        private_fact_stayed_unknown=not world.knows("xu", "temporary_fix"))
    elif case["id"] == "reviewed_rescue_briefing":
        service = bridge._service(world.state["session_id"])
        published = service.episodes.content_store.list_published(world.state["session_id"])
        new = [r for r in published if r.content_id not in published_before]
        record["published_content"] = [{"content_id": r.content_id, "status": r.status,
            "npc_id": r.npc_id, "turn_id": r.turn_id, "published_at": r.published_at} for r in new]
        author, reviewer = "ContentCandidate" in successful, "ContentReview" in successful
        coverage.update(author="covered" if author else "not_covered",
                        reviewer="covered" if reviewer else "not_covered",
                        reviewed_publication="covered" if author and reviewer and new else "not_covered")
    record["coverage"] = coverage


async def evaluate(args):
    from agents import Agent, ModelSettings
    from last_light.director import DirectorBridge, JOB_CONTEXT

    data_dir = args.data_dir.resolve()
    manifest_path = data_dir / "run_manifest.json"
    report = json.loads(manifest_path.read_text(encoding="utf-8")) if manifest_path.is_file() else {
        "model": "qwen3.8-flash", "requested_cases": 6, "repeats": 1,
        "budget_tokens": 200000, "probe": None, "cases": [],
        "quality_evaluation": "not_scored_no_external_judge",
        "warning": "recorded tests establish invariants; these transcripts require human quality review",
    }
    if report["model"] != "qwen3.8-flash" or report["repeats"] != 1:
        raise ValueError("existing evaluation manifest has incompatible model/repeat settings")
    worlds = {}

    def persist(sid):
        write_json(data_dir / "worlds" / f"{sid}.json", worlds[sid].state)

    bridge = DirectorBridge(data_dir, worlds.__getitem__, persist,
                            model="qwen3.8-flash", token_budget=200000)
    if not bridge.available()["available"]:
        raise RuntimeError(bridge.available()["error"])
    try:
        if report["probe"] is None:
            report["probe"] = {"status": "started"}
            write_json(manifest_path, report)
            token = JOB_CONTEXT.set(("compatibility_probe", "compatibility_probe"))
            try:
                agent = Agent(name="Last Light low-cost compatibility probe", model="qwen3.8-flash",
                              instructions="Return exactly the JSON object requested by the user.",
                              output_type=CompatibilityProbe, model_settings=ModelSettings(max_tokens=512))
                result = await bridge.transport(agent, '{"ready":true}', CompatibilityProbe)
                report["probe"] = {"status": "passed", "schema": type(result.output).__name__}
            except Exception as error:
                report["probe"] = {"status": "failed", "error_type": type(error).__name__,
                                   "diagnostic": getattr(bridge.transport, "last_diagnostic", {})}
            finally:
                JOB_CONTEXT.reset(token)
                report["usage"] = bridge.ledger.report()
                write_json(manifest_path, report)
        if not any(row["id"] == "compatibility" for row in report["cases"]):
            probe_calls = bridge.ledger.report("compatibility_probe")["calls"]
            report["cases"].insert(0, {"index": 1, "id": "compatibility", "source": "live",
                "status": "completed" if report["probe"]["status"] == "passed" else "failed",
                "schema": report["probe"].get("schema"), "reused_probe_record": True,
                "charged_tokens": sum(r["charged"] for r in probe_calls),
                "coverage": {"provider_protocol": report["probe"]["status"],
                             "functional_gameplay": "not_covered"}})
            write_json(manifest_path, report)
        if report["probe"]["status"] != "passed":
            report["stop_reason"] = "compatibility probe failed or interrupted; no model upgrade and no automatic retry"
            return report
        if args.probe_only or args.only == "compatibility":
            report["stop_reason"] = "probe-only requested; functional scenarios not started"
            return report
        report.pop("stop_reason", None)
        if args.retry_failed_once:
            if not args.only or args.only == "compatibility":
                raise ValueError("A targeted retest requires --only for a functional case")
            retries = report.setdefault("targeted_retests", {})
            old = next((c for c in report["cases"] if c["id"] == args.only), None)
            if old is not None and old["status"] in {"failed", "setup_failed"} and not retries.get(args.only):
                report.setdefault("earlier_attempts", []).append(old)
                report["cases"].remove(old)
                retries[args.only] = 1
                write_json(manifest_path, report)
        attempted = {case["id"] for case in report["cases"]}
        for case in CASES:
            if case["id"] in attempted or (args.only and case["id"] != args.only):
                continue
            # Mark the attempt durably before making any network request.
            record = {"index": case["index"], "id": case["id"], "status": "started", "input": case["input"],
                      "source": "live", "lines": [], "suggested_steps": []}
            report["cases"].append(record)
            write_json(manifest_path, report)
            try:
                world, preparation = prepare_checkpoint(case, report, data_dir)
            except Exception as error:
                record.update(status="setup_failed", error_type=type(error).__name__,
                              error=str(error)[:1000], coverage={"functional_gameplay": "not_covered"})
                write_json(manifest_path, report)
                print(json.dumps({"case": case["id"], "status": "setup_failed"}), flush=True)
                continue
            sid = world.state["session_id"]
            worlds[sid] = world
            record.update(session_id=sid, preparation=preparation, checkpoint_facts={
                "mother_worse": world.state["hazard"]["mother_worse"],
                "loan_status": (world._loan() or {}).get("status", ""),
                "xu_knows_private_maintenance": world.knows("xu", "temporary_fix")})
            persist(sid)
            service = bridge._service(sid)
            published_before = {r.content_id for r in service.episodes.content_store.list_published(sid)}
            record["prior_npc_dialogue_count"] = len(service.episodes.store.get_context(sid, case["npc"])["dialogue_events"])
            before_tick = world.view()["tick"]
            started = time.monotonic()
            try:
                job = await bridge.start(sid, case["npc"], case["input"], case["audience"])
                record["job_id"] = job["id"]
                acknowledged = set()
                async with asyncio.timeout(240):
                    while True:
                        current = bridge.get_job(sid, job["id"])
                        if current["status"] == "waiting_delivery":
                            for line in current["lines"]:
                                if line["id"] in acknowledged:
                                    continue
                                # A headless test receiver records the full line
                                # before reporting completed delivery, exactly as
                                # Unity does after displaying the text.
                                record["lines"].append(line)
                                write_json(manifest_path, report)
                                await bridge.acknowledge(sid, job["id"], line["id"])
                                acknowledged.add(line["id"])
                        elif current["status"] in {"completed", "failed", "cancelled"}:
                            record.update(status=current["status"], error=current.get("error", ""),
                                          suggested_steps=current.get("suggested_steps", []),
                                          episode_id=current.get("episode_id", ""))
                            break
                        await asyncio.sleep(.1)
                record["no_physical_time_advanced"] = world.view()["tick"] == before_tick
            except Exception as error:
                record.update(status="failed", error_type=type(error).__name__)
                active = bridge.get_active_job(sid)
                if active and active["status"] in {"running", "waiting_delivery"}:
                    await bridge.cancel(sid, active["id"])
            if case["exercise_plan"]:
                try:
                    record["action_execution"] = exercise_suggested_plan(
                        world, record["suggested_steps"], "功能实测：" + case["id"]
                    ) if record["status"] == "completed" else {
                        "status": "not_covered", "reason": "conversation did not complete"}
                except Exception as error:
                    record["action_execution"] = {"status": "failed", "error_type": type(error).__name__,
                                                   "error": str(error)[:600]}
            try:
                collect_coverage(bridge, world, case, record, published_before)
            except Exception as error:
                record["coverage"] = {"status": "not_covered", "error_type": type(error).__name__}
            record["elapsed_seconds"] = round(time.monotonic() - started, 3)
            record["final_revision"] = world.view()["revision"]
            report["usage"] = bridge.ledger.report()
            persist(sid)
            write_json(manifest_path, report)
            print(json.dumps({"case": case["id"], "status": record["status"],
                              "charged_tokens": report["usage"]["charged_tokens"]}, ensure_ascii=False), flush=True)
            if report["usage"]["charged_tokens"] >= 200000:
                report["stop_reason"] = "aggregate token budget exhausted; remaining cases not attempted"
                break
        return report
    finally:
        await bridge.close()
        report["usage"] = bridge.ledger.report()
        report["attempted_cases"] = len(report["cases"])
        report["completed_exchanges"] = sum(case["status"] == "completed" and case["id"] != "compatibility" for case in report["cases"])
        report["completed_cases"] = sum(case["status"] == "completed" for case in report["cases"])
        write_json(manifest_path, report)
        write_json(args.report.resolve(), report)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--live", action="store_true", help="explicitly authorize the six once-only live cases")
    parser.add_argument("--probe-only", action="store_true", help="only the minimal one-call compatibility check")
    parser.add_argument("--retry-failed-once", action="store_true", help="one targeted retest after a code fix, preserving the failed attempt and token ledger")
    parser.add_argument("--only", choices=[*CASE_IDS, *map(str, range(1, 7))],
                        help="run just one case by ID or number; existing attempts are never retried")
    parser.add_argument("--data-dir", type=Path, default=ROOT / "artifacts" / "live-qwen-budget")
    parser.add_argument("--report", type=Path, default=ROOT / "artifacts" / "live-qwen-report.json")
    args = parser.parse_args()
    if not args.live:
        parser.error("No network calls made. Add --live only after explicit authorization.")
    if args.only and args.only.isdigit():
        args.only = CASE_IDS[int(args.only) - 1]
    if args.probe_only and args.only not in (None, "compatibility"):
        parser.error("--probe-only can only be combined with --only 1 / compatibility")
    report = asyncio.run(evaluate(args))
    print(json.dumps({"report": str(args.report.resolve()), "attempted_cases": report.get("attempted_cases", 0),
                      "completed_exchanges": report.get("completed_exchanges", 0),
                      "charged_tokens": report.get("usage", {}).get("charged_tokens", 0)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
