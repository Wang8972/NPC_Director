"""Original Last Light low-poly assets. Run with Blender 4.5 --background --python.

All meshes, skin weights, expression keys, animation curves and materials are
authored here. No downloaded character or animation library is used.
"""
from pathlib import Path
import sys, math, json, hashlib
import bpy
from mathutils import Vector, Quaternion, Matrix

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / 'Art/Source'
EXPORT = ROOT / 'Assets/LastLight/Art'
EVIDENCE = ROOT / 'artifacts/presentation'
for folder in (SOURCE, EXPORT/'Characters', EXPORT/'Props', EXPORT/'Motion', EVIDENCE):
    folder.mkdir(parents=True, exist_ok=True)

COLORS = {'skin':'C6A28D','hair':'302E2A','cloth':'73817F','pants':'303D45',
          'light':'D5D6CC','metal':'4B616C','amber':'D8A85F','green':'749688',
          'dark':'152630','lip':'906858','white':'E1DDD3','iris':'4D504A'}
MATERIALS={}
def material(name, color=None):
    key=name+str(color)
    if key in MATERIALS and MATERIALS[key].name in bpy.data.materials:return MATERIALS[key]
    value=color or COLORS.get(name,'73817F')
    rgb=tuple(int(value[i:i+2],16)/255 for i in (0,2,4))
    mat=bpy.data.materials.new('LL_'+name)
    mat.diffuse_color=(*rgb,1);mat.use_nodes=True
    bsdf=mat.node_tree.nodes.get('Principled BSDF')
    bsdf.inputs['Base Color'].default_value=(*rgb,1)
    bsdf.inputs['Roughness'].default_value=.72
    mat['source']='tools/build_art.py / original procedural authoring'
    MATERIALS[key]=mat
    return mat

class Mesh:
    def __init__(self):self.v=[];self.f=[];self.mi=[];self.weights=[];self.tags={};self.mats=[]
    def add(self, verts, faces, mat, bone='Root', tag=''):
        start=len(self.v)
        if mat not in self.mats:self.mats.append(mat)
        self.v.extend(verts);self.weights.extend([bone]*len(verts))
        self.f.extend([tuple(start+i for i in f) for f in faces]);self.mi.extend([self.mats.index(mat)]*len(faces))
        if tag:self.tags.setdefault(tag,[]).extend(range(start,len(self.v)))
    def ellipsoid(self, center, radius, mat, bone='Root', tag='', rings=8, sides=12):
        v=[];f=[]
        for j in range(rings+1):
            phi=math.pi*j/rings
            for i in range(sides):
                theta=2*math.pi*i/sides
                v.append(tuple(center[k]+radius[k]*a for k,a in enumerate((math.sin(phi)*math.cos(theta),math.sin(phi)*math.sin(theta),math.cos(phi)))))
        for j in range(rings):
            for i in range(sides):a=j*sides+i;b=j*sides+(i+1)%sides;f.append((a,b,b+sides,a+sides))
        self.add(v,f,mat,bone,tag)
    def box(self,c,s,mat,bone='Root',tag='',bevel=.12):
        # Chamfered cross-section, not a runtime cube primitive.
        x,y,z=[a*.5 for a in s];b=min(x,y)*bevel
        corners=[(-x+b,-y), (x-b,-y),(x,-y+b),(x,y-b),(x-b,y),(-x+b,y),(-x,y-b),(-x,-y+b)]
        v=[(c[0]+a,c[1]+d,c[2]+h) for h in (-z,z) for a,d in corners]
        f=[tuple(reversed(range(8))),tuple(range(8,16))]+[(i,(i+1)%8,(i+1)%8+8,i+8) for i in range(8)]
        self.add(v,f,mat,bone,tag)
    def limb(self,a,b,r1,r2,mat,bone,tag=''):
        a,b=Vector(a),Vector(b);direction=(b-a).normalized()
        u=direction.cross(Vector((0,1,0))).normalized();v=direction.cross(u)
        verts=[];faces=[];sides=10
        for t,r in ((0,r1),(.18,r1),(.82,r2),(1,r2)):
            for i in range(sides):
                p=a.lerp(b,t)+(u*math.cos(i*math.tau/sides)+v*math.sin(i*math.tau/sides)) * r
                verts.append(tuple(p))
        faces += [tuple(reversed(range(sides))),tuple(range(3*sides,4*sides))]
        for j in range(3):
            for i in range(sides):faces.append((j*sides+i,j*sides+(i+1)%sides,(j+1)*sides+(i+1)%sides,(j+1)*sides+i))
        self.add(verts,faces,mat,bone,tag)
    def object(self,name,rig=None):
        if not rig and self.tags:
            root=bpy.data.objects.new(name,None);bpy.context.collection.objects.link(root)
            tagged=set(i for indices in self.tags.values() for i in indices)
            for part, indices in [('Housing',set(range(len(self.v)))-tagged),*[(key,set(value)) for key,value in self.tags.items()]]:
                sub=Mesh(); mapping={old:new for new,old in enumerate(sorted(indices))}
                sub.v=[self.v[i] for i in sorted(indices)];sub.weights=['Root']*len(indices);sub.mats=self.mats
                for face, mi in zip(self.f,self.mi):
                    if all(i in indices for i in face):sub.f.append(tuple(mapping[i] for i in face));sub.mi.append(mi)
                child=sub.object(part);child.parent=root
            return root
        mesh=bpy.data.meshes.new(name+'_Mesh');mesh.from_pydata(self.v,[],self.f);mesh.update()
        ob=bpy.data.objects.new(name,mesh);bpy.context.collection.objects.link(ob)
        for mat in self.mats:mesh.materials.append(mat)
        for face,mi in zip(mesh.polygons,self.mi):face.material_index=mi
        if rig:
            groups={b:ob.vertex_groups.new(name=b) for b in set(self.weights)}
            for i,b in enumerate(self.weights):groups[b].add([i],1,'REPLACE')
            modifier=ob.modifiers.new('Skinned rig','ARMATURE');modifier.object=rig;ob.parent=rig
        return ob

