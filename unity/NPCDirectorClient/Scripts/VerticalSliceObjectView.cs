using System;
using UnityEngine;

namespace NPCDirector
{
    [Serializable]
    public sealed class VerticalSliceStateMaterial
    {
        public string state;
        public Material material;
    }

    public sealed class VerticalSliceObjectView : MonoBehaviour
    {
        [SerializeField] private string objectId;
        [SerializeField] private Renderer[] targetRenderers = Array.Empty<Renderer>();
        [SerializeField] private VerticalSliceStateMaterial[] stateMaterials =
            Array.Empty<VerticalSliceStateMaterial>();

        public string ObjectId => objectId;

        public void Configure(
            string id,
            Renderer[] renderers,
            VerticalSliceStateMaterial[] materials)
        {
            objectId = id;
            targetRenderers = renderers ?? Array.Empty<Renderer>();
            stateMaterials = materials ?? Array.Empty<VerticalSliceStateMaterial>();
        }

        public bool ApplyState(string state)
        {
            foreach (VerticalSliceStateMaterial mapping in stateMaterials)
            {
                if (mapping != null && mapping.state == state && mapping.material != null)
                {
                    foreach (Renderer target in targetRenderers)
                    {
                        if (target != null)
                        {
                            target.sharedMaterial = mapping.material;
                        }
                    }
                    return true;
                }
            }
            return false;
        }
    }
}
