using System;
using System.Collections.Generic;
using System.Security.Cryptography;
using System.Text;
using UnityEngine;

namespace NPCDirector
{
    public sealed class PrototypeSceneStateController : MonoBehaviour
    {
        private static readonly string[] CanonicalObjectIds =
        {
            "gate_console",
            "generator",
            "control_cabinet",
            "cargo_crate_c12",
            "manifest_board",
            "alarm_lamp"
        };

        private readonly Dictionary<string, string> appliedStates =
            new Dictionary<string, string>(StringComparer.Ordinal);
        private readonly Dictionary<string, Renderer> renderers =
            new Dictionary<string, Renderer>(StringComparer.Ordinal);

        private string currentSessionId;
        private int lastWorldVersion = -1;
        private string objectiveState;
        private string spareFuseLocation;
        private PrototypeRouteFlags routeFlags = new PrototypeRouteFlags();

        public int AppliedSnapshotCount { get; private set; }
        public int MappingApplicationCount { get; private set; }
        public int StaleSnapshotIgnoreCount { get; private set; }
        public int DuplicateSnapshotIgnoreCount { get; private set; }
        public int MissingRendererCount { get; private set; }
        public int LastWorldVersion => lastWorldVersion;

        private void Awake()
        {
            BuildRendererLookup();
        }

        public void BeginSession(string sessionId)
        {
            currentSessionId = sessionId;
            lastWorldVersion = -1;
            objectiveState = null;
            spareFuseLocation = null;
            routeFlags = new PrototypeRouteFlags();
            appliedStates.Clear();
            AppliedSnapshotCount = 0;
            MappingApplicationCount = 0;
            StaleSnapshotIgnoreCount = 0;
            DuplicateSnapshotIgnoreCount = 0;
            MissingRendererCount = 0;
            BuildRendererLookup();
        }

        public bool ApplySnapshot(PrototypeStateSnapshotPayload snapshot)
        {
            if (snapshot == null || snapshot.scene_id != "prototype_gate_repair")
            {
                Debug.LogWarning("[S3_SNAPSHOT_REJECT] null payload or wrong scene");
                return false;
            }
            if (currentSessionId != snapshot.session_id)
            {
                BeginSession(snapshot.session_id);
            }
            if (snapshot.world_version < lastWorldVersion)
            {
                StaleSnapshotIgnoreCount += 1;
                Debug.Log(
                    $"[S3_STALE_IGNORED] incoming={snapshot.world_version} " +
                    $"current={lastWorldVersion}");
                return false;
            }
            if (snapshot.world_version == lastWorldVersion)
            {
                DuplicateSnapshotIgnoreCount += 1;
                Debug.Log($"[S3_DUPLICATE_IGNORED] version={snapshot.world_version}");
                return false;
            }

            Dictionary<string, string> incoming = new Dictionary<string, string>(
                StringComparer.Ordinal);
            foreach (PrototypeObjectState item in snapshot.object_states ??
                     Array.Empty<PrototypeObjectState>())
            {
                if (item == null || string.IsNullOrWhiteSpace(item.object_id) ||
                    incoming.ContainsKey(item.object_id))
                {
                    Debug.LogWarning("[S3_SNAPSHOT_REJECT] duplicate or empty object id");
                    return false;
                }
                incoming.Add(item.object_id, item.state);
            }
            if (incoming.Count != CanonicalObjectIds.Length)
            {
                Debug.LogWarning($"[S3_SNAPSHOT_REJECT] object count={incoming.Count}");
                return false;
            }
            foreach (string objectId in CanonicalObjectIds)
            {
                if (!incoming.ContainsKey(objectId))
                {
                    Debug.LogWarning($"[S3_SNAPSHOT_REJECT] missing object={objectId}");
                    return false;
                }
                if (!TryGetRenderer(objectId, out _))
                {
                    MissingRendererCount += 1;
                    Debug.LogWarning($"[S3_SNAPSHOT_REJECT] no Renderer for {objectId}");
                    return false;
                }
            }

            foreach (string objectId in CanonicalObjectIds)
            {
                string state = incoming[objectId];
                appliedStates[objectId] = state;
                TryGetRenderer(objectId, out Renderer targetRenderer);
                targetRenderer.material.color = ColorForState(state);
                MappingApplicationCount += 1;
            }
            objectiveState = snapshot.objective_state;
            spareFuseLocation = FindItemLocation(snapshot, "spare_fuse");
            routeFlags = snapshot.route_flags ?? new PrototypeRouteFlags();
            lastWorldVersion = snapshot.world_version;
            AppliedSnapshotCount += 1;
            Debug.Log(
                $"[S3_SNAPSHOT_APPLIED] version={lastWorldVersion} " +
                $"objective={objectiveState} mappings={MappingApplicationCount}");
            return true;
        }

