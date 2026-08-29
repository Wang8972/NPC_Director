using System.IO;
using UnityEditor;
using UnityEditor.Events;
using UnityEditor.SceneManagement;
using UnityEngine;
using UnityEngine.EventSystems;
using UnityEngine.SceneManagement;
using UnityEngine.UI;

namespace NPCDirector.Editor
{
    public static class PrototypeP2SceneBuilder
    {
        private const string ScenePath = "Assets/Scenes/PrototypeGateRepairP2.unity";
        private const string MaterialFolder = "Assets/NPCDirectorGenerated/P2Materials";
        private const string SessionId = "p2-fake-001";
        private const string Endpoint = "ws://127.0.0.1:8766";

        private sealed class UiRefs
        {
            public Text connection;
            public Text objective;
            public Text selected;
            public Text route;
            public Text feedback;
            public Text clues;
            public Text state;
            public Text subtitle;
        }

        [MenuItem("NPC Director/P2/Create or Reset Fake Director Scene")]
        public static void CreateOrResetScene()
        {
            bool confirmed = EditorUtility.DisplayDialog(
                "Create P2 Fake Director Scene",
                "This replaces the currently open scene. Save unrelated work before continuing.",
                "Create P2 Scene",
                "Cancel");
            if (!confirmed)
            {
                return;
            }

            Scene scene = EditorSceneManager.NewScene(NewSceneSetup.EmptyScene, NewSceneMode.Single);
            CreateCameraAndLighting();

            GameObject root = new GameObject("P2PrototypeRoot");
            PrototypeSceneStateController sceneState =
                root.AddComponent<PrototypeSceneStateController>();
            PrototypeP2GameController controller =
                root.AddComponent<PrototypeP2GameController>();
            NpcRegistry registry = root.AddComponent<NpcRegistry>();
            PrototypeSceneActionExecutor actionExecutor =
                root.AddComponent<PrototypeSceneActionExecutor>();
            PrototypeP2Client client = root.AddComponent<PrototypeP2Client>();

            CreateEnvironment(controller);
            UiRefs ui = CreateUi(controller);
            NpcExecutorBinding[] bindings = CreateNpcs(controller, ui.subtitle);
            registry.Configure(bindings);
            actionExecutor.Configure(SessionId, registry);
            client.Configure(Endpoint, SessionId, registry, actionExecutor, controller);
            controller.Configure(
                client,
                sceneState,
                ui.connection,
                ui.objective,
                ui.selected,
                ui.route,
                ui.feedback,
                ui.clues,
                ui.state);

            EnsureAssetFolder("Assets/Scenes");
            EditorSceneManager.MarkSceneDirty(scene);
            EditorSceneManager.SaveScene(scene, ScenePath);
            AssetDatabase.SaveAssets();
            Selection.activeGameObject = root;
            Debug.Log(
                $"[P2_SCENE_BUILDER] created scene={ScenePath} npcs=3 hotspots=6 " +
                "session_clients=1 scene_action_executors=1");
        }

        [MenuItem("NPC Director/P2/Validate Open Fake Director Scene")]
        public static void ValidateOpenScene()
        {
            int npcCount = Object.FindObjectsOfType<PrototypeP2NpcSelector>(true).Length;
            int hotspotCount = Object.FindObjectsOfType<PrototypeP2Hotspot>(true).Length;
            int clientCount = Object.FindObjectsOfType<PrototypeP2Client>(true).Length;
            int registryCount = Object.FindObjectsOfType<NpcRegistry>(true).Length;
            int actionExecutorCount =
                Object.FindObjectsOfType<PrototypeSceneActionExecutor>(true).Length;
            bool allObjectsPresent = true;
            foreach (string objectId in CanonicalObjectIds())
            {
                allObjectsPresent &= GameObject.Find(objectId) != null;
            }
            bool passed = npcCount == 3 && hotspotCount == 6 && clientCount == 1 &&
                          registryCount == 1 && actionExecutorCount == 1 && allObjectsPresent;
            Debug.Log(
                $"[P2_SCENE_VALIDATE] {(passed ? "PASS" : "FAIL")} " +
                $"npcs={npcCount} hotspots={hotspotCount} clients={clientCount} " +
                $"registries={registryCount} action_executors={actionExecutorCount} " +
                $"objects_present={allObjectsPresent}");
        }

        private static string[] CanonicalObjectIds()
        {
            return new[]
            {
                "gate_console",
                "generator",
                "control_cabinet",
                "cargo_crate_c12",
                "manifest_board",
                "alarm_lamp"
            };
        }

