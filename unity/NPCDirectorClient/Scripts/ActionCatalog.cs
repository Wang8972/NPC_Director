using System;
using System.Collections.Generic;
using UnityEngine;

namespace NPCDirector
{
    [Serializable]
    public sealed class ActionCatalogEntry
    {
        public string action;
        public string animatorState;
        public int layer;
        [Range(0, 100)] public int defaultPriority = 50;
    }

    public sealed class ActionCatalog : MonoBehaviour
    {
        [SerializeField] private List<ActionCatalogEntry> entries = new List<ActionCatalogEntry>();
        private readonly Dictionary<string, ActionCatalogEntry> lookup =
            new Dictionary<string, ActionCatalogEntry>(StringComparer.Ordinal);

        private static readonly HashSet<string> MinimumWhitelist =
            new HashSet<string>(StringComparer.Ordinal)
            {
                "idle", "nod", "shake_head", "step_forward", "point"
            };

        private void Awake()
        {
            lookup.Clear();
            foreach (ActionCatalogEntry entry in entries)
            {
                if (entry == null || string.IsNullOrWhiteSpace(entry.action))
                {
                    continue;
                }
                lookup[entry.action] = entry;
            }
        }

        public bool TryGet(string action, out ActionCatalogEntry entry)
        {
            return lookup.TryGetValue(action, out entry);
        }

        public bool IsMinimumAction(string action)
        {
            return MinimumWhitelist.Contains(action);
        }
    }
}
