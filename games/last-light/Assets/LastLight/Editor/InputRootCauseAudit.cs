#if UNITY_EDITOR
using System;
using System.IO;
using System.Reflection;
using UnityEngine;

namespace LastLight.Editor
{
    public static class InputRootCauseAudit
    {
        public static void VerifyFix()
        {
            var log = new System.Collections.Generic.List<string>();
            var samples = new[] {
                "{\"ok\":true,\"view\":{\"session_id\":\"audit\",\"execution\":null},\"job\":null}",
                "{\"ok\":true,\"view\":{\"session_id\":\"audit\"}}",
                File.ReadAllText("artifacts/input-audit/actual-session-response.json"),
                "{\"ok\":true,\"view\":{\"session_id\":\"audit\",\"execution\":{\"id\":\"e1\",\"plan_id\":\"p1\"}},\"job\":{\"id\":\"j1\",\"status\":\"running\"}}"
            };
            for (int i = 0; i < samples.Length; i++)
            {
                var response = GameJson.Deserialize<ApiResponse>(samples[i]);
                bool idle = i < 3;
                if ((response.view.execution == null) != idle) throw new Exception("Execution null semantics: " + i);
                if ((response.job == null) != idle) throw new Exception("Job null semantics: " + i);
                var go = new GameObject("Null contract regression");
                var buttonGo = new GameObject("Send", typeof(RectTransform), typeof(UnityEngine.UI.Button));
                try
                {
                    var app = go.AddComponent<LastLightApp>();
                    var flags = BindingFlags.NonPublic | BindingFlags.Instance;
                    typeof(LastLightApp).GetField("view", flags).SetValue(app, response.view);
                    typeof(LastLightApp).GetField("titleOpen", flags).SetValue(app, false);
                    typeof(LastLightApp).GetField("selectedNpc", flags).SetValue(app, "lin");
                    var button = buttonGo.GetComponent<UnityEngine.UI.Button>();
                    typeof(LastLightApp).GetField("sendButton", flags).SetValue(app, button);
                    typeof(LastLightApp).GetMethod("RefreshInteractivity", flags).Invoke(app, null);
                    bool canAct = (bool)typeof(LastLightApp).GetMethod("CanAct", flags).Invoke(app, null);
                    if (canAct != idle || button.interactable != idle) throw new Exception("Action/UI gating: " + i);
                    log.Add("PASS case=" + i + " idle=" + idle + " CanAct=" + canAct + " send=" + button.interactable);
                }
                finally { UnityEngine.Object.DestroyImmediate(buttonGo); UnityEngine.Object.DestroyImmediate(go); }
            }
            if (GameJson.Deserialize<ApiResponse>("{\"ok\":false,\"view\":null,\"job\":null}").view != null)
                throw new Exception("Null view lost");
            if (GameJson.Deserialize<DialogueLine>("{\"text\":\"旧存档\",\"performance\":null}").performance != null)
                throw new Exception("Legacy performance null lost");
            if (GameJson.Deserialize<DialogueLine>("{\"text\":\"旧存档\"}").performance != null)
                throw new Exception("Omitted performance not null");
            var performance = GameJson.Deserialize<DialogueLine>("{\"performance\":{\"schema_version\":\"1.0\",\"turn_id\":\"turn-1\",\"npc_id\":\"lin\",\"face_cues\":[{\"preset\":\"concerned\",\"intensity\":0.7}]}}");
            if (performance.performance.face_cues.Length != 1) throw new Exception("Real performance lost");
            log.Add("PASS null view, legacy performance, real performance");
            File.WriteAllLines("artifacts/input-audit/json-null-fix-verification.txt", log);
            Debug.Log("[JSON_NULL_FIX_VERIFIED]\n" + string.Join("\n", log));
        }

        public static void Run()
        {
            var lines = new System.Collections.Generic.List<string>();
            var samples = new System.Collections.Generic.List<string> {
                "{\"ok\":true,\"view\":{\"session_id\":\"audit\",\"execution\":null,\"plans\":[]},\"job\":null}",
                "{\"ok\":true,\"view\":{\"session_id\":\"audit\",\"plans\":[]}}",
                "{\"ok\":true,\"view\":{\"session_id\":\"audit\",\"execution\":{\"id\":\"real-execution\",\"plan_id\":\"real-plan\"}}}"
            };
            const string actualPath = "artifacts/input-audit/actual-session-response.json";
            if (File.Exists(actualPath)) samples.Add(File.ReadAllText(actualPath));
            foreach (var json in samples)
            {
                var response = JsonUtility.FromJson<ApiResponse>(json);
                var go = new GameObject("Input audit");
                var app = go.AddComponent<LastLightApp>();
                var flags = BindingFlags.Instance | BindingFlags.NonPublic;
                typeof(LastLightApp).GetField("view", flags).SetValue(app, response.view);
                typeof(LastLightApp).GetField("titleOpen", flags).SetValue(app, false);
                typeof(LastLightApp).GetField("selectedNpc", flags).SetValue(app, "lin");
                var buttonObject = new GameObject("Audit send button", typeof(RectTransform), typeof(UnityEngine.UI.Button));
                var button = buttonObject.GetComponent<UnityEngine.UI.Button>();
                typeof(LastLightApp).GetField("sendButton", flags).SetValue(app, button);
                var refresh = typeof(LastLightApp).GetMethod("RefreshInteractivity", flags);
                refresh.Invoke(app, null);
                var canAct = typeof(LastLightApp).GetMethod("CanAct", flags);
                lines.Add("json=" + (json.Length > 1000 ? "actual-session-response.json" : json));
                lines.Add("executionIsNull=" + (response.view.execution == null) +
                    "; executionId=" + response.view.execution?.id +
                    "; jobIsNull=" + (response.job == null) +
                    "; CanAct=" + canAct.Invoke(app, null) + "; sendButton.interactable=" + button.interactable);
                response.view.execution = null;
                refresh.Invoke(app, null);
                lines.Add("controlAfterSettingExecutionNull.CanAct=" + canAct.Invoke(app, null) +
                    "; sendButton.interactable=" + button.interactable);
                UnityEngine.Object.DestroyImmediate(buttonObject);
                UnityEngine.Object.DestroyImmediate(go);
            }
            Directory.CreateDirectory("artifacts/input-audit");
            File.WriteAllLines("artifacts/input-audit/json-null-reproduction.txt", lines);
            Debug.Log("[INPUT_ROOT_CAUSE_AUDIT]\n" + string.Join("\n", lines));
        }
    }
}
#endif
