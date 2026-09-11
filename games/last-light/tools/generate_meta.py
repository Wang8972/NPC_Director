#!/usr/bin/env python3
"""Stable Unity GUIDs. Unity fills importer-specific defaults on first import."""
from pathlib import Path
from uuid import UUID, uuid5

ROOT=Path(__file__).resolve().parents[1]
NAMESPACE=UUID("207a82d1-2c3f-4f40-b431-381e4d58e3fa")


def main():
    created=0
    for path in sorted((ROOT/"Assets").rglob("*")):
        if path.suffix==".meta" or path.name.startswith("."):
            continue
        meta=Path(str(path)+".meta")
        if meta.exists():
            continue
        guid=uuid5(NAMESPACE,path.relative_to(ROOT).as_posix()).hex
        text=f"fileFormatVersion: 2\nguid: {guid}\n"
        if path.is_dir():text+="folderAsset: yes\nDefaultImporter:\n  externalObjects: {}\n  userData:\n  assetBundleName:\n  assetBundleVariant:\n"
        elif path.suffix==".cs":text+="MonoImporter:\n  externalObjects: {}\n  serializedVersion: 2\n  defaultReferences: []\n  executionOrder: 0\n  icon: {fileID: 0}\n  userData:\n  assetBundleName:\n  assetBundleVariant:\n"
        meta.write_text(text,encoding="utf-8");created+=1
    print(f"Created {created} stable Unity metadata files")


if __name__=="__main__":main()
