#if UNITY_EDITOR
using System;
using System.IO;
using System.Linq;
using UnityEditor;
using UnityEngine;

namespace LastLight.Editor
{
    public static class ArtImporter
    {
        const string Root="Assets/LastLight/Art";
        const string Generated="Assets/LastLight/Generated/Art";
        [Serializable] sealed class ModelData {public string id,file;}
        [Serializable] sealed class MotionData {public string id;public float duration,contact,release;public bool loop;}
        [Serializable] sealed class Manifest {public ModelData[] characters,props;public MotionData[] clips;public string[] bones;}
        [MenuItem("Last Light/Import art")]
        public static void Import()
        {
            if(!File.Exists(Root+"/manifest.json"))throw new Exception("Art manifest missing: run Blender tools/build_art.py first.");
            var manifest=JsonUtility.FromJson<Manifest>(File.ReadAllText(Root+"/manifest.json"));
            Directory.CreateDirectory(Generated);Directory.CreateDirectory("Assets/LastLight/Resources/Presentation");AssetDatabase.Refresh();
            foreach(var model in manifest.characters.Concat(manifest.props))ConfigureModel(model.file,manifest.characters.Contains(model));
            ConfigureModel(Root+"/Motion/rescue_motion.fbx",true);
            var path="Assets/LastLight/Resources/Presentation/Assets.asset";
            var catalog=AssetDatabase.LoadAssetAtPath<PresentationAssets>(path);
            if(catalog==null){catalog=ScriptableObject.CreateInstance<PresentationAssets>();AssetDatabase.CreateAsset(catalog,path);}
            catalog.characters=manifest.characters.Select(m=>Prefab(m,true,manifest.bones)).ToArray();
            catalog.props=manifest.props.Select(m=>Prefab(m,false,manifest.bones)).ToArray();
            var clips=AssetDatabase.LoadAllAssetsAtPath(Root+"/Motion/rescue_motion.fbx").OfType<AnimationClip>()
                .Where(c=>!c.name.StartsWith("__preview__")).ToArray();
            catalog.motions=manifest.clips.Select(m=>
            {
                var source=clips.FirstOrDefault(c=>(c.name==m.id||c.name.EndsWith("|"+m.id)||c.name.EndsWith("_"+m.id)) && AnimationUtility.GetCurveBindings(c).Any(b=>b.type==typeof(Transform)));
                if(source==null)throw new Exception("FBX is missing clip "+m.id+"; found "+string.Join(",",clips.Select(c=>c.name)));
                string cp=Generated+"/"+m.id+".anim";
                var target=AssetDatabase.LoadAssetAtPath<AnimationClip>(cp);
                if(target==null){target=new AnimationClip();AssetDatabase.CreateAsset(target,cp);}
                EditorUtility.CopySerialized(source,target);target.name=m.id;target.legacy=false;
                target.wrapMode=m.loop?WrapMode.Loop:WrapMode.ClampForever;EditorUtility.SetDirty(target);
                return new PresentationAssets.Motion{id=m.id,clip=target,duration=m.duration,loop=m.loop,contact=m.contact,release=m.release};
            }).ToArray();
            var actionText=Resources.Load<TextAsset>("Presentation/Actions");
            if(actionText==null)throw new Exception("Action presentation catalog missing");
            var actions=JsonUtility.FromJson<ActionCatalog>(actionText.text);
            if(actions.actions.Length!=51)throw new Exception("Action catalog must cover 51 actions");
            foreach(var action in actions.actions)
            {
                foreach(string id in new[]{action.preparation_clip,action.result_clip,action.failed_clip})catalog.Clip(id);
                foreach(string socket in action.socket_ids)if(!PresentationSockets.All.Any(s=>s.id==socket))throw new Exception("Missing socket "+socket);
            }
            EditorUtility.SetDirty(catalog);AssetDatabase.SaveAssets();
            Debug.Log("[LAST_LIGHT_ART_IMPORTED] "+catalog.characters.Length+" actors, "+catalog.props.Length+" props, "+catalog.motions.Length+" clips");
        }
        [Serializable] sealed class ActionCatalog {public ActionPresentationView[] actions;}
        static void ConfigureModel(string path,bool character)
        {
            if(!File.Exists(path))throw new FileNotFoundException("Required exported art missing",path);
            var importer=AssetImporter.GetAtPath(path) as ModelImporter;
            if(importer==null)throw new Exception("FBX importer missing: "+path);
            importer.animationType=character?ModelImporterAnimationType.Generic:ModelImporterAnimationType.None;
            importer.importAnimation=path.Contains("/Motion/");importer.importBlendShapes=character;
            importer.optimizeGameObjects=false;importer.isReadable=true;importer.globalScale=1;
            importer.materialImportMode=ModelImporterMaterialImportMode.ImportStandard;
            importer.SaveAndReimport();
        }
        static PresentationAssets.Model Prefab(ModelData data,bool character,string[] requiredBones)
        {
            var source=AssetDatabase.LoadAssetAtPath<GameObject>(data.file);
            if(source==null)throw new Exception("Failed to import "+data.file);
            var go=UnityEngine.Object.Instantiate(source);go.name=data.id;
            try
            {
                foreach(var animator in go.GetComponentsInChildren<Animator>()){animator.applyRootMotion=false;animator.enabled=false;}
                foreach(var renderer in go.GetComponentsInChildren<Renderer>())
                {
                    renderer.sharedMaterials=renderer.sharedMaterials.Select(m=>Material(m)).ToArray();
                    if(renderer is SkinnedMeshRenderer skin)skin.updateWhenOffscreen=true;
                }
                PresentationSockets.Attach(go,character?"actor":data.id);
                if(character)
                {
                    var names=go.GetComponentsInChildren<Transform>().Select(t=>t.name).ToArray();
                    foreach(string bone in requiredBones)if(!names.Contains(bone))throw new Exception(data.id+" missing bone "+bone);
                    var mesh=go.GetComponentInChildren<SkinnedMeshRenderer>()?.sharedMesh;
                    if(mesh==null)throw new Exception(data.id+" is not a skinned model");
                    foreach(string face in new[]{"neutral","happy","sad","angry","surprised","relieved_smile","concerned","stern","suspicious","blink"})
                        if(mesh.GetBlendShapeIndex(face)<0)throw new Exception(data.id+" missing blendshape "+face);
                }
                var prefab=PrefabUtility.SaveAsPrefabAsset(go,Generated+"/"+(character?"Actor_":"Prop_")+data.id+".prefab");
                return new PresentationAssets.Model{id=data.id,prefab=prefab};
            }
            finally{UnityEngine.Object.DestroyImmediate(go);}
        }
        static Material Material(Material source)
        {
            if(source==null)throw new Exception("Unassigned imported material");
            string name=source.name.Replace('/','_');string path=Generated+"/"+name+".mat";
            var target=AssetDatabase.LoadAssetAtPath<Material>(path);
            var color=source.HasProperty("_BaseColor")?source.GetColor("_BaseColor"):source.color;
            if(target==null){target=new Material(Shader.Find("Universal Render Pipeline/Lit"));AssetDatabase.CreateAsset(target,path);}
            target.SetColor("_BaseColor",color);target.color=color;target.SetFloat("_Smoothness",.18f);EditorUtility.SetDirty(target);return target;
        }
    }
}
#endif