BONES=[('Root',(0,0,0),(0,0,.15),None),('Hips',(0,0,.91),(0,0,1.04),'Root'),
       ('Spine',(0,0,1.04),(0,0,1.20),'Hips'),('Chest',(0,0,1.20),(0,0,1.39),'Spine'),
       ('Neck',(0,0,1.39),(0,0,1.51),'Chest'),('Head',(0,0,1.51),(0,0,1.77),'Neck')]
for sign,side in ((1,'L'),(-1,'R')):
    BONES += [(f'Shoulder_{side}',(sign*.08,0,1.37),(sign*.20,0,1.37),'Chest'),
              (f'UpperArm_{side}',(sign*.20,0,1.37),(sign*.34,0,1.13),f'Shoulder_{side}'),
              (f'Forearm_{side}',(sign*.34,0,1.13),(sign*.43,-.01,.92),f'UpperArm_{side}'),
              (f'Hand_{side}',(sign*.43,-.01,.92),(sign*.47,-.01,.82),f'Forearm_{side}'),
              (f'Grip_{side}',(sign*.47,-.01,.86),(sign*.47,-.065,.86),f'Hand_{side}'),
              (f'Thigh_{side}',(sign*.095,0,.94),(sign*.10,0,.53),'Hips'),
              (f'Shin_{side}',(sign*.10,0,.53),(sign*.10,0,.12),f'Thigh_{side}'),
              (f'Foot_{side}',(sign*.10,0,.12),(sign*.10,-.13,.065),f'Shin_{side}'),
              (f'Toe_{side}',(sign*.10,-.13,.065),(sign*.10,-.21,.065),f'Foot_{side}'),
              (f'Eye_{side}',(sign*.046,-.105,1.665),(sign*.046,-.15,1.665),'Head')]

def rig():
    arm=bpy.data.armatures.new('LastLight_Generic');ob=bpy.data.objects.new('Rig',arm)
    bpy.context.collection.objects.link(ob);bpy.context.view_layer.objects.active=ob;ob.select_set(True)
    bpy.ops.object.mode_set(mode='EDIT')
    for name,head,tail,parent in BONES:
        bone=arm.edit_bones.new(name);bone.head=head;bone.tail=tail
        if parent:bone.parent=arm.edit_bones[parent]
    bpy.ops.object.mode_set(mode='OBJECT')
    for b in ob.pose.bones:b.rotation_mode='XYZ'
    return ob