        private static void CreateCameraAndLighting()
        {
            GameObject cameraObject = new GameObject("Main Camera");
            Camera camera = cameraObject.AddComponent<Camera>();
            cameraObject.tag = "MainCamera";
            cameraObject.transform.position = new Vector3(0f, 8.5f, -14f);
            cameraObject.transform.LookAt(new Vector3(0f, 0.8f, 1.5f));
            camera.clearFlags = CameraClearFlags.SolidColor;
            camera.backgroundColor = new Color(0.09f, 0.12f, 0.16f);
            camera.rect = new Rect(0.35f, 0f, 0.65f, 1f);

            GameObject lightObject = new GameObject("Directional Light");
            Light light = lightObject.AddComponent<Light>();
            light.type = LightType.Directional;
            light.intensity = 1.1f;
            lightObject.transform.rotation = Quaternion.Euler(45f, -30f, 0f);

            GameObject floor = GameObject.CreatePrimitive(PrimitiveType.Plane);
            floor.name = "GrayboxFloor";
            floor.transform.localScale = new Vector3(1.6f, 1f, 1.1f);
            floor.GetComponent<Renderer>().sharedMaterial = GetOrCreateMaterial(
                "floor",
                new Color(0.25f, 0.28f, 0.32f));
        }

        private static void CreateEnvironment(PrototypeP2GameController controller)
        {
            CreateHotspot(controller, "gate_console", new Vector3(-5f, 0.7f, 0f),
                new Vector3(1.3f, 1.4f, 0.7f));
            CreateHotspot(controller, "generator", new Vector3(-3f, 0.7f, 0f),
                new Vector3(1.3f, 1.4f, 0.9f));
            CreateHotspot(controller, "control_cabinet", new Vector3(-1f, 0.8f, 0f),
                new Vector3(1.2f, 1.6f, 0.7f));
            CreateHotspot(controller, "cargo_crate_c12", new Vector3(1.2f, 0.65f, 0f),
                new Vector3(1.4f, 1.3f, 1.1f));
            CreateHotspot(controller, "manifest_board", new Vector3(3.4f, 0.8f, 0f),
                new Vector3(1.4f, 1.6f, 0.35f));
            CreateHotspot(controller, "alarm_lamp", new Vector3(5.3f, 0.8f, 0f),
                new Vector3(0.8f, 1.6f, 0.8f));
        }

        private static NpcExecutorBinding[] CreateNpcs(
            PrototypeP2GameController controller,
            Text subtitle)
        {
            return new[]
            {
                CreateNpc(controller, subtitle, "guard_captain_maren", "Maren",
                    new Vector3(-3.5f, 1f, 3.5f), new Color(0.25f, 0.45f, 0.8f)),
                CreateNpc(controller, subtitle, "mechanic_lia", "Lia",
                    new Vector3(0f, 1f, 3.5f), new Color(0.85f, 0.65f, 0.2f)),
                CreateNpc(controller, subtitle, "porter_finn", "Finn",
                    new Vector3(3.5f, 1f, 3.5f), new Color(0.55f, 0.35f, 0.22f))
            };
        }

        private static void CreateHotspot(
            PrototypeP2GameController controller,
            string objectId,
            Vector3 position,
            Vector3 scale)
        {
            GameObject target = GameObject.CreatePrimitive(PrimitiveType.Cube);
            target.name = objectId;
            target.transform.position = position;
            target.transform.localScale = scale;
            target.GetComponent<Renderer>().sharedMaterial = GetOrCreateMaterial(
                $"hotspot_{objectId}",
                new Color(0.75f, 0.2f, 0.2f));
            PrototypeP2Hotspot hotspot = target.AddComponent<PrototypeP2Hotspot>();
            hotspot.Configure(controller, objectId);
            CreateWorldLabel(target.transform, objectId, scale.y * 0.5f + 0.35f);
        }

        private static NpcExecutorBinding CreateNpc(
            PrototypeP2GameController controller,
            Text subtitle,
            string npcId,
            string displayName,
            Vector3 position,
            Color color)
        {
            GameObject npc = GameObject.CreatePrimitive(PrimitiveType.Capsule);
            npc.name = npcId;
            npc.transform.position = position;
            npc.GetComponent<Renderer>().sharedMaterial = GetOrCreateMaterial($"npc_{npcId}", color);
            PrototypeP2NpcSelector selector = npc.AddComponent<PrototypeP2NpcSelector>();
            selector.Configure(controller, npcId);
            ActionCatalog catalog = npc.AddComponent<ActionCatalog>();
            catalog.ConfigureForPrototype();
            FacialPresetController face = npc.AddComponent<FacialPresetController>();
            face.ConfigureForPrototype();
            PerformanceExecutor executor = npc.AddComponent<PerformanceExecutor>();
            executor.Configure(subtitle, catalog, face);
            CreateWorldLabel(npc.transform, displayName, 1.45f);
            return new NpcExecutorBinding { npcId = npcId, executor = executor };
        }

