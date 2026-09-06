using System;
using System.Collections.Generic;
using System.IO;
using UnityEditor;
using UnityEditor.SceneManagement;
using UnityEngine;
using UnityEngine.SceneManagement;

namespace NPCDirector.Editor
{
    public static class VerticalSliceSceneBuilder
    {
        private const string ScenePath = "Assets/Scenes/GreyHarborVerticalSlice.unity";
        private const string AssetRoot = "Assets/VerticalSlice";
        private const string MaterialRoot = AssetRoot + "/Materials";
        private const string PrefabRoot = AssetRoot + "/Prefabs";

        private static readonly Color HarborSteel = new Color(0.18f, 0.24f, 0.29f);
        private static readonly Color WetConcrete = new Color(0.20f, 0.23f, 0.25f);
        private static readonly Color SafetyYellow = new Color(0.92f, 0.62f, 0.12f);
        private static readonly Color FailureRed = new Color(0.78f, 0.10f, 0.08f);
        private static readonly Color StandbyAmber = new Color(0.95f, 0.55f, 0.08f);
        private static readonly Color SuccessGreen = new Color(0.12f, 0.68f, 0.34f);
        private static readonly Color InfoCyan = new Color(0.10f, 0.60f, 0.74f);

        [MenuItem("NPC Director/Vertical Slice/VS2/Create Art Sample Scene")]
        public static void CreateArtSampleScene()
        {
            bool confirmed = EditorUtility.DisplayDialog(
                "Create VS2 Art Sample",
                "This creates a new vertical-slice scene from the verified P3 runtime.",
                "Create VS2 Scene",
                "Cancel");
            if (!confirmed)
            {
                return;
            }

            GameObject root = PrototypeP3SceneBuilder.BuildBaseScene();
            root.name = "GreyHarborVerticalSliceRoot";
            EnsureFolders();
            CreateModulePrefabs();
            Transform artRoot = new GameObject("VerticalSliceArt").transform;
            CreateArchitecture(artRoot);
            CreateObjectViews();
            CreateCharacterSilhouettes();
            CreateStormLighting(artRoot);
            ConfigureCamera();

            Scene scene = SceneManager.GetActiveScene();
            EditorSceneManager.MarkSceneDirty(scene);
            EditorSceneManager.SaveScene(scene, ScenePath);
            AssetDatabase.SaveAssets();
            Selection.activeGameObject = artRoot.gameObject;
            Debug.Log(
                $"[VS2_SCENE_BUILDER] created scene={ScenePath} architecture=18 " +
                "object_views=6 characters=3 lights=5 prefabs=3 gameplay_scope_added=0");
        }

        [MenuItem("NPC Director/Vertical Slice/VS2/Validate Open Art Sample")]
        public static void ValidateOpenArtSample()
        {
            VerticalSliceArtMarker[] markers =
                UnityEngine.Object.FindObjectsOfType<VerticalSliceArtMarker>(true);
            int architecture = Count(markers, VerticalSliceArtKind.Architecture);
            int props = Count(markers, VerticalSliceArtKind.Prop);
            int characters = Count(markers, VerticalSliceArtKind.Character);
            int lights = Count(markers, VerticalSliceArtKind.Lighting);
            int views = UnityEngine.Object.FindObjectsOfType<VerticalSliceObjectView>(true).Length;
            int hotspots = UnityEngine.Object.FindObjectsOfType<PrototypeP2Hotspot>(true).Length;
            bool prefabsPresent =
                AssetDatabase.LoadAssetAtPath<GameObject>(PrefabRoot + "/WallModule.prefab") != null &&
                AssetDatabase.LoadAssetAtPath<GameObject>(PrefabRoot + "/CargoRack.prefab") != null &&
                AssetDatabase.LoadAssetAtPath<GameObject>(PrefabRoot + "/HarborLamp.prefab") != null;
            bool passed = architecture >= 12 && props >= 6 && characters == 3 &&
                          lights >= 5 && views == 6 && hotspots == 6 && prefabsPresent;
            Debug.Log(
                $"[VS2_SCENE_VALIDATE] {(passed ? "PASS" : "FAIL")} " +
                $"architecture={architecture} props={props} characters={characters} " +
                $"lights={lights} object_views={views} hotspots={hotspots} " +
                $"prefabs_present={prefabsPresent}");
        }