PROFILES={
 'player':('9B785F','303A43','302C27',1.00,0),
 'lin':('496D7C','293B4B','242925',.98,1),
 'zhou':('958574','374248','352C25',1.03,0),
 'chen':('637E75','354442','35342D',1.01,0),
 'xu':('A7A494','4A5357','33302E',.97,1),
 'mother':('8B8290','505160','827F79',.94,2),
 'xiaoman':('B8A175','4C626D','342B23',.76,1),
 'passenger05':('737C83','42474F','4D4036',.99,0),
 'passenger07':('8F8C7B','39464D','413D34',1.02,0),
}

def character(id):
    coat,pants,hair,height,hairkind=PROFILES[id];r=rig();m=Mesh()
    c=material(id+'_cloth',coat);p=material(id+'_pants',pants);h=material(id+'_hair',hair)
    skin=material('skin');dark=material('dark');light=material('light');lip=material('lip')
    m.ellipsoid((0,0,1.17),(.206,.118,.265),c,'Chest',rings=7,sides=12)
    m.box((0,0,1.00),(.32,.20,.21),c,'Spine',bevel=.3)
    m.ellipsoid((0,0,.92),(.164,.112,.115),p,'Hips',rings=4)
    m.limb((0,0,1.37),(0,0,1.53),.055,.054,skin,'Neck')
    m.ellipsoid((0,-.01,1.638),(.108,.103,.142),skin,'Head',rings=12,sides=16)
    m.ellipsoid((0,.014,1.724),(.112,.105,.065),h,'Head',rings=6,sides=16)
    m.ellipsoid((0,.083,1.658),(.103,.037,.097),h,'Head',rings=6)
    if hairkind==1:m.ellipsoid((0,.125,1.68),(.055,.06,.068),h,'Head')
    if hairkind==2:
        for side in (-1,1):m.ellipsoid((side*.09,.01,1.66),(.034,.095,.095),h,'Head',rings=5)
    for side,label in ((1,'L'),(-1,'R')):
        m.ellipsoid((side*.11,0,1.632),(.018,.026,.031),skin,'Head',rings=5,sides=8)
        m.ellipsoid((side*.046,-.108,1.665),(.030,.013,.014),material('white'),f'Eye_{label}',f'eye_{label}',rings=5,sides=10)
        m.ellipsoid((side*.046,-.119,1.665),(.012,.004,.012),material('iris'),f'Eye_{label}',f'eye_{label}',rings=5,sides=10)
        m.ellipsoid((side*.046,-.123,1.665),(.006,.002,.007),dark,f'Eye_{label}',f'eye_{label}',rings=4,sides=8)
        m.box((side*.046,-.107,1.696),(.059,.012,.010),h,'Head',f'brow_{label}')
        a=(side*.20,0,1.365);b=(side*.34,0,1.13);d=(side*.43,-.01,.92)
        m.ellipsoid(a,(.079,.081,.078),c,f'UpperArm_{label}',rings=5)
        m.limb(a,b,.073,.058,c,f'UpperArm_{label}')
        m.ellipsoid(b,(.060,.060,.06),c,f'Forearm_{label}',rings=5)
        m.limb(b,d,.056,.039,c,f'Forearm_{label}')
        m.limb((side*.422,-.01,.94),d,.045,.043,light,f'Forearm_{label}')
        m.ellipsoid((side*.457,-.01,.865),(.038,.027,.060),skin,f'Hand_{label}',rings=6,sides=10)
        m.ellipsoid((side*.423,-.032,.871),(.014,.021,.035),skin,f'Grip_{label}',rings=5,sides=8)
        hip=(side*.095,0,.94);knee=(side*.10,0,.53);foot=(side*.10,0,.12)
        m.limb(hip,knee,.09,.066,p,f'Thigh_{label}')
        m.ellipsoid(knee,(.067,.064,.068),p,f'Shin_{label}',rings=5)
        m.limb(knee,foot,.064,.048,p,f'Shin_{label}')
        m.ellipsoid((side*.10,-.055,.078),(.064,.125,.072),dark,f'Foot_{label}',rings=5)
        m.box((side*.10,-.06,.031),(.13,.25,.028),material('metal'),f'Foot_{label}')
    m.ellipsoid((0,-.11,1.625),(.019,.038,.036),skin,'Head',rings=5,sides=8)
    m.ellipsoid((0,-.108,1.592),(.036,.009,.006),lip,'Head','mouth',rings=4,sides=12)
    # Garment construction gives recognisable silhouettes without villain coding.
    m.box((0,-.12,1.22),(.014,.012,.34),light,'Chest')
    for side in (-1,1):m.box((side*.067,-.108,1.368),(.10,.025,.055),light,'Chest')
    if id=='lin':
        m.box((.108,-.117,1.27),(.057,.014,.025),material('amber'),'Chest')
        m.box((-.07,-.133,1.34),(.07,.028,.045),material('green'),'Chest')
    elif id=='chen':
        m.box((.10,-.13,1.19),(.115,.025,.12),c,'Chest')
        for x in (-.046,.046):m.box((x,-.127,1.67),(.072,.009,.044),material('metal'),'Head')
        # Recessed clear openings, not opaque black glasses.
        for x in (-.046,.046):m.box((x,-.133,1.67),(.058,.005,.030),material('white'),'Head')
    elif id in ('xu','mother'):m.box((0,-.132,1.27),(.065,.024,.2),material('green'),'Chest')
    elif id=='zhou':
        m.box((-.11,-.127,1.19),(.095,.018,.10),c,'Chest')
        for z in (1.12,1.21,1.30):m.ellipsoid((0,-.138,z),(.009,.004,.009),dark,'Chest',rings=4,sides=6)
    ob=m.object('Body',r);ob.shape_key_add(name='Basis')
    for preset in ('neutral','happy','sad','angry','surprised','relieved_smile','concerned','stern','suspicious','blink'):
        key=ob.shape_key_add(name=preset)
        for label,sign in (('L',1),('R',-1)):
            for i in m.tags.get('brow_'+label,[]):
                v=key.data[i].co;local=(v.x-sign*.046)*sign
                if preset in ('angry','stern'):v.z+=local*.30
                if preset in ('sad','concerned'):v.z-=local*.25;v.z+=.005
                if preset=='surprised':v.z+=.02
                if preset=='suspicious':v.z+=.008 if sign==1 else -.003
            for i in m.tags.get('eye_'+label,[]):
                v=key.data[i].co
                if preset=='blink':v.z=1.665+(v.z-1.665)*.035
                elif preset in ('happy','relieved_smile'):v.z=1.665+(v.z-1.665)*.75
                elif preset=='surprised':v.z=1.665+(v.z-1.665)*1.22
        for i in m.tags.get('mouth',[]):
            v=key.data[i].co
            if preset in ('happy','relieved_smile'):v.z+=abs(v.x)*(.33 if preset=='happy' else .19)
            if preset in ('sad','concerned'):v.z-=abs(v.x)*.20
            if preset=='surprised':v.x*=.55;v.z=1.591+(v.z-1.592)*2.8
            if preset in ('angry','stern'):v.z=1.592+(v.z-1.592)*.55
    r.scale=(height,)*3
    ob['actor_id']=id;ob['face_presets']='neutral,happy,sad,angry,surprised,relieved_smile,concerned,stern,suspicious'
    return r,ob

