using System;
using UnityEngine;

namespace NPCDirector
{
    public sealed class PrototypeSnapshotSpikeRunner : MonoBehaviour
    {
        [SerializeField] private PrototypeSceneStateController controller;
        [SerializeField] private bool runOnStart = true;

        private static readonly string[] ObjectIds =
        {
            "gate_console",
            "generator",
            "control_cabinet",
            "cargo_crate_c12",
            "manifest_board",
            "alarm_lamp"
        };

        private void Start()
        {
            if (runOnStart)
            {
                RunSpike();
            }
        }

        [ContextMenu("Run S3 Snapshot Spike")]
        public void RunSpike()
        {
            if (controller == null)
            {
                Debug.LogError("[S3_FAIL] controller is not assigned");
                return;
            }

            PrototypeStateSnapshotPayload initial = Initial("s3-session", 0);
            PrototypeStateSnapshotPayload acquired = Acquired("s3-session", 1);
            PrototypeStateSnapshotPayload installed = Installed("s3-session", 2);
            PrototypeStateSnapshotPayload success = Success("s3-session", 3);

            controller.BeginSession("s3-session");
            int correctMappings = 0;
            correctMappings += ApplyAndCheck(initial);
            string initialHash = controller.StableStateHash();
            correctMappings += ApplyAndCheck(acquired);
            correctMappings += ApplyAndCheck(installed);
            correctMappings += ApplyAndCheck(success);

            PrototypeStateSnapshotPayload stale = Installed("s3-session", 2);
            stale.object_states[0].state = "offline_e17_stale_should_not_apply";
            controller.ApplySnapshot(stale);
            controller.ApplySnapshot(success);

            int staleIgnored = controller.StaleSnapshotIgnoreCount;
            int duplicateIgnored = controller.DuplicateSnapshotIgnoreCount;
            int sideEffectsBeforeReset = controller.MappingApplicationCount;
            int missingRenderers = controller.MissingRendererCount;

            controller.BeginSession("s3-reset");
            PrototypeStateSnapshotPayload reset = Initial("s3-reset", 0);
            int resetMappings = ApplyAndCheck(reset);
            string resetHash = controller.StableStateHash();
            bool resetHashMatches = initialHash == resetHash;

            bool passed = correctMappings == 24 && resetMappings == 6 &&
                          staleIgnored == 1 && duplicateIgnored == 1 &&
                          sideEffectsBeforeReset == 24 && missingRenderers == 0 &&
                          resetHashMatches;
            string status = passed ? "PASS" : "FAIL";
            Debug.Log(
                $"[S3_SUMMARY] {status} mappings={correctMappings}/24 " +
                $"stale_ignored={staleIgnored} duplicate_ignored={duplicateIgnored} " +
                $"side_effect_mappings={sideEffectsBeforeReset} " +
                $"missing_renderers={missingRenderers} " +
                $"reset_hash_match={resetHashMatches} reset_hash={resetHash}");

            controller.BeginSession("s3-final-visual");
            controller.ApplySnapshot(Success("s3-final-visual", 3));
        }

        private int ApplyAndCheck(PrototypeStateSnapshotPayload snapshot)
        {
            if (!controller.ApplySnapshot(snapshot))
            {
                return 0;
            }
            int matches = 0;
            foreach (PrototypeObjectState item in snapshot.object_states)
            {
                if (controller.HasState(item.object_id, item.state))
                {
                    matches += 1;
                }
            }
            return matches;
        }

        private static PrototypeStateSnapshotPayload Initial(string sessionId, int version)
        {
            return Snapshot(
                sessionId,
                version,
                "investigate_fault",
                "cargo_crate_c12",
                "none",
                false,
                false,
                "offline_e17",
                "stopped_fuse_slot_empty",
                "locked",
                "sealed_anomaly",
                "readable",
                "flashing_red");
        }

        private static PrototypeStateSnapshotPayload Acquired(string sessionId, int version)
        {
            return Snapshot(
                sessionId,
                version,
                "install_fuse",
                "mechanic_lia",
                "cooperation",
                false,
                false,
                "offline_e17",
                "stopped_fuse_slot_empty",
                "locked",
                "sealed_anomaly",
                "readable",
                "flashing_red");
        }

        private static PrototypeStateSnapshotPayload Installed(string sessionId, int version)
        {
            return Snapshot(
                sessionId,
                version,
                "restart_gate",
                "generator",
                "cooperation",
                false,
                false,
                "offline_e17",
                "standby_fuse_installed",
                "locked",
                "sealed_anomaly",
                "readable",
                "solid_amber");
        }

        private static PrototypeStateSnapshotPayload Success(string sessionId, int version)
        {
            return Snapshot(
                sessionId,
                version,
                "prototype_success",
                "generator",
                "cooperation",
                false,
                true,
                "online",
                "running",
                "restart_complete",
                "sealed_anomaly",
                "readable",
                "solid_green");
        }

        private static PrototypeStateSnapshotPayload Snapshot(
            string sessionId,
            int version,
            string objective,
            string fuseLocation,
            string route,
            bool crateAuthorized,
            bool cabinetAuthorized,
            params string[] states)
        {
            PrototypeObjectState[] objectStates = new PrototypeObjectState[ObjectIds.Length];
            for (int index = 0; index < ObjectIds.Length; index += 1)
            {
                objectStates[index] = new PrototypeObjectState
                {
                    object_id = ObjectIds[index],
                    state = states[index]
                };
            }
            return new PrototypeStateSnapshotPayload
            {
                session_id = sessionId,
                scene_id = "prototype_gate_repair",
                world_version = version,
                objective_state = objective,
                object_states = objectStates,
                item_locations = new[]
                {
                    new PrototypeItemLocation
                    {
                        item_id = "spare_fuse",
                        location_id = fuseLocation
                    }
                },
                route_flags = new PrototypeRouteFlags
                {
                    fuse_route = route,
                    crate_c12_authorized = crateAuthorized,
                    control_cabinet_authorized = cabinetAuthorized
                }
            };
        }
    }
}
