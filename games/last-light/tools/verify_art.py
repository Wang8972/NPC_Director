"""Blender FBX round-trip and deformation checks, not Unity validation."""
from pathlib import Path
import json, math
import bpy
ROOT=Path(__file__).resolve().parents[1]
manifest=json.loads((ROOT/'Assets/LastLight/Art/manifest.json').read_text())
report={'kind':'Blender 4.5 FBX round-trip, not Unity import or Player verification','characters':[],'motion':{},'errors':[]}
for character in manifest['characters']:
    bpy.ops.wm.read_factory_settings(use_empty=True)
    bpy.ops.import_scene.fbx(filepath=str(ROOT/character['file']))
    rigs=[o for o in bpy.context.scene.objects if o.type=='ARMATURE']
    meshes=[o for o in bpy.context.scene.objects if o.type=='MESH']
    assert len(rigs)==1,character['id']
    rig=rigs[0];names=set(rig.data.bones.keys());assert set(manifest['bones'])<=names
    skin=next(o for o in meshes if o.data.shape_keys)
    shapes={k.name for k in skin.data.shape_keys.key_blocks};assert set(character['blendshapes'])<=shapes
    basis=skin.data.shape_keys.key_blocks['Basis']
    for name in ('happy','sad','angry','surprised','relieved_smile','concerned','stern','suspicious','blink'):
        shape=skin.data.shape_keys.key_blocks[name]
        assert any((a.co-b.co).length>1e-6 for a,b in zip(shape.data,basis.data)),(character['id'],name)
    assert all(v.groups for v in skin.data.vertices),'unweighted character vertices'
    report['characters'].append({'id':character['id'],'bones':len(names),'blendshapes':len(shapes),'weighted_vertices':len(skin.data.vertices)})
bpy.ops.wm.read_factory_settings(use_empty=True)
bpy.ops.import_scene.fbx(filepath=str(ROOT/'Assets/LastLight/Art/Motion/rescue_motion.fbx'))
names=[a.name for a in bpy.data.actions]
for clip in manifest['clips']:
    matches=[name for name in names if name==clip['id'] or name.endswith('|'+clip['id']) or name.endswith('_'+clip['id'])]
    assert matches,(clip['id'],names)
report['motion']={'imported_actions':names,'expected':len(manifest['clips'])}
report['passed']=True
(ROOT/'artifacts/presentation/art-roundtrip.json').write_text(json.dumps(report,indent=2)+'\n')
print('ART_ROUNDTRIP_OK',len(report['characters']),len(names))
