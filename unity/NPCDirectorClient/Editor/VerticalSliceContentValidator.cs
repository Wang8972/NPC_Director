using UnityEditor;
using UnityEditor.Build;
using UnityEditor.Build.Reporting;
using UnityEngine;

namespace NPCDirector.Editor
{
    public sealed class VerticalSliceContentValidator : IPreprocessBuildWithReport
    {
        public int callbackOrder => 0;

        [MenuItem("NPC Director/Vertical Slice/Validate Content Catalog")]
        public static void ValidateFromMenu()
        {
            if (!PrototypeContentCatalogLoader.TryLoadAndValidate(
                    out PrototypeContentCatalogData catalog,
                    out string error))
            {
                Debug.LogError($"[VS1_CATALOG] FAIL error={error}");
                return;
            }
            Debug.Log(
                $"[VS1_CATALOG] PASS version={catalog.catalog_version} " +
                $"npcs={catalog.npc_profiles.Length} objects={catalog.object_ids.Length} " +
                $"facts={catalog.facts.Length}");
        }

        public void OnPreprocessBuild(BuildReport report)
        {
            if (!PrototypeContentCatalogLoader.TryLoadAndValidate(
                    out _,
                    out string error))
            {
                throw new BuildFailedException(
                    $"Vertical-slice content catalog validation failed: {error}");
            }
        }
    }
}
