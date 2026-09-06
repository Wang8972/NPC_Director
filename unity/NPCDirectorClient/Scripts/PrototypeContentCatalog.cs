using System;
using System.Collections.Generic;
using UnityEngine;

namespace NPCDirector
{
    [Serializable]
    public sealed class PrototypeCatalogNpc
    {
        public string npc_id;
        public string display_name;
        public string role;
        public string stance;
        public string style;
        public string[] allowed_action_types = Array.Empty<string>();
    }

    [Serializable]
    public sealed class PrototypeCatalogFact
    {
        public string fact_id;
        public string text;
        public string[] sensitive_surfaces = Array.Empty<string>();
    }

    [Serializable]
    public sealed class PrototypeContentCatalogData
    {
        public string schema_version;
        public string catalog_version;
        public string scene_id;
        public PrototypeCatalogNpc[] npc_profiles = Array.Empty<PrototypeCatalogNpc>();
        public string[] object_ids = Array.Empty<string>();
        public string[] item_ids = Array.Empty<string>();
        public string[] route_ids = Array.Empty<string>();
        public string[] operation_ids = Array.Empty<string>();
        public PrototypeCatalogFact[] facts = Array.Empty<PrototypeCatalogFact>();
    }

    public static class PrototypeContentCatalogLoader
    {
        private static readonly HashSet<string> NpcIds = new HashSet<string>
        {
            "guard_captain_maren", "mechanic_lia", "porter_finn"
        };

        private static readonly HashSet<string> ObjectIds = new HashSet<string>
        {
            "gate_console", "generator", "control_cabinet", "cargo_crate_c12",
            "manifest_board", "alarm_lamp"
        };

        public static bool TryLoadAndValidate(
            out PrototypeContentCatalogData catalog,
            out string error)
        {
            TextAsset asset = Resources.Load<TextAsset>("VerticalSliceContentCatalog");
            if (asset == null)
            {
                catalog = null;
                error = "Resources/VerticalSliceContentCatalog.json is missing";
                return false;
            }
            catalog = JsonUtility.FromJson<PrototypeContentCatalogData>(asset.text);
            if (catalog == null || catalog.schema_version != "1.0" ||
                catalog.scene_id != "prototype_gate_repair")
            {
                error = "catalog schema or scene identity is invalid";
                return false;
            }
            if (!ExactIds(catalog.npc_profiles, NpcIds) ||
                !ExactIds(catalog.object_ids, ObjectIds) ||
                catalog.facts == null || catalog.facts.Length != 11 ||
                catalog.item_ids == null || catalog.item_ids.Length != 1 ||
                catalog.route_ids == null || catalog.route_ids.Length != 2)
            {
                error = "catalog scope no longer matches 3 NPC / 6 object vertical slice";
                return false;
            }
            error = null;
            return true;
        }

        private static bool ExactIds(
            PrototypeCatalogNpc[] values,
            HashSet<string> expected)
        {
            if (values == null || values.Length != expected.Count)
            {
                return false;
            }
            HashSet<string> actual = new HashSet<string>();
            foreach (PrototypeCatalogNpc value in values)
            {
                if (value == null || !actual.Add(value.npc_id))
                {
                    return false;
                }
            }
            return actual.SetEquals(expected);
        }

        private static bool ExactIds(string[] values, HashSet<string> expected)
        {
            return values != null && new HashSet<string>(values).SetEquals(expected) &&
                   values.Length == expected.Count;
        }
    }
}