CLIPS=['idle','walk','turn','sit_down','stand_up','observe','nod','small_nod','shake_head','step_forward','step_back','point','reach_out','cross_arms','open_palms',
       'idle_alert','inspect_stand','inspect_kneel','read_record','reach_item','lift_item','carry_item','offer_item','receive_item','connect_cable','disconnect_cable','switch_off','switch_on','repair_kneel','verify_meter','operate_door','brace_cart','push_cart','support_person','escort_walk','lift_stretcher','unfold_stretcher','use_phone','use_radio','announce','point_route','place_item','gather_signal','confirm_nod','stop_work','hold_position','seated','labored_breath','reunion','carried_litter','look_radio','check_patient']
LOOPS={'idle','idle_alert','walk','escort_walk','carry_item','hold_position','seated','labored_breath','carried_litter'}
def aim_pose_bone(r,name,target):
    bone=r.pose.bones[name]
    direction=bone.tail-bone.head
    desired=Vector(target)-bone.head
    if desired.length<1e-5:return
    rotation=direction.rotation_difference(desired) @ bone.matrix.to_quaternion()
    bone.matrix=Matrix.Translation(bone.head) @ rotation.to_matrix().to_4x4()
    bpy.context.view_layer.update()

def solve_arm(r,side,target,blend):
    bpy.context.view_layer.update()
    upper=r.pose.bones['UpperArm_'+side];lower=r.pose.bones['Forearm_'+side];hand=r.pose.bones['Hand_'+side]
    start=upper.head.copy();goal=hand.head.lerp(Vector(target),blend)
    a=(lower.head-start).length;b=(hand.head-lower.head).length
    delta=goal-start;length=min(a+b-.002,max(.01,delta.length));direction=delta.normalized()
    pole=Vector((1 if side=='L' else -1,0,-.25));pole=(pole-direction*pole.dot(direction)).normalized()
    adjacent=(a*a+length*length-b*b)/(2*length)
    elbow=start+direction*adjacent+pole*math.sqrt(max(0,a*a-adjacent*adjacent))
    aim_pose_bone(r,'UpperArm_'+side,elbow);aim_pose_bone(r,'Forearm_'+side,goal)