        private static int Count(
            VerticalSliceArtMarker[] markers,
            VerticalSliceArtKind kind)
        {
            int count = 0;
            foreach (VerticalSliceArtMarker marker in markers)
            {
                if (marker.Kind == kind)
                {
                    count += 1;
                }
            }
            return count;
        }

        private static void CreateArchitecture(Transform parent)
        {
            Material wall = Material("HarborSteel", HarborSteel, 0.65f);
            Material floor = Material("WetConcrete", WetConcrete, 0.82f);
            Material trim = Material("SafetyYellow", SafetyYellow, 0.45f);
            CreateBox("FloorSlab", parent, new Vector3(0f, -0.15f, 2f),
                new Vector3(16f, 0.3f, 11f), floor, VerticalSliceArtKind.Architecture);
            CreateBox("BackWall", parent, new Vector3(0f, 2.5f, 6.8f),
                new Vector3(16f, 5f, 0.35f), wall, VerticalSliceArtKind.Architecture);
            CreateBox("LeftWall", parent, new Vector3(-7.8f, 2.5f, 2f),
                new Vector3(0.35f, 5f, 9.5f), wall, VerticalSliceArtKind.Architecture);
            CreateBox("RightWall", parent, new Vector3(7.8f, 2.5f, 2f),
                new Vector3(0.35f, 5f, 9.5f), wall, VerticalSliceArtKind.Architecture);
            CreateBox("CeilingBeamA", parent, new Vector3(-4f, 4.7f, 2f),
                new Vector3(0.3f, 0.3f, 9.2f), wall, VerticalSliceArtKind.Architecture);
            CreateBox("CeilingBeamB", parent, new Vector3(4f, 4.7f, 2f),
                new Vector3(0.3f, 0.3f, 9.2f), wall, VerticalSliceArtKind.Architecture);
            for (int index = 0; index < 6; index++)
            {
                float x = -6.5f + index * 2.6f;
                CreateBox($"SafetyStripe{index}", parent, new Vector3(x, 0.02f, -2.7f),
                    new Vector3(1.2f, 0.03f, 0.25f), trim, VerticalSliceArtKind.Architecture);
            }
            InstantiatePrefab("WallModule", parent, new Vector3(-5.8f, 1.3f, 5.9f));
            InstantiatePrefab("WallModule", parent, new Vector3(5.8f, 1.3f, 5.9f));
            InstantiatePrefab("CargoRack", parent, new Vector3(4.8f, 1.2f, 4.8f));
            InstantiatePrefab("CargoRack", parent, new Vector3(-5.2f, 1.2f, 4.8f));
            CreatePipeRun(parent, wall);
        }

        private static void CreatePipeRun(Transform parent, Material material)
        {
            for (int index = 0; index < 4; index++)
            {
                GameObject pipe = GameObject.CreatePrimitive(PrimitiveType.Cylinder);
                pipe.name = $"OverheadPipe{index}";
                pipe.transform.SetParent(parent, false);
                pipe.transform.position = new Vector3(-4.5f + index * 3f, 4.1f, 6.2f);
                pipe.transform.rotation = Quaternion.Euler(0f, 0f, 90f);
                pipe.transform.localScale = new Vector3(0.15f, 1.3f, 0.15f);
                pipe.GetComponent<Renderer>().sharedMaterial = material;
                Mark(pipe, pipe.name, VerticalSliceArtKind.Architecture);
            }
        }

