#if UNITY_EDITOR
using System;
using System.IO;
using UnityEditor;
using UnityEditor.Build.Reporting;
using UnityEditor.SceneManagement;
using UnityEngine;
using UnityEngine.Rendering;
using UnityEngine.Rendering.Universal;

namespace LastLight.Editor
{
    public static class BuildTools
    {
        const string Root="Assets/LastLight/Generated";
        [InitializeOnLoadMethod]
        static void ConfigureOnImport()
        {
            EditorApplication.delayCall += () =>
            {
                if (EditorApplication.isCompiling || EditorApplication.isPlayingOrWillChangePlaymode) return;
                if (!File.Exists(Root+"/LastLightPipeline.asset")||
                    !File.Exists("Assets/LastLight/Resources/RuntimeMaterials/TextMeshPro_Mobile_Distance_Field.mat")) Configure();
            };
        }

        [MenuItem("Last Light/Configure project")]
        public static void Configure()
        {
            EnsureTmpResources();
            Directory.CreateDirectory(Root);
            AssetDatabase.Refresh();
            var renderer=AssetDatabase.LoadAssetAtPath<UniversalRendererData>(Root+"/LastLightRenderer.asset");
            if(renderer==null)
            {
                renderer=ScriptableObject.CreateInstance<UniversalRendererData>();
                AssetDatabase.CreateAsset(renderer,Root+"/LastLightRenderer.asset");
            }
            var pipeline=AssetDatabase.LoadAssetAtPath<UniversalRenderPipelineAsset>(Root+"/LastLightPipeline.asset");
            if(pipeline==null)
            {
                pipeline=ScriptableObject.CreateInstance<UniversalRenderPipelineAsset>();
                AssetDatabase.CreateAsset(pipeline,Root+"/LastLightPipeline.asset");
                var serialized=new SerializedObject(pipeline);
                var list=serialized.FindProperty("m_RendererDataList");
                list.arraySize=1;list.GetArrayElementAtIndex(0).objectReferenceValue=renderer;
                serialized.FindProperty("m_DefaultRendererIndex").intValue=0;
                serialized.ApplyModifiedPropertiesWithoutUndo();
            }
            GraphicsSettings.defaultRenderPipeline=pipeline;
            QualitySettings.renderPipeline=pipeline;
            QualitySettings.vSyncCount=1;
            QualitySettings.shadowDistance=30;
            PlayerSettings.companyName="LastLight";
            PlayerSettings.productName="余灯 · Last Light";
            PlayerSettings.bundleVersion="1.0.0";
            PlayerSettings.defaultScreenWidth=1920;
            PlayerSettings.defaultScreenHeight=1080;
            PlayerSettings.fullScreenMode=FullScreenMode.FullScreenWindow;
            PlayerSettings.resizableWindow=true;
            PlayerSettings.runInBackground=true;
            PlayerSettings.colorSpace=ColorSpace.Linear;
            // Single supported input path; no legacy StandaloneInputModule is used.
            var settings=new SerializedObject(AssetDatabase.LoadAllAssetsAtPath("ProjectSettings/ProjectSettings.asset")[0]);
            var input=settings.FindProperty("activeInputHandler");
            if(input!=null){input.intValue=1;settings.ApplyModifiedPropertiesWithoutUndo();}
            EditorBuildSettings.scenes=new[]{new EditorBuildSettingsScene("Assets/Scenes/LastLight.unity",true)};
            PreserveRuntimeShaders();
            if(!File.Exists("Assets/LastLight/Resources/Presentation/Assets.asset")) ArtImporter.Import();
            AssetDatabase.SaveAssets();
            Debug.Log("[LAST_LIGHT_CONFIGURED] Unity="+Application.unityVersion+" URP / New Input System / Chinese font");
        }

        static void EnsureTmpResources()
        {
            if(Resources.Load<TMPro.TMP_Settings>("TMP Settings")!=null)return;
            var package=UnityEditor.PackageManager.PackageInfo.FindForAssembly(typeof(TMPro.TMP_Text).Assembly);
            if(package==null)return;
            string path=Path.Combine(package.resolvedPath,"Package Resources","TMP Essential Resources.unitypackage");
            if(File.Exists(path))
            {
                AssetDatabase.ImportPackage(path,false);
                AssetDatabase.Refresh();
            }
        }