        private static void CreateWorldLabel(Transform parent, string value, float height)
        {
            GameObject labelObject = new GameObject(parent.name + "_label");
            labelObject.transform.position = parent.position + Vector3.up * height;
            labelObject.transform.localScale = Vector3.one * 0.13f;
            TextMesh label = labelObject.AddComponent<TextMesh>();
            label.text = value;
            label.anchor = TextAnchor.MiddleCenter;
            label.alignment = TextAlignment.Center;
            label.fontSize = 40;
            label.color = Color.white;
        }

        private static UiRefs CreateUi(PrototypeP2GameController controller)
        {
            GameObject canvasObject = new GameObject("P2Canvas");
            Canvas canvas = canvasObject.AddComponent<Canvas>();
            canvas.renderMode = RenderMode.ScreenSpaceOverlay;
            CanvasScaler scaler = canvasObject.AddComponent<CanvasScaler>();
            scaler.uiScaleMode = CanvasScaler.ScaleMode.ScaleWithScreenSize;
            scaler.referenceResolution = new Vector2(1920f, 1080f);
            canvasObject.AddComponent<GraphicRaycaster>();

            GameObject eventSystem = new GameObject("EventSystem");
            eventSystem.AddComponent<EventSystem>();
            eventSystem.AddComponent<StandaloneInputModule>();

            GameObject panelObject = new GameObject("P2ControlPanel");
            panelObject.transform.SetParent(canvasObject.transform, false);
            RectTransform panelRect = panelObject.AddComponent<RectTransform>();
            panelRect.anchorMin = new Vector2(0f, 0f);
            panelRect.anchorMax = new Vector2(0f, 1f);
            panelRect.pivot = new Vector2(0f, 0.5f);
            panelRect.sizeDelta = new Vector2(670f, 0f);
            panelObject.AddComponent<Image>().color = new Color(0.04f, 0.06f, 0.09f, 0.94f);

            Font font = LoadBuiltInFont();
            Text title = CreateText(panelObject.transform, font, "P2 Fake Director", 28, -15f, 630f, 40f);
            title.fontStyle = FontStyle.Bold;
            UiRefs refs = new UiRefs
            {
                connection = CreateText(panelObject.transform, font, "连接：未启动", 18, -58f, 630f, 28f),
                objective = CreateText(panelObject.transform, font, "目标：等待快照", 20, -90f, 630f, 34f),
                selected = CreateText(panelObject.transform, font, "当前 NPC：莉娅", 18, -126f, 630f, 32f),
                route = CreateText(panelObject.transform, font, "路线：none", 18, -160f, 630f, 30f),
                feedback = CreateText(panelObject.transform, font, "反馈：等待连接", 18, -195f, 630f, 72f),
                clues = CreateText(panelObject.transform, font, "已发现事实：", 15, -270f, 630f, 180f),
                state = CreateText(panelObject.transform, font, "world_version=-1", 15, -455f, 630f, 88f),
                subtitle = CreateText(panelObject.transform, font, "字幕：", 18, -545f, 630f, 70f)
            };

            float y = -620f;
            CreateButton(panelObject.transform, font, controller, "选择玛伦", "select:guard_captain_maren", 10f, y, 200f);
            CreateButton(panelObject.transform, font, controller, "选择莉娅", "select:mechanic_lia", 225f, y, 200f);
            CreateButton(panelObject.transform, font, controller, "选择费恩", "select:porter_finn", 440f, y, 200f);
            y -= 45f;
            CreateButton(panelObject.transform, font, controller, "莉娅检查发电机", "fixture:inspect_generator", 10f, y, 305f);
            CreateButton(panelObject.transform, font, controller, "莉娅告知玛伦", "fixture:lia_tell_maren_diagnosis", 330f, y, 310f);
            y -= 45f;
            CreateButton(panelObject.transform, font, controller, "转述缺保险丝", "fixture:tell_diagnosis", 10f, y, 305f);
            CreateButton(panelObject.transform, font, controller, "询问保险丝位置", "fixture:ask_fuse_location", 330f, y, 310f);
            y -= 45f;
            CreateButton(panelObject.transform, font, controller, "合作：回应顾虑并请求交付", "fixture:cooperation_offer", 10f, y, 305f);
            CreateButton(panelObject.transform, font, controller, "转述 C-12 记录", "fixture:tell_manifest", 330f, y, 310f);
            y -= 45f;
            CreateButton(panelObject.transform, font, controller, "程序：请求检查授权", "fixture:request_authorization", 10f, y, 305f);
            CreateButton(panelObject.transform, font, controller, "费恩交付保险丝", "fixture:give_fuse", 330f, y, 310f);
            y -= 45f;
            CreateButton(panelObject.transform, font, controller, "莉娅安装保险丝", "fixture:install_fuse", 10f, y, 305f);
            CreateButton(panelObject.transform, font, controller, "玛伦授权控制柜", "fixture:authorize_restart", 330f, y, 310f);
            y -= 45f;
            CreateButton(panelObject.transform, font, controller, "玛伦重启闸门", "fixture:restart_gate", 10f, y, 305f);
            CreateButton(panelObject.transform, font, controller, "拒绝自动圆桌", "fixture:roundtable", 330f, y, 310f);
            y -= 45f;
            CreateButton(panelObject.transform, font, controller, "中断当前场景动作", "interrupt", 10f, y, 305f);
            CreateButton(panelObject.transform, font, controller, "后端权威重置", "reset", 330f, y, 310f);
            return refs;
        }

