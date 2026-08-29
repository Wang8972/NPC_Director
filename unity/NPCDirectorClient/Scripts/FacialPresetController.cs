using System;
using System.Collections.Generic;
using UnityEngine;

namespace NPCDirector
{
    [Serializable]
    public sealed class BlendShapeWeight
    {
        public string blendShape;
        [Range(0, 100)] public float weight;
    }

    [Serializable]
    public sealed class FacialPreset
    {
        public string name;
        public BlendShapeWeight[] weights = Array.Empty<BlendShapeWeight>();
    }

    public sealed class FacialPresetController : MonoBehaviour
    {
        [SerializeField] private SkinnedMeshRenderer faceMesh;
        [SerializeField] private FacialPreset[] presets = Array.Empty<FacialPreset>();
        private readonly Dictionary<string, FacialPreset> lookup =
            new Dictionary<string, FacialPreset>(StringComparer.Ordinal);

        private static readonly HashSet<string> MinimumWhitelist =
            new HashSet<string>(StringComparer.Ordinal)
            {
                "neutral", "happy", "sad", "angry", "surprised"
            };

        private void Awake()
        {
            Rebuild();
        }

        public void ConfigureForPrototype()
        {
            presets = new[] { new FacialPreset { name = "neutral" } };
            Rebuild();
        }

        private void Rebuild()
        {
            lookup.Clear();
            foreach (FacialPreset preset in presets)
            {
                if (preset != null && !string.IsNullOrWhiteSpace(preset.name))
                {
                    lookup[preset.name] = preset;
                }
            }
        }

        public bool Apply(string presetName, float intensity)
        {
            if (faceMesh == null || !lookup.TryGetValue(presetName, out FacialPreset preset))
            {
                return false;
            }
            float scale = Mathf.Clamp01(intensity);
            foreach (BlendShapeWeight item in preset.weights)
            {
                int index = faceMesh.sharedMesh.GetBlendShapeIndex(item.blendShape);
                if (index >= 0)
                {
                    faceMesh.SetBlendShapeWeight(index, item.weight * scale);
                }
            }
            return true;
        }

        public bool Contains(string presetName)
        {
            return lookup.ContainsKey(presetName);
        }

        public bool IsMinimumPreset(string presetName)
        {
            return MinimumWhitelist.Contains(presetName);
        }
    }
}