        static readonly string[] RuntimeShaders={
            "Universal Render Pipeline/Lit","Universal Render Pipeline/Particles/Unlit",
            "TextMeshPro/Distance Field","TextMeshPro/Mobile/Distance Field","UI/Default"
        };

        static void PreserveRuntimeShaders()
        {
            // These materials are created at runtime, so scene dependency scanning cannot see them.
            // Keep both direct Resources references and required shader variants in player builds.
            const string materialRoot="Assets/LastLight/Resources/RuntimeMaterials";
            Directory.CreateDirectory(materialRoot);AssetDatabase.Refresh();
            var assets=AssetDatabase.LoadAllAssetsAtPath("ProjectSettings/GraphicsSettings.asset");
            if(assets.Length==0)throw new Exception("GraphicsSettings asset is unavailable.");
            var graphics=new SerializedObject(assets[0]);
            var included=graphics.FindProperty("m_AlwaysIncludedShaders");
            if(included==null)throw new Exception("Cannot locate the always-included shader list.");
            foreach(string shaderName in RuntimeShaders)
            {
                var shader=Shader.Find(shaderName);
                if(shader==null)throw new Exception("Required runtime shader missing: "+shaderName);
                bool present=false;
                for(int i=0;i<included.arraySize;i++)
                    if(included.GetArrayElementAtIndex(i).objectReferenceValue==shader){present=true;break;}
                if(!present)
                {
                    int index=included.arraySize;included.InsertArrayElementAtIndex(index);
                    included.GetArrayElementAtIndex(index).objectReferenceValue=shader;
                }
                string file=shaderName.Replace('/','_').Replace(' ','_')+".mat";
                string path=materialRoot+"/"+file;
                if(AssetDatabase.LoadAssetAtPath<Material>(path)==null)
                {
                    var material=new Material(shader){name="LastLight Keep "+shaderName};
                    if(shaderName=="Universal Render Pipeline/Lit")material.EnableKeyword("_EMISSION");
                    AssetDatabase.CreateAsset(material,path);
                }
            }
            graphics.ApplyModifiedPropertiesWithoutUndo();
        }

        [MenuItem("Last Light/Open game")]
        public static void OpenGame(){Configure();EditorSceneManager.OpenScene("Assets/Scenes/LastLight.unity");}

        [MenuItem("Last Light/Build Windows")]
        public static void BuildWindows()
        {
            Configure();
            Directory.CreateDirectory("Builds/Windows");
            var options=new BuildPlayerOptions
            {
                scenes=new[]{"Assets/Scenes/LastLight.unity"},
                locationPathName="Builds/Windows/LastLight.exe",
                target=BuildTarget.StandaloneWindows64,
                options=BuildOptions.Development
            };
            var report=BuildPipeline.BuildPlayer(options);
            Directory.CreateDirectory("artifacts");
            File.WriteAllText("artifacts/unity-build-result.json",JsonUtility.ToJson(new BuildResult
            { unity=Application.unityVersion,result=report.summary.result.ToString(),errors=(int)report.summary.totalErrors,
              warnings=(int)report.summary.totalWarnings,bytes=(long)report.summary.totalSize },true));
            if(report.summary.result!=UnityEditor.Build.Reporting.BuildResult.Succeeded)
                throw new Exception("Windows build failed; see artifacts/unity-build.log");
            Debug.Log("[LAST_LIGHT_WINDOWS_BUILD_OK]");
        }

        [MenuItem("Last Light/Validate assets")]
        public static void ValidateAssets()
        {
            Configure();
            ArtImporter.Import();
            string[] required={"Fonts/Chinese","Audio/ambient","Audio/door","Audio/brake","Audio/music"};
            foreach(string path in required)
                if(Resources.Load(path)==null)throw new Exception("Missing resource: "+path);
            foreach(string shader in RuntimeShaders)
                if(Shader.Find(shader)==null)throw new Exception("Runtime shader unavailable: "+shader);
            Debug.Log("[LAST_LIGHT_ASSET_VALIDATION_OK]");
        }

        [Serializable] sealed class BuildResult
        {public string unity,result;public int errors,warnings;public long bytes;}
    }
}
#endif
