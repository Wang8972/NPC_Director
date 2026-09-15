using UnityEngine;

namespace LastLight
{
    /// <summary>Normalizes JsonUtility's empty instances for optional wire objects.</summary>
    public static class GameJson
    {
        public static T Deserialize<T>(string json)
        {
            var result = JsonUtility.FromJson<T>(json);
            if (result is ApiResponse response) Normalize(response);
            else if (result is GameView view) Normalize(view);
            else if (result is DialogueLine line) Normalize(line);
            return result;
        }

        static void Normalize(ApiResponse response)
        {
            if (response == null) return;
            if (response.view != null && string.IsNullOrEmpty(response.view.session_id)) response.view = null;
            if (response.job != null && string.IsNullOrEmpty(response.job.id)) response.job = null;
            Normalize(response.view);
        }

        static void Normalize(GameView view)
        {
            if (view == null) return;
            if (view.execution != null && string.IsNullOrEmpty(view.execution.id)) view.execution = null;
            foreach (var line in view.dialogue ?? System.Array.Empty<DialogueLine>()) Normalize(line);
            foreach (var line in view.epilogues ?? System.Array.Empty<DialogueLine>()) Normalize(line);
        }

        static void Normalize(DialogueLine line)
        {
            if (line == null || line.performance == null) return;
            if (string.IsNullOrEmpty(line.performance.schema_version) &&
                string.IsNullOrEmpty(line.performance.turn_id) &&
                string.IsNullOrEmpty(line.performance.npc_id))
                line.performance = null;
        }
    }
}
