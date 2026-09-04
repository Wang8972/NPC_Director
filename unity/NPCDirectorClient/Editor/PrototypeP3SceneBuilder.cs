using System;
using UnityEditor;
using UnityEditor.Events;
using UnityEditor.SceneManagement;
using UnityEngine;
using UnityEngine.SceneManagement;
using UnityEngine.UI;

namespace NPCDirector.Editor
{
    public static class PrototypeP3SceneBuilder
    {
        private const string ScenePath = "Assets/Scenes/PrototypeGateRepairP3.unity";
        private const string SessionId = "p3-real-001";
        private const string Endpoint = "ws://127.0.0.1:8767";

        [MenuItem("NPC Director/P3/Create or Reset Real Director Scene")]
        public static void CreateOrResetScene()
        {
            bool confirmed = EditorUtility.DisplayDialog(
                "Create P3 Real Director Scene",
                "This replaces the currently open scene and derives P3 from the verified P2 base.",
                "Create P3 Scene",
                "Cancel");
            if (!confirmed)
            {
                return;
            }

            GameObject root = PrototypeP2SceneBuilder.BuildBaseScene();
            root.name = "P3PrototypeRoot";
            PrototypeP2Client client = root.GetComponent<PrototypeP2Client>();
            PrototypeP2GameController controller = root.GetComponent<PrototypeP2GameController>();
            NpcRegistry registry = root.GetComponent<NpcRegistry>();
            PrototypeSceneActionExecutor actionExecutor =
                root.GetComponent<PrototypeSceneActionExecutor>();
            actionExecutor.Configure(SessionId, registry);
            client.Configure(Endpoint, SessionId, registry, actionExecutor, controller);
            client.SetConnectionModeLabel("Real");

            DisableFakeFixtureButtons();
            ReplaceTitle();
            CreateNaturalLanguageInput(client, controller);

            Scene scene = SceneManager.GetActiveScene();
            EditorSceneManager.MarkSceneDirty(scene);
            EditorSceneManager.SaveScene(scene, ScenePath);
            AssetDatabase.SaveAssets();
            Selection.activeGameObject = root;
            Debug.Log(
                $"[P3_SCENE_BUILDER] created scene={ScenePath} npcs=3 hotspots=6 " +
                "session_clients=1 text_inputs=1 mode=real");
        }

        [MenuItem("NPC Director/P3/Validate Open Real Director Scene")]
        public static void ValidateOpenScene()
        {
            int npcCount = UnityEngine.Object.FindObjectsOfType<PrototypeP2NpcSelector>(true).Length;
            int hotspotCount = UnityEngine.Object.FindObjectsOfType<PrototypeP2Hotspot>(true).Length;
            int clientCount = UnityEngine.Object.FindObjectsOfType<PrototypeP2Client>(true).Length;
            int inputCount = UnityEngine.Object.FindObjectsOfType<PrototypeP3TextInput>(true).Length;
            int enabledFixtureButtons = 0;
            foreach (PrototypeP2UiAction action in
                     UnityEngine.Object.FindObjectsOfType<PrototypeP2UiAction>(true))
            {
                if (action.gameObject.activeInHierarchy &&
                    action.Command.StartsWith("fixture:", StringComparison.Ordinal))
                {
                    enabledFixtureButtons += 1;
                }
            }
            bool passed = npcCount == 3 && hotspotCount == 6 && clientCount == 1 &&
                          inputCount == 1 && enabledFixtureButtons == 0;
            Debug.Log(
                $"[P3_SCENE_VALIDATE] {(passed ? "PASS" : "FAIL")} " +
                $"npcs={npcCount} hotspots={hotspotCount} clients={clientCount} " +
                $"text_inputs={inputCount} enabled_fixture_buttons={enabledFixtureButtons}");
        }

        private static void DisableFakeFixtureButtons()
        {
            foreach (PrototypeP2UiAction action in
                     UnityEngine.Object.FindObjectsOfType<PrototypeP2UiAction>(true))
            {
                if (action.Command.StartsWith("fixture:", StringComparison.Ordinal))
                {
                    action.gameObject.SetActive(false);
                }
            }
        }

        private static void ReplaceTitle()
        {
            foreach (Text text in UnityEngine.Object.FindObjectsOfType<Text>(true))
            {
                if (text.text == "P2 Fake Director")
                {
                    text.text = "P3 Real NPC Director";
                }
                else if (text.text == "连接：未启动")
                {
                    text.text = "连接：等待 Real Backend";
                }
            }
        }

