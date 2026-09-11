#!/usr/bin/env python3
"""Capture real rule projections for the local mock and Unity Player fixtures.

These are explicitly labelled mock images, NOT Unity screenshots or GPU evidence.
The same JSON fixtures can be rendered by Unity's --qa-capture workflow on Windows.
"""
from __future__ import annotations
import argparse
import json
from pathlib import Path
import subprocess
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/"backend"),str(ROOT/"backend/tests")]


def fixture_views(out):
    from last_light.engine import WorldEngine
    from test_engine_routes import ready,stabilize,act,control,prepare_stay
    out.mkdir(parents=True,exist_ok=True)
    views=[]
    def save(name,w):
        path=out/(name+".view.json")
        path.write_text(json.dumps(w.view(),ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
        views.append(path)
    save("01-cabin07",WorldEngine(mode="rehearsal"))
    w=ready();w.move("cabin06");save("02-cabin06",w)
    w.move("service");save("03-service",w)
    stabilize(w);act(w,"clear_trolley",helpers=["zhou"]);act(w,"free_internal_door")
    w.move("cabin05");save("04-cabin05",w)
    control(w);act(w,"collect_lamp","lin");act(w,"scout_walkway","lin");act(w,"open_outer_door","lin")
    act(w,"light_walkway","lin");w.move("tunnel");save("05-tunnel",w)
    w=ready()
    for _ in range(16):act(w,"wait")
    w.move("cabin06");save("06-smoke",w)
    w=ready();prepare_stay(w);act(w,"await_rescue");save("07-ending",w)
    # Capture authored before/execution/after data, not a scripted false success.
    for name,action,actor,helpers in [
        ("handoff","take_backup","player",[]),
        ("mother-transfer","move_mother","player",["xu"]),
        ("child-reunion","reunite_child","player",["zhou"]),
    ]:
        w=ready()
        if action=="take_backup":
            w.move("cabin06");assert w.talk_rehearsal("xu","","xu_loan")["ok"]
        elif action=="move_mother":
            act(w,"clear_aisle");act(w,"close_vent");w.move("cabin06")
        else:
            stabilize(w);act(w,"clear_trolley",helpers=["zhou"]);act(w,"free_internal_door");act(w,"check_child");w.move("cabin05")
        from test_engine_routes import step
        proposal=w.propose([step(action,actor,helpers)])
        assert proposal["ok"],proposal
        before=w.view()
        result=w.begin(proposal["plan_id"]);assert result["ok"],result
        execution=w.view()["execution"]
        result=w.complete(execution["id"]);assert result["ok"],result
        (out/(name+".sequence.json")).write_text(json.dumps({"before":before,"execution":execution,"after":w.view()},ensure_ascii=False,indent=2)+"\n")
    return views


def main():
    parser=argparse.ArgumentParser(description="Generate real rule fixtures; render imported assets with Blender, not primitive substitutes.")
    parser.add_argument("--fixtures-only",action="store_true",help="Retained for compatibility; no graphics engine is required.")
    parser.add_argument("--blender",help="Optional Blender executable to regenerate standalone asset previews.")
    args=parser.parse_args()
    out=ROOT/"artifacts/mock"
    views=fixture_views(out)
    print(f"Wrote {len(views)} authoritative world projections and three action sequences: {out}")
    if args.blender:
        subprocess.run([args.blender,"--background","--threads","4","--python-exit-code","2","--python",str(ROOT/"tools/render_presentation_art.py")],check=True)
    else:
        print("Asset previews: artifacts/presentation; historical primitive PNGs are not current Unity evidence.")


if __name__=="__main__":main()
