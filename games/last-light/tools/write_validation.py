#!/usr/bin/env python3
"""Summarize observed evidence, without upgrading mocks into Windows/live passes."""
import hashlib
import json
from pathlib import Path
import sqlite3
import subprocess
import xml.etree.ElementTree as ET

ROOT=Path(__file__).resolve().parents[1]


def digest(paths):
    h=hashlib.sha256()
    for path in sorted(paths):
        h.update(path.relative_to(ROOT).as_posix().encode());h.update(b'\0');h.update(path.read_bytes())
    return h.hexdigest()


def main():
    report={'kind':'local implementation evidence; Windows validation pending',
        'source_sha256':digest([*ROOT.glob('backend/last_light/**/*.py'),*ROOT.glob('backend/last_light/**/*.json'),
                               *ROOT.glob('Assets/**/*.cs'),*ROOT.glob('Packages/manifest.json')]),
        'windows':{'editor_build':'not_run','player_build':'not_run','screenshots':'not_run','fps':'not_measured','playtime':'not_measured'},
        'warnings':['Live AI validation is incomplete. CPU previews are not Unity screenshots.']}
    junit=ROOT/'artifacts/pytest.xml'
    if junit.exists():
        suites=ET.parse(junit).getroot().findall('testsuite')
        report['python_tests']={key:sum(int(s.attrib.get(key,0)) for s in suites) for key in ['tests','failures','errors','skipped']}
    for name in ('csharp-syntax','csharp-ui-syntax'):
        path=ROOT/'artifacts'/f'{name}.json'
        if path.exists():report[name]=json.loads(path.read_text())
    live=ROOT/'artifacts/live-qwen-report.json'
    if live.exists():
        data=json.loads(live.read_text())
        report['live_ai']={'model':data['model'],'budget':200000,
            'cases':[{k:c.get(k) for k in ['id','status','error','coverage','action_execution']} for c in data['cases']],
            'earlier_failed_attempts':len(data.get('earlier_attempts',[]))}
    content=ROOT/'artifacts/content-subsystem-report.json'
    if content.exists():
        data=json.loads(content.read_text())
        report['content_followup']={k:data.get(k) for k in ['kind','status','author','reviewer','error_type','published','full_game_episode_passed']}
    ledger=ROOT/'artifacts/live-qwen-budget/director/usage.sqlite'
    if ledger.exists():
        db=sqlite3.connect(ledger)
        charged,actual,unknown,calls=db.execute("SELECT COALESCE(SUM(CASE WHEN status='reserved' THEN reserved ELSE charged END),0),COALESCE(SUM(CASE WHEN usage_known=1 THEN charged ELSE 0 END),0),SUM(CASE WHEN usage_known=0 THEN 1 ELSE 0 END),COUNT(*) FROM model_calls").fetchone()
        report['live_budget']={'ceiling':200000,'charged_tokens':charged,'supplier_reported_tokens':actual,'unknown_usage_calls':unknown,'model_calls':calls,'within_budget':charged<=200000}
        db.close()
    report['mock_previews']={'kind':'Historical primitive previews superseded by independent Blender assets',
        'current_directory':'artifacts/presentation','unity_player_capture':False}
    art=ROOT/'Assets/LastLight/Art/manifest.json'
    if art.exists():
        assets=json.loads(art.read_text())
        report['art_assets']={'source':'Original Blender low-poly meshes, skinning, expressions and clips',
            'blender':assets['blender'],'characters':len(assets['characters']),'props':len(assets['props']),'clips':len(assets['clips']),
            'files_hash_valid':all((ROOT/path).is_file() and hashlib.sha256((ROOT/path).read_bytes()).hexdigest()==value for path,value in assets['sha256'].items())}
    for key,relative in [('art_roundtrip','artifacts/presentation/art-roundtrip.json'),
                         ('csharp_presentation_tests','artifacts/presentation/csharp-timeline-tests.json'),
                         ('presentation_fixtures','artifacts/presentation/fixtures/manifest.json')]:
        path=ROOT/relative
        if path.exists():report[key]=json.loads(path.read_text())
    report['actor_reference_compile']={'scope':'TrainActor, PresentationAssets, PresentationSockets, GameDtos, PresentationClock',
        'reference_version':'UnityEngine.Modules 2021.3.33 netstandard2.0; NOT locked Unity 6000.0.62f1 build',
        'log':'artifacts/actor-reference-compile.log'}
    report['presentation_live_calls']=0
    (ROOT/'artifacts').mkdir(exist_ok=True)
    (ROOT/'artifacts/validation.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
    manifest=json.loads((ROOT/'Packages/manifest.json').read_text()) if (ROOT/'Packages/manifest.json').exists() else {'dependencies':{}}
    dependency={'unity':'6000.0.62f1','unity_revision':'f99f05b3e950','packages':manifest['dependencies'],'npc_director_version':'0.3.0'}
    sibling=ROOT.parents[1] if (ROOT.parents[1]/'src/npc_director').is_dir() else ROOT.parent/'npc-director'
    if (sibling/'.git').exists():
        dependency['npc_director_source_commit']=subprocess.check_output(['git','rev-parse','HEAD'],cwd=sibling,text=True).strip()
    dependency['vendored_wheels']=[{'file':p.name,'sha256':hashlib.sha256(p.read_bytes()).hexdigest()} for p in (ROOT/'vendor/wheels').glob('*.whl')]
    (ROOT/'DEPENDENCIES.json').write_text(json.dumps(dependency,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps({'python_tests':report.get('python_tests'),'live_budget':report.get('live_budget'),'windows':'pending user verification'},ensure_ascii=False))


if __name__=='__main__':main()