        private static Text CreateText(
            Transform parent,
            Font font,
            string value,
            int fontSize,
            float y,
            float width,
            float height)
        {
            GameObject textObject = new GameObject(value);
            textObject.transform.SetParent(parent, false);
            RectTransform rect = textObject.AddComponent<RectTransform>();
            rect.anchorMin = new Vector2(0f, 1f);
            rect.anchorMax = new Vector2(0f, 1f);
            rect.pivot = new Vector2(0f, 1f);
            rect.anchoredPosition = new Vector2(20f, y);
            rect.sizeDelta = new Vector2(width, height);
            Text text = textObject.AddComponent<Text>();
            text.font = font;
            text.fontSize = fontSize;
            text.color = Color.white;
            text.alignment = TextAnchor.UpperLeft;
            text.horizontalOverflow = HorizontalWrapMode.Wrap;
            text.verticalOverflow = VerticalWrapMode.Overflow;
            text.text = value;
            return text;
        }

        private static void CreateButton(
            Transform parent,
            Font font,
            PrototypeP2GameController controller,
            string label,
            string command,
            float x,
            float y,
            float width)
        {
            GameObject buttonObject = new GameObject(label);
            buttonObject.transform.SetParent(parent, false);
            RectTransform rect = buttonObject.AddComponent<RectTransform>();
            rect.anchorMin = new Vector2(0f, 1f);
            rect.anchorMax = new Vector2(0f, 1f);
            rect.pivot = new Vector2(0f, 1f);
            rect.anchoredPosition = new Vector2(x, y);
            rect.sizeDelta = new Vector2(width, 38f);
            Image image = buttonObject.AddComponent<Image>();
            image.color = new Color(0.18f, 0.28f, 0.4f, 1f);
            Button button = buttonObject.AddComponent<Button>();
            button.targetGraphic = image;

            Text buttonText = CreateText(buttonObject.transform, font, label, 15, -5f, width, 30f);
            buttonText.rectTransform.anchoredPosition = new Vector2(0f, -4f);
            buttonText.rectTransform.sizeDelta = new Vector2(width, 30f);
            buttonText.alignment = TextAnchor.MiddleCenter;
            PrototypeP2UiAction action = buttonObject.AddComponent<PrototypeP2UiAction>();
            action.Configure(controller, command);
            UnityEventTools.AddPersistentListener(button.onClick, action.InvokeAction);
        }

        private static Material GetOrCreateMaterial(string assetName, Color color)
        {
            EnsureAssetFolder(MaterialFolder);
            string assetPath = $"{MaterialFolder}/{assetName}.mat";
            Material material = AssetDatabase.LoadAssetAtPath<Material>(assetPath);
            if (material == null)
            {
                Shader shader = Shader.Find("Standard") ??
                                Shader.Find("Universal Render Pipeline/Lit") ??
                                Shader.Find("Sprites/Default");
                material = new Material(shader);
                AssetDatabase.CreateAsset(material, assetPath);
            }
            material.color = color;
            EditorUtility.SetDirty(material);
            return material;
        }

        private static Font LoadBuiltInFont()
        {
#if UNITY_6000_0_OR_NEWER
            return Resources.GetBuiltinResource<Font>("LegacyRuntime.ttf");
#else
            return Resources.GetBuiltinResource<Font>("Arial.ttf");
#endif
        }

        private static void EnsureAssetFolder(string folder)
        {
            if (AssetDatabase.IsValidFolder(folder))
            {
                return;
            }
            string parent = Path.GetDirectoryName(folder)?.Replace('\\', '/');
            string name = Path.GetFileName(folder);
            if (string.IsNullOrEmpty(parent) || string.IsNullOrEmpty(name))
            {
                return;
            }
            EnsureAssetFolder(parent);
            AssetDatabase.CreateFolder(parent, name);
        }
    }
}
