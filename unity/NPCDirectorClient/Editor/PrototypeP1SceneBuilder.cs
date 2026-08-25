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
    public static class PrototypeP1SceneBuilder
    {
        private const string ScenePath = "Assets/Scenes/PrototypeGateRepairP1.unity";
        private const string MaterialFolder = "Assets/NPCDirectorGenerated/P1Materials";

        [MenuItem("NPC Director/P1/Create or Reset Graybox Scene")]
        public static void CreateOrResetScene()
        {
            bool confirmed = EditorUtility.DisplayDialog(
                "Create P1 Graybox Scene",
                "This replaces the currently open scene. Save unrelated work before continuing.",
                "Create P1 Scene",
                "Cancel");
            if (!confirmed)
            {
                return;
            }

            Scene scene = EditorSceneManager.NewScene(NewSceneSetup.EmptyScene, NewSceneMode.Single);
            CreateCameraAndLighting();

            GameObject root = new GameObject("P1PrototypeRoot");
            PrototypeSceneStateController sceneState =
                root.AddComponent<PrototypeSceneStateController>();
            PrototypeGameFlowController flow =
                root.AddComponent<PrototypeGameFlowController>();
            PrototypeP1GateRunner gateRunner = root.AddComponent<PrototypeP1GateRunner>();

            CreateEnvironment(flow);
            CreateNpcs(flow);
            CreateUi(flow, sceneState);
            gateRunner.Configure(flow);

            EnsureAssetFolder("Assets/Scenes");
            EditorSceneManager.MarkSceneDirty(scene);
            EditorSceneManager.SaveScene(scene, ScenePath);
            AssetDatabase.SaveAssets();
            Selection.activeGameObject = root;
            Debug.Log(
                $"[P1_SCENE_BUILDER] created scene={ScenePath} npcs=3 hotspots=6 " +
                "backend_clients=0");
        }

        [MenuItem("NPC Director/P1/Validate Open Graybox Scene")]
        public static void ValidateOpenScene()
        {
            int npcCount = Object.FindObjectsOfType<PrototypeNpcSelector>(true).Length;
            int hotspotCount = Object.FindObjectsOfType<PrototypeHotspot>(true).Length;
            int flowCount = Object.FindObjectsOfType<PrototypeGameFlowController>(true).Length;
            int backendClientCount = Object.FindObjectsOfType<NPCDirectorClient>(true).Length;
            bool allObjectsPresent = true;
            string[] objectIds =
            {
                "gate_console",
                "generator",
                "control_cabinet",
                "cargo_crate_c12",
                "manifest_board",
                "alarm_lamp"
            };
            foreach (string objectId in objectIds)
            {
                allObjectsPresent &= GameObject.Find(objectId) != null;
            }
            bool passed = npcCount == 3 && hotspotCount == 6 && flowCount == 1 &&
                          backendClientCount == 0 && allObjectsPresent;
            Debug.Log(
                $"[P1_SCENE_VALIDATE] {(passed ? "PASS" : "FAIL")} " +
                $"npcs={npcCount} hotspots={hotspotCount} flow={flowCount} " +
                $"backend_clients={backendClientCount} objects_present={allObjectsPresent}");
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
            camera.rect = new Rect(0.32f, 0f, 0.68f, 1f);

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

        private static void CreateEnvironment(PrototypeGameFlowController flow)
        {
            CreateHotspot(flow, "gate_console", new Vector3(-5f, 0.7f, 0f), new Vector3(1.3f, 1.4f, 0.7f));
            CreateHotspot(flow, "generator", new Vector3(-3f, 0.7f, 0f), new Vector3(1.3f, 1.4f, 0.9f));
            CreateHotspot(flow, "control_cabinet", new Vector3(-1f, 0.8f, 0f), new Vector3(1.2f, 1.6f, 0.7f));
            CreateHotspot(flow, "cargo_crate_c12", new Vector3(1.2f, 0.65f, 0f), new Vector3(1.4f, 1.3f, 1.1f));
            CreateHotspot(flow, "manifest_board", new Vector3(3.4f, 0.8f, 0f), new Vector3(1.4f, 1.6f, 0.35f));
            CreateHotspot(flow, "alarm_lamp", new Vector3(5.3f, 0.8f, 0f), new Vector3(0.8f, 1.6f, 0.8f));
        }

        private static void CreateNpcs(PrototypeGameFlowController flow)
        {
            CreateNpc(
                flow,
                PrototypePuzzleRules.MarenId,
                "Maren",
                new Vector3(-3.5f, 1f, 3.5f),
                new Color(0.25f, 0.45f, 0.8f));
            CreateNpc(
                flow,
                PrototypePuzzleRules.LiaId,
                "Lia",
                new Vector3(0f, 1f, 3.5f),
                new Color(0.85f, 0.65f, 0.2f));
            CreateNpc(
                flow,
                PrototypePuzzleRules.FinnId,
                "Finn",
                new Vector3(3.5f, 1f, 3.5f),
                new Color(0.55f, 0.35f, 0.22f));
        }

        private static void CreateHotspot(
            PrototypeGameFlowController flow,
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
            PrototypeHotspot hotspot = target.AddComponent<PrototypeHotspot>();
            hotspot.Configure(flow, objectId);
            CreateWorldLabel(target.transform, objectId, scale.y * 0.5f + 0.35f);
        }

        private static void CreateNpc(
            PrototypeGameFlowController flow,
            string npcId,
            string displayName,
            Vector3 position,
            Color color)
        {
            GameObject npc = GameObject.CreatePrimitive(PrimitiveType.Capsule);
            npc.name = npcId;
            npc.transform.position = position;
            npc.GetComponent<Renderer>().sharedMaterial = GetOrCreateMaterial($"npc_{npcId}", color);
            PrototypeNpcSelector selector = npc.AddComponent<PrototypeNpcSelector>();
            selector.Configure(flow, npcId);
            CreateWorldLabel(npc.transform, displayName, 1.45f);
        }

        private static void CreateWorldLabel(Transform parent, string value, float height)
        {
            GameObject labelObject = new GameObject("Label");
            labelObject.name = parent.name + "_label";
            labelObject.transform.position = parent.position + Vector3.up * height;
            labelObject.transform.rotation = Quaternion.identity;
            labelObject.transform.localScale = Vector3.one * 0.13f;
            TextMesh label = labelObject.AddComponent<TextMesh>();
            label.text = value;
            label.anchor = TextAnchor.MiddleCenter;
            label.alignment = TextAlignment.Center;
            label.fontSize = 40;
            label.color = Color.white;
        }

        private static void CreateUi(
            PrototypeGameFlowController flow,
            PrototypeSceneStateController sceneState)
        {
            GameObject canvasObject = new GameObject("P1Canvas");
            Canvas canvas = canvasObject.AddComponent<Canvas>();
            canvas.renderMode = RenderMode.ScreenSpaceOverlay;
            CanvasScaler scaler = canvasObject.AddComponent<CanvasScaler>();
            scaler.uiScaleMode = CanvasScaler.ScaleMode.ScaleWithScreenSize;
            scaler.referenceResolution = new Vector2(1920f, 1080f);
            canvasObject.AddComponent<GraphicRaycaster>();

            GameObject eventSystem = new GameObject("EventSystem");
            eventSystem.AddComponent<EventSystem>();
            eventSystem.AddComponent<StandaloneInputModule>();

            GameObject panelObject = new GameObject("ControlPanel");
            panelObject.transform.SetParent(canvasObject.transform, false);
            RectTransform panelRect = panelObject.AddComponent<RectTransform>();
            panelRect.anchorMin = new Vector2(0f, 0f);
            panelRect.anchorMax = new Vector2(0f, 1f);
            panelRect.pivot = new Vector2(0f, 0.5f);
            panelRect.anchoredPosition = Vector2.zero;
            panelRect.sizeDelta = new Vector2(620f, 0f);
            Image panelImage = panelObject.AddComponent<Image>();
            panelImage.color = new Color(0.04f, 0.06f, 0.09f, 0.93f);

            Font font = LoadBuiltInFont();
            Text title = CreateText(panelObject.transform, font, "P1 本地灰盒", 28, -18f, 580f, 42f);
            title.fontStyle = FontStyle.Bold;
            Text objective = CreateText(panelObject.transform, font, "目标：", 22, -65f, 580f, 55f);
            Text selected = CreateText(panelObject.transform, font, "当前 NPC：", 20, -120f, 580f, 40f);
            Text route = CreateText(panelObject.transform, font, "路线：", 20, -160f, 580f, 40f);
            Text feedback = CreateText(panelObject.transform, font, "反馈 / 字幕：", 20, -205f, 580f, 80f);
            Text clues = CreateText(panelObject.transform, font, "线索：", 17, -300f, 580f, 190f);
            Text state = CreateText(panelObject.transform, font, "state", 15, -505f, 580f, 145f);

            flow.Configure(sceneState, objective, selected, route, clues, feedback, state);

            float firstButtonY = -665f;
            CreateButton(panelObject.transform, font, flow, "选择玛伦", "select:" + PrototypePuzzleRules.MarenId, 10f, firstButtonY);
            CreateButton(panelObject.transform, font, flow, "选择莉娅", "select:" + PrototypePuzzleRules.LiaId, 205f, firstButtonY);
            CreateButton(panelObject.transform, font, flow, "选择费恩", "select:" + PrototypePuzzleRules.FinnId, 400f, firstButtonY);

            CreateButton(panelObject.transform, font, flow, "转述缺保险丝", PrototypePuzzleRules.TellDiagnosis, 10f, firstButtonY - 48f, 280f);
            CreateButton(panelObject.transform, font, flow, "转述 C-12 记录", PrototypePuzzleRules.TellManifest, 305f, firstButtonY - 48f, 280f);
            CreateButton(panelObject.transform, font, flow, "回应费恩并请求交付", PrototypePuzzleRules.OfferCooperation, 10f, firstButtonY - 96f, 280f);
            CreateButton(panelObject.transform, font, flow, "请求玛伦授权 C-12", PrototypePuzzleRules.RequestProcedure, 305f, firstButtonY - 96f, 280f);
            CreateButton(panelObject.transform, font, flow, "运行自动验收", "self_check", 10f, firstButtonY - 144f, 280f);
            CreateButton(panelObject.transform, font, flow, "重置原型", "reset", 305f, firstButtonY - 144f, 280f);

            CreateText(
                panelObject.transform,
                font,
                "玩法：点击场景对象进行观察或动作；点击 Capsule 或上方按钮选择 NPC。\n" +
                "合作：诊断 → 告知费恩 → 回应顾虑并请求交付。\n" +
                "程序：诊断 + 记录板 → 两项事实告知玛伦 → 授权 → 费恩点击 C-12。",
                16,
                firstButtonY - 205f,
                580f,
                120f);
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
            PrototypeGameFlowController flow,
            string label,
            string command,
            float x,
            float y,
            float width = 180f)
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

            Text buttonText = CreateText(buttonObject.transform, font, label, 16, -7f, width, 30f);
            RectTransform textRect = buttonText.rectTransform;
            textRect.anchoredPosition = new Vector2(0f, -5f);
            textRect.sizeDelta = new Vector2(width, 30f);
            buttonText.alignment = TextAnchor.MiddleCenter;

            PrototypeUiAction action = buttonObject.AddComponent<PrototypeUiAction>();
            action.Configure(flow, command);
            UnityEventTools.AddPersistentListener(button.onClick, action.InvokeAction);
        }

        private static Material GetOrCreateMaterial(string assetName, Color color)
        {
            EnsureAssetFolder(MaterialFolder);
            string assetPath = $"{MaterialFolder}/{assetName}.mat";
            Material material = AssetDatabase.LoadAssetAtPath<Material>(assetPath);
            if (material == null)
            {
                Shader shader = Shader.Find("Standard");
                if (shader == null)
                {
                    shader = Shader.Find("Universal Render Pipeline/Lit");
                }
                if (shader == null)
                {
                    shader = Shader.Find("Sprites/Default");
                }
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