        private static void CreateNaturalLanguageInput(
            PrototypeP2Client client,
            PrototypeP2GameController controller)
        {
            Canvas canvas = UnityEngine.Object.FindObjectOfType<Canvas>();
            GameObject panel = new GameObject("P3NaturalLanguagePanel");
            panel.transform.SetParent(canvas.transform, false);
            RectTransform panelRect = panel.AddComponent<RectTransform>();
            panelRect.anchorMin = new Vector2(0.36f, 0f);
            panelRect.anchorMax = new Vector2(0.98f, 0f);
            panelRect.pivot = new Vector2(0.5f, 0f);
            panelRect.anchoredPosition = new Vector2(0f, 22f);
            panelRect.sizeDelta = new Vector2(0f, 64f);
            panel.AddComponent<Image>().color = new Color(0.04f, 0.06f, 0.09f, 0.94f);

            Font font = LoadBuiltInFont();
            InputField input = CreateInputField(panel.transform, font);
            PrototypeP3TextInput submitter = panel.AddComponent<PrototypeP3TextInput>();
            submitter.Configure(client, controller, input);
            CreateSubmitButton(panel.transform, font, submitter);
        }

        private static InputField CreateInputField(Transform parent, Font font)
        {
            GameObject inputObject = new GameObject("PlayerInput");
            inputObject.transform.SetParent(parent, false);
            RectTransform rect = inputObject.AddComponent<RectTransform>();
            rect.anchorMin = new Vector2(0f, 0.5f);
            rect.anchorMax = new Vector2(1f, 0.5f);
            rect.pivot = new Vector2(0f, 0.5f);
            rect.anchoredPosition = new Vector2(12f, 0f);
            rect.sizeDelta = new Vector2(-190f, 44f);
            inputObject.AddComponent<Image>().color = Color.white;
            InputField input = inputObject.AddComponent<InputField>();

            Text text = CreateInputText(inputObject.transform, font, "Text", Color.black);
            Text placeholder = CreateInputText(
                inputObject.transform,
                font,
                "Placeholder",
                new Color(0.35f, 0.35f, 0.35f, 1f));
            placeholder.text = "选择 NPC 后输入自然语言；Enter 或点击发送";
            input.textComponent = text;
            input.placeholder = placeholder;
            input.lineType = InputField.LineType.SingleLine;
            return input;
        }

        private static Text CreateInputText(
            Transform parent,
            Font font,
            string name,
            Color color)
        {
            GameObject textObject = new GameObject(name);
            textObject.transform.SetParent(parent, false);
            RectTransform rect = textObject.AddComponent<RectTransform>();
            rect.anchorMin = Vector2.zero;
            rect.anchorMax = Vector2.one;
            rect.offsetMin = new Vector2(12f, 6f);
            rect.offsetMax = new Vector2(-12f, -6f);
            Text text = textObject.AddComponent<Text>();
            text.font = font;
            text.fontSize = 18;
            text.color = color;
            text.alignment = TextAnchor.MiddleLeft;
            text.horizontalOverflow = HorizontalWrapMode.Wrap;
            text.verticalOverflow = VerticalWrapMode.Truncate;
            return text;
        }

        private static void CreateSubmitButton(
            Transform parent,
            Font font,
            PrototypeP3TextInput submitter)
        {
            GameObject buttonObject = new GameObject("发送");
            buttonObject.transform.SetParent(parent, false);
            RectTransform rect = buttonObject.AddComponent<RectTransform>();
            rect.anchorMin = new Vector2(1f, 0.5f);
            rect.anchorMax = new Vector2(1f, 0.5f);
            rect.pivot = new Vector2(1f, 0.5f);
            rect.anchoredPosition = new Vector2(-12f, 0f);
            rect.sizeDelta = new Vector2(155f, 44f);
            Image image = buttonObject.AddComponent<Image>();
            image.color = new Color(0.18f, 0.45f, 0.28f, 1f);
            Button button = buttonObject.AddComponent<Button>();
            button.targetGraphic = image;
            Text label = CreateInputText(buttonObject.transform, font, "Label", Color.white);
            label.text = "发送给当前 NPC";
            label.alignment = TextAnchor.MiddleCenter;
            UnityEventTools.AddPersistentListener(button.onClick, submitter.Submit);
        }

        private static Font LoadBuiltInFont()
        {
#if UNITY_6000_0_OR_NEWER
            return Resources.GetBuiltinResource<Font>("LegacyRuntime.ttf");
#else
            return Resources.GetBuiltinResource<Font>("Arial.ttf");
#endif
        }
    }
}
