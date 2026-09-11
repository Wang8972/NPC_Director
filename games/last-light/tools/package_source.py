#!/usr/bin/env python3
"""Package source, real assets and labelled evidence; never credentials or SDK caches."""
from __future__ import annotations
import hashlib
import json
from pathlib import Path
import zipfile

ROOT=Path(__file__).resolve().parents[1]
ALLOWED={"Art","Assets","Packages","ProjectSettings","backend","Docs","tools","vendor"}
ROOT_FILES={"README.md","pyproject.toml",".env.example",".gitignore","DEPENDENCIES.json","ISSUES.md"}
SKIP={".git",".blender-cache",".unityrefs",".dotnet",".wheelcheck",".compile",".nuget",".venv","__pycache__","bin","obj",".pytest_cache",".ruff_cache"}
EVIDENCE={"pytest.xml","pytest.log","actor-reference-compile.log","http-mock-smoke.log","csharp-syntax.json","csharp-ui-syntax.json","validation.json","live-qwen-report.json","content-subsystem-report.json","context-size-report.json"}


def include(path):
    relative=path.relative_to(ROOT)
    if path.name in {"IMPLEMENTATION_DRAFT_SUPERSEDED.md","UnityMock.cs"} or path.suffix in {".blend1",".blend2"}:return False
    if any(p in SKIP for p in relative.parts):return False
    if path.suffix in {".pyc",".sqlite",".db"} or path.name.endswith((".sqlite-wal",".sqlite-shm")):return False
    if relative.parts[0] in ALLOWED:return True
    if len(relative.parts)==1 and path.name in ROOT_FILES:return True
    if relative.parts[0]=="artifacts":
        if len(relative.parts)==2 and path.name in EVIDENCE:return True
        if len(relative.parts)==3 and relative.parts[1]=="mock":
            return path.name.endswith((".view.json",".sequence.json"))
        if len(relative.parts)>=3 and relative.parts[1]=="presentation":
            return path.suffix in {".json",".png",".gif",".mp4",".txt"} and not any(p in {"turntable","motions","faces"} for p in relative.parts[2:-1])
    return False


def main():
    target=ROOT/"Builds/LastLight-source-and-mock.zip"
    target.parent.mkdir(exist_ok=True)
    files=[p for p in sorted(ROOT.rglob("*")) if p.is_file() and not p.is_symlink() and include(p)]
    manifest=[]
    with zipfile.ZipFile(target,"w",zipfile.ZIP_DEFLATED,compresslevel=7) as archive:
        for file in files:
            relative=file.relative_to(ROOT).as_posix()
            archive.write(file,"last-light/"+relative)
            manifest.append({"path":relative,"size":file.stat().st_size,"sha256":hashlib.sha256(file.read_bytes()).hexdigest()})
        archive.writestr("last-light/SOURCE_PACKAGE_MANIFEST.json",json.dumps({"kind":"source + independent Blender/FBX art + local mock; not a Windows binary",
            "windows_player_status":"not_built_on_this_mac; use tools/build_windows.ps1", "files":manifest},ensure_ascii=False,indent=2))
    with zipfile.ZipFile(target) as archive:
        assert archive.testzip() is None
        assert not any(n.endswith("/.env") or "/.dotnet/" in n or "/.wheelcheck/" in n for n in archive.namelist())
    print(json.dumps({"path":str(target),"files":len(files),"bytes":target.stat().st_size},ensure_ascii=False))


if __name__=="__main__":main()