def animations(r):
    records=[]
    for name in dict.fromkeys(CLIPS):
        action=bpy.data.actions.new(name);action.use_fake_user=True;r.animation_data_create();r.animation_data.action=action
        seconds=1.2 if name in ('nod','small_nod','confirm_nod','shake_head') else 1.0 if name in ('walk','escort_walk') else 2.4
        frames=int(seconds*30)
        for frame in range(0,frames+1,3):
            t=frame/frames;wave=math.sin(t*math.pi);cycle=math.sin(t*math.tau)
            for b in r.pose.bones:b.rotation_euler=(0,0,0);b.location=(0,0,0)
            def rot(b,x=0,y=0,z=0):r.pose.bones[b].rotation_euler=tuple(math.radians(a) for a in (x,y,z))
            active=1 if name in LOOPS else wave
            if name in ('walk','escort_walk'):
                for side,sign in (('L',1),('R',-1)):
                    rot('Thigh_'+side,cycle*22*sign);rot('Shin_'+side,max(0,-cycle*sign)*30)
                    rot('UpperArm_'+side,-cycle*14*sign)
            if name in ('nod','small_nod','confirm_nod'):rot('Head',cycle*(5 if name=='small_nod' else 12))
            if name=='shake_head':rot('Head',0,cycle*18)
            if name in ('observe','inspect_stand','idle_alert'):rot('Head',5,cycle*10)
            if name in ('step_forward','step_back','turn'):rot('Chest',wave*(8 if name=='step_forward' else -6),wave*14 if name=='turn' else 0)
            if name in ('point','point_route','gather_signal','announce'):
                rot('UpperArm_R',-70*active,0,15*active);rot('Forearm_R',-15*active);rot('Head',0,-10*active)
            if name in ('reach_out','reach_item','lift_item','place_item','offer_item','receive_item','connect_cable','disconnect_cable','operate_door','switch_off','switch_on'):
                rot('UpperArm_R',-45*active,0,14*active);rot('Forearm_R',-35*active)
                rot('Hand_R',15*cycle if name in ('connect_cable','disconnect_cable','switch_off','switch_on') else 0)
                if name in ('offer_item','receive_item'):rot('UpperArm_L',-38*active,0,-12*active);rot('Forearm_L',-25*active)
            if name in ('cross_arms','open_palms'):
                for side,sign in (('L',1),('R',-1)):
                    rot('UpperArm_'+side,-30*wave,0,sign*(38 if name=='cross_arms' else -28)*wave)
                    rot('Forearm_'+side,-75*wave if name=='cross_arms' else -30*wave)
            if name in ('read_record','carry_item','brace_cart','push_cart','support_person','lift_stretcher','hold_position','unfold_stretcher'):
                for side,sign in (('L',1),('R',-1)):
                    rot('UpperArm_'+side,-38*active,0,-sign*8*active);rot('Forearm_'+side,-40*active)
                rot('Chest',10*active if name in ('push_cart','unfold_stretcher') else 0)
            if name in ('inspect_kneel','repair_kneel','verify_meter','check_patient','reunion'):
                r.pose.bones['Hips'].location.y=-.34*wave
                rot('Thigh_L',-65*wave);rot('Shin_L',130*wave);rot('Foot_L',-65*wave);rot('Thigh_R',-65*wave);rot('Shin_R',130*wave);rot('Foot_R',-65*wave)
                rot('Chest',18*wave);rot('Head',10*wave)
                rot('UpperArm_R',-48*wave);rot('Forearm_R',-34*wave)
                rot('Hand_R',cycle*18 if name=='repair_kneel' else 0)
                rot('UpperArm_L',-36*wave);rot('Forearm_L',-40*wave)
            if name in ('seated','sit_down','stand_up'):
                k=1 if name=='seated' else (1-t if name=='stand_up' else t)
                r.pose.bones['Hips'].location.y=-.32*k
                for side in ('L','R'):rot('Thigh_'+side,-80*k);rot('Shin_'+side,80*k)
            if name in ('use_phone','use_radio','look_radio'):
                rot('UpperArm_R',-30*wave);rot('Forearm_R',-115*wave);rot('Head',4,0,8*wave)
            if name=='carried_litter':rot('Hips',-85);r.pose.bones['Hips'].location.y=-.12
            if name=='labored_breath':rot('Chest',5+cycle*2);rot('Head',8);rot('UpperArm_R',-20);rot('Forearm_R',-35)
            if name in ('idle','idle_alert'):rot('Chest',cycle*.8)
            bpy.context.view_layer.update()
            if name in ('inspect_kneel','repair_kneel','verify_meter','check_patient','reunion'):
                floor=min(r.pose.bones['Foot_'+side].head.z-.12 for side in ('L','R'))
                r.pose.bones['Hips'].location.y-=floor
                bpy.context.view_layer.update()
            targets={}
            if name in ('point','point_route','gather_signal','announce'):targets={'R':(-.35,-.48,1.42)}
            if name in ('reach_out','reach_item','lift_item','place_item','connect_cable','disconnect_cable','operate_door','switch_off','switch_on'):targets={'R':(-.25,-.43,1.10)}
            if name in ('offer_item','receive_item','carry_item','hold_position'):targets={'R':(-.18,-.34,1.10),'L':(.18,-.34,1.10)}
            if name in ('brace_cart','push_cart','support_person','lift_stretcher','unfold_stretcher'):targets={'R':(-.30,-.38,.99),'L':(.30,-.38,.99)}
            if name=='read_record':targets={'R':(-.14,-.31,1.27),'L':(.14,-.31,1.27)}
            if name=='cross_arms':targets={'R':(.10,-.23,1.25),'L':(-.10,-.30,1.23)}
            if name=='open_palms':targets={'R':(-.46,-.24,1.13),'L':(.46,-.24,1.13)}
            if name in ('repair_kneel','inspect_kneel','verify_meter','check_patient','reunion'):targets={'R':(-.22,-.37,.62),'L':(.19,-.34,.66)}
            if name in ('use_phone','use_radio','look_radio'):targets={'R':(-.11,-.10,1.58)}
            for side,target in targets.items():solve_arm(r,side,target,active)
            for b in r.pose.bones:
                b.keyframe_insert(data_path='rotation_euler',frame=frame);b.keyframe_insert(data_path='location',frame=frame)
        records.append({'id':name,'duration':seconds,'loop':name in LOOPS,'contact':.55,'release':.78})
    r.animation_data.action=None
    for b in r.pose.bones:b.rotation_euler=(0,0,0);b.location=(0,0,0)
    return records