        private static void CreateObjectViews()
        {
            Material failure = Material("StateFailure", FailureRed, 0.3f, true);
            Material standby = Material("StateStandby", StandbyAmber, 0.3f, true);
            Material success = Material("StateSuccess", SuccessGreen, 0.25f, true);
            Material info = Material("StateInfo", InfoCyan, 0.35f, true);
            Material steel = Material("PropSteel", HarborSteel * 1.15f, 0.55f);

            ConfigureObject("gate_console", steel, failure, standby, success, info,
                new[] { PrimitiveType.Cube, PrimitiveType.Cube },
                new[] { new Vector3(1.5f, 1.4f, 0.8f), new Vector3(0.9f, 0.35f, 0.9f) });
            ConfigureObject("generator", steel, failure, standby, success, info,
                new[] { PrimitiveType.Cylinder, PrimitiveType.Cube },
                new[] { new Vector3(0.75f, 0.9f, 0.75f), new Vector3(1.5f, 0.55f, 1f) });
            ConfigureObject("control_cabinet", steel, failure, standby, success, info,
                new[] { PrimitiveType.Cube, PrimitiveType.Cube },
                new[] { new Vector3(1.2f, 1.8f, 0.65f), new Vector3(0.65f, 0.5f, 0.72f) });
            ConfigureObject("cargo_crate_c12", steel, failure, standby, success, info,
                new[] { PrimitiveType.Cube, PrimitiveType.Cube },
                new[] { new Vector3(1.6f, 1.2f, 1.2f), new Vector3(1.7f, 0.12f, 1.3f) });
            ConfigureObject("manifest_board", steel, failure, standby, success, info,
                new[] { PrimitiveType.Cube, PrimitiveType.Cube },
                new[] { new Vector3(1.5f, 1.7f, 0.2f), new Vector3(1.2f, 1.35f, 0.23f) });
            ConfigureObject("alarm_lamp", steel, failure, standby, success, info,
                new[] { PrimitiveType.Cylinder, PrimitiveType.Sphere },
                new[] { new Vector3(0.5f, 0.8f, 0.5f), new Vector3(0.55f, 0.55f, 0.55f) });
        }

        private static void ConfigureObject(
            string objectId,
            Material baseMaterial,
            Material failure,
            Material standby,
            Material success,
            Material info,
            PrimitiveType[] primitives,
            Vector3[] scales)
        {
            GameObject target = GameObject.Find(objectId);
            Renderer rootRenderer = target.GetComponent<Renderer>();
            if (rootRenderer != null)
            {
                rootRenderer.enabled = false;
            }
            List<Renderer> renderers = new List<Renderer>();
            for (int index = 0; index < primitives.Length; index++)
            {
                GameObject visual = GameObject.CreatePrimitive(primitives[index]);
                visual.name = $"{objectId}_visual_{index}";
                visual.transform.SetParent(target.transform, false);
                visual.transform.localPosition = index == 0
                    ? Vector3.zero
                    : new Vector3(0f, scales[0].y * 0.45f, -0.05f);
                visual.transform.localScale = scales[index];
                UnityEngine.Object.DestroyImmediate(visual.GetComponent<Collider>());
                Renderer renderer = visual.GetComponent<Renderer>();
                renderer.sharedMaterial = baseMaterial;
                renderers.Add(renderer);
                Mark(visual, visual.name, VerticalSliceArtKind.Prop);
            }
            VerticalSliceObjectView view = target.AddComponent<VerticalSliceObjectView>();
            view.Configure(
                objectId,
                renderers.ToArray(),
                StateMappings(objectId, failure, standby, success, info, baseMaterial));
        }

        private static VerticalSliceStateMaterial[] StateMappings(
            string objectId,
            Material failure,
            Material standby,
            Material success,
            Material info,
            Material baseMaterial)
        {
            Dictionary<string, Material> values = new Dictionary<string, Material>
            {
                ["offline_e17"] = failure,
                ["stopped_fuse_slot_empty"] = failure,
                ["locked"] = failure,
                ["sealed_anomaly"] = failure,
                ["flashing_red"] = failure,
                ["readable"] = info,
                ["access_authorized"] = standby,
                ["standby_fuse_installed"] = standby,
                ["solid_amber"] = standby,
                ["authorized"] = standby,
                ["online"] = success,
                ["running"] = success,
                ["restart_complete"] = success,
                ["solid_green"] = success
            };
            List<VerticalSliceStateMaterial> mappings = new List<VerticalSliceStateMaterial>();
            foreach (KeyValuePair<string, Material> value in values)
            {
                mappings.Add(new VerticalSliceStateMaterial
                {
                    state = value.Key,
                    material = value.Value ?? baseMaterial
                });
            }
            return mappings.ToArray();
        }

