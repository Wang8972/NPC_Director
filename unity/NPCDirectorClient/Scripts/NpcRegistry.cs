using System;
using System.Collections.Generic;
using UnityEngine;

namespace NPCDirector
{
    [Serializable]
    public sealed class NpcExecutorBinding
    {
        public string npcId;
        public PerformanceExecutor executor;
    }

    public sealed class NpcRegistry : MonoBehaviour
    {
        [SerializeField] private NpcExecutorBinding[] bindings = Array.Empty<NpcExecutorBinding>();

        private readonly Dictionary<string, PerformanceExecutor> executors =
            new Dictionary<string, PerformanceExecutor>(StringComparer.Ordinal);
        private readonly Dictionary<string, int> routeCounts =
            new Dictionary<string, int>(StringComparer.Ordinal);

        public int UnknownRouteCount { get; private set; }
        public int RegisteredCount => executors.Count;

        private void Awake()
        {
            Rebuild();
        }

        public void Rebuild()
        {
            executors.Clear();
            routeCounts.Clear();
            foreach (NpcExecutorBinding binding in bindings)
            {
                if (binding == null || string.IsNullOrWhiteSpace(binding.npcId) ||
                    binding.executor == null)
                {
                    continue;
                }
                if (executors.ContainsKey(binding.npcId))
                {
                    Debug.LogError($"[S1_REGISTRY] duplicate npc_id={binding.npcId}");
                    continue;
                }
                executors.Add(binding.npcId, binding.executor);
                routeCounts.Add(binding.npcId, 0);
            }
            Debug.Log($"[S1_REGISTRY] ready executors={executors.Count}");
        }

        public bool TryResolve(string npcId, out PerformanceExecutor executor)
        {
            if (!string.IsNullOrWhiteSpace(npcId) && executors.TryGetValue(npcId, out executor))
            {
                routeCounts[npcId] += 1;
                Debug.Log(
                    $"[S1_ROUTE] npc_id={npcId} executor={executor.gameObject.name} " +
                    $"count={routeCounts[npcId]}");
                return true;
            }
            UnknownRouteCount += 1;
            executor = null;
            Debug.LogWarning($"[S1_ROUTE_REJECT] unknown npc_id={npcId}");
            return false;
        }

        public int GetRouteCount(string npcId)
        {
            return routeCounts.TryGetValue(npcId, out int count) ? count : 0;
        }

        [ContextMenu("Log S1 Route Summary")]
        public void LogSpikeSummary()
        {
            Debug.Log(
                "[S1_SUMMARY] " +
                $"maren={GetRouteCount("guard_captain_maren")} " +
                $"lia={GetRouteCount("mechanic_lia")} " +
                $"finn={GetRouteCount("porter_finn")} " +
                $"unknown={UnknownRouteCount} registered={RegisteredCount}");
        }
    }
}