def reset():
    bpy.ops.object.select_all(action='SELECT');bpy.ops.object.delete(use_global=False)
    for data in list(bpy.data.actions):bpy.data.actions.remove(data)

def export_fbx(path,objects,animation=False):
    bpy.ops.object.select_all(action='DESELECT')
    for ob in objects:
        ob.select_set(True)
        for child in ob.children_recursive:child.select_set(True)
    bpy.context.view_layer.objects.active=objects[0]
    bpy.ops.export_scene.fbx(filepath=str(path),use_selection=True,object_types=({'ARMATURE','EMPTY'} if animation else {'ARMATURE','MESH','EMPTY'}),
        axis_forward='-Z',axis_up='Y',add_leaf_bones=False,bake_anim=animation,bake_anim_use_all_actions=animation,
        bake_anim_use_nla_strips=False,bake_anim_simplify_factor=0,apply_unit_scale=True,use_mesh_modifiers=True,
        mesh_smooth_type='FACE',path_mode='AUTO')

def prop(id):
    m=Mesh();metal=material('metal');dark=material('dark');pale=material('light');green=material('green');amber=material('amber')
    if id in ('backup','medical'):
        m.box((0,0,.20),(.34,.22,.40),green if id=='backup' else pale,bevel=.35)
        m.box((0,-.118,.28),(.19,.017,.095),dark);m.box((0,-.132,.29),(.13,.006,.042),green)
        for x in (-.115,.115):m.box((x,0,.43),(.035,.045,.10),dark)
        m.box((0,0,.475),(.26,.045,.035),dark)
        for x in (-.105,-.075,-.045):m.box((x,-.12,.12),(.013,.014,.065),metal)
    elif id=='tools':
        m.box((0,0,.15),(.42,.23,.30),material('cloth'),bevel=.25)
        m.box((0,0,.33),(.18,.045,.045),dark);m.box((0,-.125,.13),(.26,.02,.12),metal)
    elif id=='spares':m.box((0,0,.06),(.24,.16,.12),pale);m.box((0,-.09,.07),(.15,.015,.035),amber)
    elif id in ('meter','radio_handset'):
        m.box((0,0,.09),(.08,.04,.18),dark);m.box((0,-.024,.13),(.058,.008,.05),green)
        m.box((0,0,.21),(.012,.012,.08),metal)
    elif id in ('lamp','driver','cup'):
        height=.19 if id!='driver' else .22;radius=.045 if id=='cup' else .025
        m.limb((0,0,0),(0,0,height),radius,radius,metal if id=='cup' else amber,'Root')
        m.limb((0,0,height),(0,0,height+.045),radius*1.1,radius*1.1,pale,'Root')
    elif id=='stretcher':
        m.box((0,0,.035),(.62,1.80,.07),green)
        for x in (-.36,.36):m.limb((x,-1.05,.045),(x,1.05,.045),.022,.022,metal,'Root')
        for y in (-.50,.5):m.box((0,y,.081),(.7,.08,.01),dark)
    elif id=='cart':
        m.box((0,0,.43),(.65,.46,.66),metal)
        for z in (.26,.5,.72):m.box((0,-.24,z),(.54,.02,.15),pale)
        for x in (-.27,.27):
            for y in (-.17,.17):m.ellipsoid((x,y,.075),(.06,.025,.06),dark,rings=5,sides=10)
        m.box((0,.25,.83),(.56,.035,.045),dark)
    elif id=='door':
        for x in (-.65,.65):m.box((x,0,1.05),(.12,.15,2.1),metal)
        m.box((0,0,2.12),(1.42,.15,.14),metal)
        m.box((0,0,1.03),(1.17,.09,2.00),pale,tag='DoorLeaf')
        m.box((0,-.055,1.47),(.53,.013,.62),dark,tag='DoorLeaf')
        m.box((.40,-.09,1.0),(.045,.07,.25),metal,tag='DoorLeaf')
    elif id in ('cabinet','joint','phone','console','vent'):
        w,h=(.75,1.45) if id=='cabinet' else (.50,.65)
        m.box((0,0,h*.5),(w,.32,h),metal)
        m.box((0,-.172,h*.53),(w*.82,.025,h*.75),dark)
        for x in (-.16,.0,.16):m.box((x,-.198,h*.72),(.05,.015,.04),amber)
        for z in (.2,.32,.44):m.box((0,-.20,z),(.18,.04,.065),pale)
    elif id=='clipboard':m.box((0,0,.015),(.25,.34,.025),metal);m.box((0,0,.031),(.23,.31,.009),pale)
    elif id=='seat':
        m.box((0,0,.27),(.48,.44,.50),dark);m.box((0,0,.56),(.59,.55,.13),green)
        m.box((0,.23,.98),(.59,.12,.78),green);m.box((0,.15,1.29),(.38,.08,.17),pale)
        for x in (-.32,.32):m.box((x,0,.74),(.055,.47,.055),metal)
    elif id=='wall_module':
        m.box((0,0,1.5),(2.1,.15,3),pale);m.box((0,-.086,1.83),(1.83,.025,1.1),metal)
        m.box((0,-.104,1.84),(1.64,.017,.9),dark);m.box((0,-.28,2.73),(1.95,.52,.07),metal)
    elif id=='floor_module':m.box((0,0,-.06),(2.1,5.2,.12),metal)
    elif id=='key':m.ellipsoid((0,0,.07),(.035,.007,.035),metal,rings=5);m.box((0,0,.02),(.014,.014,.09),metal)
    else:raise ValueError(id)
    return m.object(id)

