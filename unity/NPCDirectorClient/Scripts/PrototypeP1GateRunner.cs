using UnityEngine;

namespace NPCDirector
{
    public sealed class PrototypeP1GateRunner : MonoBehaviour
    {
        [SerializeField] private PrototypeGameFlowController controller;

        public void Configure(PrototypeGameFlowController flowController)
        {
            controller = flowController;
        }

        [ContextMenu("Run P1 Automated Gate")]
        public void RunGate()
        {
            bool cooperationPassed = RunCooperationRoute();
            bool procedurePassed = RunProcedureRoute();

            PrototypeWorldState firstReset = new PrototypeWorldState("p1-reset-a");
            PrototypeWorldState secondReset = new PrototypeWorldState("p1-reset-b");
            bool resetHashMatches = firstReset.StableStateHash() == secondReset.StableStateHash();

            int npcCount = FindObjectsOfType<PrototypeNpcSelector>(true).Length;
            int hotspotCount = FindObjectsOfType<PrototypeHotspot>(true).Length;
            int backendClientCount = FindObjectsOfType<NPCDirectorClient>(true).Length;
            bool passed = cooperationPassed && procedurePassed && resetHashMatches &&
                          controller != null && npcCount == 3 && hotspotCount == 6 &&
                          backendClientCount == 0;
            string status = passed ? "PASS" : "FAIL";

            Debug.Log(
                $"[P1_SUMMARY] {status} cooperation={(cooperationPassed ? 1 : 0)} " +
                $"procedure={(procedurePassed ? 1 : 0)} " +
                $"reset_hash_match={resetHashMatches} npcs={npcCount} " +
                $"hotspots={hotspotCount} backend_clients={backendClientCount}");
        }

        private static bool RunCooperationRoute()
        {
            PrototypeWorldState state = new PrototypeWorldState("p1-gate-cooperation");
            bool passed = Apply(state, PrototypePuzzleRules.ObserveGateConsole, "") &&
                          Apply(state, PrototypePuzzleRules.InspectGenerator, PrototypePuzzleRules.LiaId) &&
                          Apply(state, PrototypePuzzleRules.TellDiagnosis, PrototypePuzzleRules.FinnId) &&
                          Apply(state, PrototypePuzzleRules.OfferCooperation, PrototypePuzzleRules.FinnId) &&
                          Apply(state, PrototypePuzzleRules.InstallFuse, PrototypePuzzleRules.LiaId) &&
                          Apply(state, PrototypePuzzleRules.AuthorizeRestart, PrototypePuzzleRules.MarenId) &&
                          Apply(state, PrototypePuzzleRules.RestartGate, PrototypePuzzleRules.MarenId) &&
                          state.IsSuccess && state.FuseRoute == "cooperation";
            Debug.Log(
                $"[P1_ROUTE] cooperation status={(passed ? "PASS" : "FAIL")} " +
                $"version={state.WorldVersion} hash={state.StableStateHash()}");
            return passed;
        }

        private static bool RunProcedureRoute()
        {
            PrototypeWorldState state = new PrototypeWorldState("p1-gate-procedure");
            bool passed = Apply(state, PrototypePuzzleRules.ObserveGateConsole, "") &&
                          Apply(state, PrototypePuzzleRules.InspectGenerator, PrototypePuzzleRules.LiaId) &&
                          Apply(state, PrototypePuzzleRules.ObserveManifest, "") &&
                          Apply(state, PrototypePuzzleRules.TellDiagnosis, PrototypePuzzleRules.MarenId) &&
                          Apply(state, PrototypePuzzleRules.TellManifest, PrototypePuzzleRules.MarenId) &&
                          Apply(state, PrototypePuzzleRules.RequestProcedure, PrototypePuzzleRules.MarenId) &&
                          Apply(state, PrototypePuzzleRules.GiveFuse, PrototypePuzzleRules.FinnId) &&
                          Apply(state, PrototypePuzzleRules.InstallFuse, PrototypePuzzleRules.LiaId) &&
                          Apply(state, PrototypePuzzleRules.AuthorizeRestart, PrototypePuzzleRules.MarenId) &&
                          Apply(state, PrototypePuzzleRules.RestartGate, PrototypePuzzleRules.MarenId) &&
                          state.IsSuccess && state.FuseRoute == "procedure";
            Debug.Log(
                $"[P1_ROUTE] procedure status={(passed ? "PASS" : "FAIL")} " +
                $"version={state.WorldVersion} hash={state.StableStateHash()}");
            return passed;
        }

        private static bool Apply(PrototypeWorldState state, string actionId, string actorId)
        {
            PrototypeActionResult result = PrototypePuzzleRules.Apply(state, actionId, actorId);
            if (!result.Accepted)
            {
                Debug.LogError(
                    $"[P1_GATE_ACTION_FAIL] action={actionId} actor={actorId} " +
                    $"code={result.Code} message={result.Message}");
            }
            return result.Accepted;
        }
    }
}
