using System;
using System.Collections.Generic;
using System.Security.Cryptography;
using System.Text;

namespace NPCDirector
{
    public sealed class PrototypeWorldState
    {
        public const string SceneId = "prototype_gate_repair";
        public const string InitialObjective = "investigate_fault";
        public const string SuccessObjective = "prototype_success";

        private readonly HashSet<string> playerFacts =
            new HashSet<string>(StringComparer.Ordinal);
        private readonly HashSet<string> finnFacts =
            new HashSet<string>(StringComparer.Ordinal);
        private readonly HashSet<string> liaFacts =
            new HashSet<string>(StringComparer.Ordinal);
        private readonly HashSet<string> marenFacts =
            new HashSet<string>(StringComparer.Ordinal);

        public string SessionId { get; private set; }
        public int WorldVersion { get; internal set; }
        public string ObjectiveState { get; internal set; }
        public string FuseLocation { get; internal set; }
        public string FuseRoute { get; internal set; }
        public bool CrateAuthorized { get; internal set; }
        public bool ControlCabinetAuthorized { get; internal set; }

        public bool IsSuccess => ObjectiveState == SuccessObjective;

        public PrototypeWorldState(string sessionId)
        {
            Reset(sessionId);
        }

        public void Reset(string sessionId)
        {
            SessionId = sessionId;
            WorldVersion = 0;
            ObjectiveState = InitialObjective;
            FuseLocation = "cargo_crate_c12";
            FuseRoute = "none";
            CrateAuthorized = false;
            ControlCabinetAuthorized = false;
            playerFacts.Clear();
            finnFacts.Clear();
            liaFacts.Clear();
            marenFacts.Clear();
            playerFacts.Add("fact_restart_requires_authority");
            finnFacts.Add("fact_fuse_moved_to_c12");
            finnFacts.Add("fact_crate_c12_contains_fuse");
            marenFacts.Add("fact_restart_requires_authority");
        }

        public bool PlayerKnows(string factId)
        {
            return playerFacts.Contains(factId);
        }

        public bool FinnKnows(string factId)
        {
            return finnFacts.Contains(factId);
        }

        public bool MarenKnows(string factId)
        {
            return marenFacts.Contains(factId);
        }

        internal bool AddPlayerFact(string factId)
        {
            return playerFacts.Add(factId);
        }

        internal bool AddFinnFact(string factId)
        {
            return finnFacts.Add(factId);
        }

        internal bool AddLiaFact(string factId)
        {
            return liaFacts.Add(factId);
        }

        internal bool AddMarenFact(string factId)
        {
            return marenFacts.Add(factId);
        }

        internal void CommitChange()
        {
            WorldVersion += 1;
        }

        public string[] SortedPlayerFacts()
        {
            string[] values = new string[playerFacts.Count];
            playerFacts.CopyTo(values);
            Array.Sort(values, StringComparer.Ordinal);
            return values;
        }

        public PrototypeStateSnapshotPayload ToSnapshot()
        {
            bool fuseInstalled = FuseLocation == "generator";
            string crateState = FuseLocation == "cargo_crate_c12"
                ? (CrateAuthorized ? "access_authorized" : "sealed_anomaly")
                : "opened_empty";
            string cabinetState = IsSuccess
                ? "restart_complete"
                : (ControlCabinetAuthorized ? "authorized" : "locked");

            return new PrototypeStateSnapshotPayload
            {
                session_id = SessionId,
                scene_id = SceneId,
                world_version = WorldVersion,
                objective_state = ObjectiveState,
                object_states = new[]
                {
                    new PrototypeObjectState
                    {
                        object_id = "gate_console",
                        state = IsSuccess ? "online" : "offline_e17"
                    },
                    new PrototypeObjectState
                    {
                        object_id = "generator",
                        state = IsSuccess
                            ? "running"
                            : (fuseInstalled ? "standby_fuse_installed" : "stopped_fuse_slot_empty")
                    },
                    new PrototypeObjectState
                    {
                        object_id = "control_cabinet",
                        state = cabinetState
                    },
                    new PrototypeObjectState
                    {
                        object_id = "cargo_crate_c12",
                        state = crateState
                    },
                    new PrototypeObjectState
                    {
                        object_id = "manifest_board",
                        state = "readable"
                    },
                    new PrototypeObjectState
                    {
                        object_id = "alarm_lamp",
                        state = IsSuccess
                            ? "solid_green"
                            : (fuseInstalled ? "solid_amber" : "flashing_red")
                    }
                },
                item_locations = new[]
                {
                    new PrototypeItemLocation
                    {
                        item_id = "spare_fuse",
                        location_id = FuseLocation
                    }
                },
                route_flags = new PrototypeRouteFlags
                {
                    fuse_route = FuseRoute,
                    crate_c12_authorized = CrateAuthorized,
                    control_cabinet_authorized = ControlCabinetAuthorized
                }
            };
        }

        public string StableStateHash()
        {
            StringBuilder canonical = new StringBuilder();
            canonical.Append(ObjectiveState).Append('|');
            canonical.Append(FuseLocation).Append('|');
            canonical.Append(FuseRoute).Append('|');
            canonical.Append(CrateAuthorized).Append('|');
            canonical.Append(ControlCabinetAuthorized).Append('|');
            foreach (string factId in SortedPlayerFacts())
            {
                canonical.Append(factId).Append('|');
            }
            AppendFacts(canonical, "finn", finnFacts);
            AppendFacts(canonical, "lia", liaFacts);
            AppendFacts(canonical, "maren", marenFacts);
            using (SHA256 sha = SHA256.Create())
            {
                byte[] digest = sha.ComputeHash(Encoding.UTF8.GetBytes(canonical.ToString()));
                return BitConverter.ToString(digest).Replace("-", "").ToLowerInvariant();
            }
        }

        private static void AppendFacts(
            StringBuilder canonical,
            string owner,
            HashSet<string> facts)
        {
            string[] values = new string[facts.Count];
            facts.CopyTo(values);
            Array.Sort(values, StringComparer.Ordinal);
            canonical.Append(owner).Append('=');
            foreach (string factId in values)
            {
                canonical.Append(factId).Append(',');
            }
            canonical.Append('|');
        }
    }
}