        public bool HasState(string objectId, string expectedState)
        {
            return appliedStates.TryGetValue(objectId, out string actual) &&
                   actual == expectedState;
        }

        public string StableStateHash()
        {
            StringBuilder canonical = new StringBuilder();
            canonical.Append(objectiveState).Append('|');
            foreach (string objectId in CanonicalObjectIds)
            {
                appliedStates.TryGetValue(objectId, out string state);
                canonical.Append(objectId).Append('=').Append(state).Append('|');
            }
            canonical.Append("spare_fuse=").Append(spareFuseLocation).Append('|');
            canonical.Append("route=").Append(routeFlags.fuse_route).Append('|');
            canonical.Append("crate_auth=").Append(routeFlags.crate_c12_authorized).Append('|');
            canonical.Append("cabinet_auth=").Append(routeFlags.control_cabinet_authorized);
            using (SHA256 sha = SHA256.Create())
            {
                byte[] digest = sha.ComputeHash(Encoding.UTF8.GetBytes(canonical.ToString()));
                return BitConverter.ToString(digest).Replace("-", "").ToLowerInvariant();
            }
        }

        private void BuildRendererLookup()
        {
            renderers.Clear();
            foreach (string objectId in CanonicalObjectIds)
            {
                GameObject target = GameObject.Find(objectId);
                Renderer targetRenderer = target != null ? target.GetComponent<Renderer>() : null;
                if (targetRenderer != null)
                {
                    renderers[objectId] = targetRenderer;
                }
            }
        }

        private bool TryGetRenderer(string objectId, out Renderer targetRenderer)
        {
            if (renderers.TryGetValue(objectId, out targetRenderer) && targetRenderer != null)
            {
                return true;
            }
            GameObject target = GameObject.Find(objectId);
            targetRenderer = target != null ? target.GetComponent<Renderer>() : null;
            if (targetRenderer == null)
            {
                return false;
            }
            renderers[objectId] = targetRenderer;
            return true;
        }

        private static string FindItemLocation(
            PrototypeStateSnapshotPayload snapshot,
            string itemId)
        {
            foreach (PrototypeItemLocation item in snapshot.item_locations ??
                     Array.Empty<PrototypeItemLocation>())
            {
                if (item != null && item.item_id == itemId)
                {
                    return item.location_id;
                }
            }
            return null;
        }

        private static Color ColorForState(string state)
        {
            string value = state ?? "";
            if (value.Contains("online") || value.Contains("running") ||
                value.Contains("complete") || value.Contains("green"))
            {
                return new Color(0.2f, 0.8f, 0.3f);
            }
            if (value.Contains("standby") || value.Contains("authorized") ||
                value.Contains("amber"))
            {
                return new Color(1f, 0.75f, 0.15f);
            }
            if (value.Contains("readable"))
            {
                return new Color(0.2f, 0.75f, 0.9f);
            }
            if (value.Contains("sealed"))
            {
                return new Color(0.7f, 0.25f, 0.8f);
            }
            return new Color(0.9f, 0.2f, 0.2f);
        }
    }
}
