"""Assemble an isolated Unity/P4 workspace. Never connects to or submits to P4."""
from __future__ import annotations
import argparse,hashlib,json,shutil,subprocess,sys,zipfile
from pathlib import Path

GAME=Path(__file__).resolve().parents[1]
REPO=GAME.parents[1]
def digest(path):return hashlib.sha256(path.read_bytes()).hexdigest()
def safe_target(root,relative):
    rel=Path(relative)
    if rel.is_absolute() or '..' in rel.parts:raise ValueError('Unsafe relative path: '+relative)
    target=root/rel
    if not target.resolve().is_relative_to(root):raise ValueError('Workspace symlink escapes root: '+relative)
    return target

def materialize(workspace,archive=None,wheel=None,check_only=False):
    workspace=workspace.expanduser().resolve()
    if not (REPO/'src/npc_director').is_dir():raise ValueError('Run this script from the NPC Director Git checkout.')
    if any((p/'.git').exists() for p in (workspace,*workspace.parents)):
        raise ValueError('Choose an independent workspace outside every Git checkout; do not overlay Git and P4.')
    raw=subprocess.check_output(['git','ls-files','-z','--','games/last-light'],cwd=REPO).decode()
    sources={Path(name).relative_to('games/last-light').as_posix():REPO/name for name in raw.split('\0') if name}
    if not sources:raise ValueError('No versioned game code. Stage or commit the import first.')
    sources['.p4ignore']=GAME/'integration/p4ignore.template'
    lock=json.loads((GAME/'integration/assets.lock.json').read_text())
    assets={entry['path']:entry for entry in lock['files']}
    overlap=set(sources)&set(assets)
    if overlap:raise ValueError('Git/P4 ownership overlaps: '+', '.join(sorted(overlap)))
    state=workspace/'.code-sync.json'
    previous=json.loads(state.read_text()) if state.exists() else {'files':{}}
    changes=[]
    for relative,source in sources.items():
        target=safe_target(workspace,relative)
        if target.exists() and digest(target)!=digest(source):
            if previous.get('files',{}).get(relative)!=digest(target):
                raise ValueError('Local code edit or unmanaged file would be overwritten: '+relative)
        changes.append((source,target))
    retired=[]
    for relative,old_hash in previous.get('files',{}).items():
        target=safe_target(workspace,relative)
        if relative not in sources and target.is_file():
            if digest(target)!=old_hash:raise ValueError('Removed code has local edits: '+relative)
            retired.append(target)
    if archive:
        with zipfile.ZipFile(archive) as z:
            expected=set(assets)|{'P4_ASSET_MANIFEST.json'}
            if set(z.namelist())!=expected:raise ValueError('Asset archive file list does not match the pinned manifest.')
            for relative,entry in assets.items():
                data=z.read(relative)
                if len(data)!=entry['size'] or hashlib.sha256(data).hexdigest()!=entry['sha256']:
                    raise ValueError('Asset hash mismatch: '+relative)
                target=safe_target(workspace,relative)
                if target.exists() and digest(target)!=entry['sha256']:
                    raise ValueError('Existing P4-owned asset differs; refusing to overwrite: '+relative)
    if wheel and (not wheel.is_file() or wheel.suffix!='.whl'):raise ValueError('Provide a valid NPC Director wheel.')
    if check_only:return {'checked':True,'code_files':len(sources),'asset_files':len(assets) if archive else 0,'p4_submitted':False}
    workspace.mkdir(parents=True,exist_ok=True)
    if archive:
        with zipfile.ZipFile(archive) as z:
            for relative in assets:
                target=safe_target(workspace,relative);target.parent.mkdir(parents=True,exist_ok=True)
                if not target.exists():target.write_bytes(z.read(relative))
    for source,target in changes:
        target.parent.mkdir(parents=True,exist_ok=True)
        if not target.exists() or digest(target)!=digest(source):shutil.copy2(source,target)
    # All conflict checks completed before any mutation; assets are never retired.
    for target in retired:target.unlink()
    wheel_dir=workspace/'vendor/wheels';wheel_dir.mkdir(parents=True,exist_ok=True)
    if wheel:
        target=wheel_dir/wheel.name
        if not target.exists() or digest(target)!=digest(wheel):shutil.copy2(wheel,target)
    else:
        subprocess.run([sys.executable,'-m','pip','wheel','--no-deps','--no-build-isolation','--wheel-dir',str(wheel_dir),str(REPO)],check=True)
    revision=subprocess.check_output(['git','rev-parse','HEAD'],cwd=REPO,text=True).strip()
    dirty=bool(subprocess.check_output(['git','status','--porcelain','--','games/last-light'],cwd=REPO,text=True).strip())
    state.write_text(json.dumps({'git_revision':revision,'source_dirty':dirty,'files':{p:digest(s) for p,s in sources.items()},
        'p4_submitted':False,'director_wheels':{p.name:digest(p) for p in wheel_dir.glob('*.whl')},'ownership':'Git code snapshot; art stays P4-owned'},ensure_ascii=False,indent=2)+'\n')
    return {'workspace':str(workspace),'code_files':len(sources),'assets_imported':len(assets) if archive else 0,'git_revision':revision,'source_dirty':dirty,'p4_submitted':False}

if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--workspace',type=Path,required=True)
    parser.add_argument('--assets-archive',type=Path)
    parser.add_argument('--director-wheel',type=Path)
    parser.add_argument('--check-only',action='store_true')
    args=parser.parse_args()
    print(json.dumps(materialize(args.workspace,args.assets_archive,args.director_wheel,args.check_only),ensure_ascii=False))