def camera_and_lights(target=(0,0,.92),distance=4.4):
    scene=bpy.context.scene;scene.render.engine='CYCLES';scene.cycles.samples=24
    scene.world.use_nodes=True
    scene.world.node_tree.nodes['Background'].inputs['Color'].default_value=(.012,.025,.035,1)
    scene.world.node_tree.nodes['Background'].inputs['Strength'].default_value=.35
    bpy.ops.object.camera_add(location=(distance*.58,-distance,distance*.56))
    camera=bpy.context.object;camera.rotation_euler=(Vector(target)-camera.location).to_track_quat('-Z','Y').to_euler();camera.data.type='ORTHO';camera.data.ortho_scale=2.25;scene.camera=camera
    for loc,power,size in [((2,-3,4),180,4),((-3,-1,2),90,3),((0,3,4),160,3)]:
        bpy.ops.object.light_add(type='AREA',location=loc);light=bpy.context.object;light.data.energy=power;light.data.shape='DISK';light.data.size=size
        light.rotation_euler=(Vector((0,0,1))-light.location).to_track_quat('-Z','Y').to_euler()
    scene.render.resolution_x=600;scene.render.resolution_y=700;scene.render.resolution_percentage=100
    scene.render.image_settings.file_format='PNG';scene.render.film_transparent=False
    scene.view_settings.view_transform='AgX'