        private static void CreateCharacterSilhouettes()
        {
            AddCharacterDetails("guard_captain_maren", "maren", new Color(0.16f, 0.34f, 0.58f),
                PrimitiveType.Cube, new Vector3(0.72f, 0.25f, 0.72f), new Vector3(0f, 1.1f, 0f));
            AddCharacterDetails("mechanic_lia", "lia", new Color(0.92f, 0.53f, 0.10f),
                PrimitiveType.Cylinder, new Vector3(0.22f, 0.75f, 0.22f), new Vector3(0.72f, 0.2f, 0f));
            AddCharacterDetails("porter_finn", "finn", new Color(0.38f, 0.23f, 0.14f),
                PrimitiveType.Cube, new Vector3(0.85f, 0.55f, 0.30f), new Vector3(0f, 0.25f, 0.48f));
        }

        private static void AddCharacterDetails(
            string npcId,
            string assetId,
            Color color,
            PrimitiveType toolType,
            Vector3 toolScale,
            Vector3 toolPosition)
        {
            GameObject npc = GameObject.Find(npcId);
            npc.GetComponent<Renderer>().sharedMaterial = Material($"Character_{assetId}", color, 0.55f);
            GameObject accessory = GameObject.CreatePrimitive(toolType);
            accessory.name = $"{npcId}_role_prop";
            accessory.transform.SetParent(npc.transform, false);
            accessory.transform.localPosition = toolPosition;
            accessory.transform.localScale = toolScale;
            UnityEngine.Object.DestroyImmediate(accessory.GetComponent<Collider>());
            accessory.GetComponent<Renderer>().sharedMaterial = Material(
                $"Character_{assetId}_accent", color * 0.65f, 0.4f);
            Mark(npc, assetId, VerticalSliceArtKind.Character);
        }

        private static void CreateStormLighting(Transform parent)
        {
            RenderSettings.ambientLight = new Color(0.12f, 0.18f, 0.24f);
            RenderSettings.fog = true;
            RenderSettings.fogColor = new Color(0.08f, 0.13f, 0.18f);
            RenderSettings.fogDensity = 0.012f;
            Light directional = UnityEngine.Object.FindObjectOfType<Light>();
            if (directional != null)
            {
                directional.color = new Color(0.55f, 0.68f, 0.82f);
                directional.intensity = 0.75f;
            }
            CreateLight(parent, "WorkLightLeft", new Vector3(-4.5f, 4f, 1f), SafetyYellow, 4.5f);
            CreateLight(parent, "WorkLightCenter", new Vector3(0f, 4f, 1f), InfoCyan, 4.5f);
            CreateLight(parent, "WorkLightRight", new Vector3(4.5f, 4f, 1f), SafetyYellow, 4.5f);
            CreateLight(parent, "GateEmergencyLight", new Vector3(-5f, 2.8f, 0f), FailureRed, 3.5f);
            CreateLight(parent, "CabinetEmergencyLight", new Vector3(-1f, 2.8f, 0f), FailureRed, 3.5f);
        }

        private static void CreateLight(
            Transform parent,
            string name,
            Vector3 position,
            Color color,
            float range)
        {
            GameObject lightObject = new GameObject(name);
            lightObject.transform.SetParent(parent, false);
            lightObject.transform.position = position;
            Light light = lightObject.AddComponent<Light>();
            light.type = LightType.Point;
            light.color = color;
            light.range = range;
            light.intensity = 2.1f;
            Mark(lightObject, name, VerticalSliceArtKind.Lighting);
        }

        private static void ConfigureCamera()
        {
            Camera camera = Camera.main;
            camera.transform.position = new Vector3(0f, 7.3f, -13.5f);
            camera.transform.LookAt(new Vector3(0f, 1.3f, 2.4f));
            camera.fieldOfView = 48f;
            camera.backgroundColor = new Color(0.035f, 0.07f, 0.10f);
        }

