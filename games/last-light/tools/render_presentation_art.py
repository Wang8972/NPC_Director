"""Blender-rendered source asset previews; explicitly not Unity gameplay captures."""
from pathlib import Path
import json, math, runpy
import bpy
from mathutils import Vector
ROOT=Path(__file__).resolve().parents[1]
art=runpy.run_path(str(ROOT/'tools/build_art.py'),run_name='last_light_art_library')
OUT=ROOT/'artifacts/presentation'

def load_actor(name):
    bpy.ops.wm.open_mainfile(filepath=str(ROOT/'Art/Source'/(name+'.blend')))
    art['camera_and_lights']()
    bpy.context.scene.cycles.samples=12
    return bpy.data.objects['Rig'],bpy.data.objects['Body']

def render(path,width=420,height=480):
    path.parent.mkdir(parents=True,exist_ok=True)
    scene=bpy.context.scene;scene.render.resolution_x=width;scene.render.resolution_y=height
    scene.render.filepath=str(path);bpy.ops.render.render(write_still=True)

faces=['neutral','happy','sad','angry','surprised','relieved_smile','concerned','stern','suspicious']
rig,body=load_actor('lin')
scene=bpy.context.scene
scene.camera.location=(.12,-1.4,1.66);scene.camera.rotation_euler=(Vector((0,-.01,1.61))-scene.camera.location).to_track_quat('-Z','Y').to_euler()
scene.camera.data.ortho_scale=.46
for face in faces:
    for key in body.data.shape_keys.key_blocks:key.value=0
    body.data.shape_keys.key_blocks[face].value=1
    render(OUT/'faces'/(face+'.png'),360,360)
rig,body=load_actor('lin')
for frame in range(24):
    rig.rotation_euler.z=frame*math.tau/24
    render(OUT/'turntable'/f'{frame:03}.png',400,480)
for person,clip in [('lin','announce'),('zhou','reunion'),('chen','repair_kneel'),('xu','offer_item')]:
    rig,body=load_actor(person)
    with bpy.data.libraries.load(str(ROOT/'Art/Source/motion.blend'),link=False) as (data,loaded):loaded.actions=[clip]
    action=loaded.actions[0];rig.animation_data_create();rig.animation_data.action=action
    bpy.context.scene.frame_start=0;bpy.context.scene.frame_end=72
    for frame in range(0,73,4):
        bpy.context.scene.frame_set(frame)
        render(OUT/'motions'/clip/f'{frame:03}.png',400,480)
(OUT/'preview-provenance.json').write_text(json.dumps({'kind':'Blender source asset preview, NOT Unity Player or live AI','faces':faces,'motions':['announce','reunion','repair_kneel','offer_item'],'turntable_frames':24},indent=2)+'\n')
print('PRESENTATION_PREVIEWS_DONE')