def main():
    manifest={'source':'Original Blender assets from tools/build_art.py','blender':bpy.app.version_string,'characters':[],'props':[],'clips':[],'bones':[b[0] for b in BONES]}
    for id in PROFILES:
        reset();r,body=character(id)
        source=SOURCE/(id+'.blend');bpy.ops.wm.save_as_mainfile(filepath=str(source))
        path=EXPORT/'Characters'/(id+'.fbx');export_fbx(path,[r,body])
        manifest['characters'].append({'id':id,'file':str(path.relative_to(ROOT)),'vertices':len(body.data.vertices),'triangles':sum(len(p.vertices)-2 for p in body.data.polygons),'blendshapes':[k.name for k in body.data.shape_keys.key_blocks]})
        camera_and_lights(target=(0,0,.91*PROFILES[id][3]))
        bpy.context.scene.render.filepath=str(EVIDENCE/(id+'.png'));bpy.ops.render.render(write_still=True)
    reset();r,body=character('player');manifest['clips']=animations(r)
    bpy.context.scene.render.fps=30;bpy.context.scene.frame_start=0;bpy.context.scene.frame_end=72
    bpy.ops.wm.save_as_mainfile(filepath=str(SOURCE/'motion.blend'))
    export_fbx(EXPORT/'Motion'/'rescue_motion.fbx',[r,body],True)
    for id in ('backup','medical','tools','spares','meter','radio_handset','lamp','driver','cup','stretcher','cart','door','cabinet','joint','phone','console','vent','clipboard','seat','wall_module','floor_module','key'):
        reset();ob=prop(id);bpy.ops.wm.save_as_mainfile(filepath=str(SOURCE/(id+'.blend')))
        path=EXPORT/'Props'/(id+'.fbx');export_fbx(path,[ob]);manifest['props'].append({'id':id,'file':str(path.relative_to(ROOT))})
    manifest['sha256']={str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(EXPORT.rglob('*.fbx'))}
    (EXPORT/'manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2)+'\n')
    (SOURCE/'palette.json').write_text(json.dumps(COLORS,indent=2)+'\n')
    print('LAST_LIGHT_ART_DONE',len(manifest['characters']),len(manifest['props']),len(manifest['clips']))

if __name__=='__main__':main()