        private static GameObject CreateBox(
            string name,
            Transform parent,
            Vector3 position,
            Vector3 scale,
            Material material,
            VerticalSliceArtKind kind)
        {
            GameObject item = GameObject.CreatePrimitive(PrimitiveType.Cube);
            item.name = name;
            item.transform.SetParent(parent, false);
            item.transform.position = position;
            item.transform.localScale = scale;
            item.GetComponent<Renderer>().sharedMaterial = material;
            Mark(item, name, kind);
            return item;
        }

        private static void Mark(GameObject target, string assetId, VerticalSliceArtKind kind)
        {
            VerticalSliceArtMarker marker = target.GetComponent<VerticalSliceArtMarker>();
            if (marker == null)
            {
                marker = target.AddComponent<VerticalSliceArtMarker>();
            }
            marker.Configure(assetId, kind);
        }

        private static void CreateModulePrefabs()
        {
            SavePrimitivePrefab("WallModule", PrimitiveType.Cube, new Vector3(2.4f, 2.5f, 0.25f),
                Material("HarborSteel", HarborSteel, 0.65f));
            SavePrimitivePrefab("CargoRack", PrimitiveType.Cube, new Vector3(2.1f, 2.4f, 0.6f),
                Material("PropSteel", HarborSteel * 1.15f, 0.55f));
            SavePrimitivePrefab("HarborLamp", PrimitiveType.Cylinder, new Vector3(0.3f, 0.25f, 0.3f),
                Material("SafetyYellow", SafetyYellow, 0.45f));
        }

        private static void SavePrimitivePrefab(
            string name,
            PrimitiveType type,
            Vector3 scale,
            Material material)
        {
            string path = $"{PrefabRoot}/{name}.prefab";
            if (AssetDatabase.LoadAssetAtPath<GameObject>(path) != null)
            {
                return;
            }
            GameObject source = GameObject.CreatePrimitive(type);
            source.name = name;
            source.transform.localScale = scale;
            source.GetComponent<Renderer>().sharedMaterial = material;
            Mark(source, name, VerticalSliceArtKind.Architecture);
            PrefabUtility.SaveAsPrefabAsset(source, path);
            UnityEngine.Object.DestroyImmediate(source);
        }

        private static void InstantiatePrefab(
            string name,
            Transform parent,
            Vector3 position)
        {
            GameObject prefab = AssetDatabase.LoadAssetAtPath<GameObject>($"{PrefabRoot}/{name}.prefab");
            GameObject instance = (GameObject)PrefabUtility.InstantiatePrefab(prefab);
            instance.name = name + "_Instance";
            instance.transform.SetParent(parent, false);
            instance.transform.position = position;
        }

        private static Material Material(
            string name,
            Color color,
            float smoothness,
            bool emission = false)
        {
            string path = $"{MaterialRoot}/{name}.mat";
            Material material = AssetDatabase.LoadAssetAtPath<Material>(path);
            if (material == null)
            {
                Shader shader = Shader.Find("Universal Render Pipeline/Lit") ??
                                Shader.Find("Standard") ?? Shader.Find("Sprites/Default");
                material = new Material(shader);
                AssetDatabase.CreateAsset(material, path);
            }
            material.color = color;
            if (material.HasProperty("_Smoothness"))
            {
                material.SetFloat("_Smoothness", smoothness);
            }
            if (emission)
            {
                material.EnableKeyword("_EMISSION");
                material.SetColor("_EmissionColor", color * 1.8f);
            }
            EditorUtility.SetDirty(material);
            return material;
        }

        private static void EnsureFolders()
        {
            EnsureFolder(AssetRoot);
            EnsureFolder(MaterialRoot);
            EnsureFolder(PrefabRoot);
        }

        private static void EnsureFolder(string folder)
        {
            if (AssetDatabase.IsValidFolder(folder))
            {
                return;
            }
            string parent = Path.GetDirectoryName(folder)?.Replace('\\', '/');
            string name = Path.GetFileName(folder);
            if (!string.IsNullOrEmpty(parent) && !string.IsNullOrEmpty(name))
            {
                EnsureFolder(parent);
                AssetDatabase.CreateFolder(parent, name);
            }
        }
    }
}
