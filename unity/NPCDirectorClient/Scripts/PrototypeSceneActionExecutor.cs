using System;
using System.Collections;
using System.Collections.Generic;
using UnityEngine;

namespace NPCDirector
{
    public sealed class PrototypeSceneActionExecutor : MonoBehaviour
    {
        private static readonly HashSet<string> AllowedActionTypes =
            new HashSet<string>(StringComparer.Ordinal)
            {
                "inspect_object",
                "authorize_object",
                "give_item",
                "install_item",
                "operate_object",
                "tell_npc",
                "tell_player"
            };

        [SerializeField] private string sessionId = "p2-fake-001";
        [SerializeField] private NpcRegistry npcRegistry;
        [SerializeField] private float objectActionSeconds = 2f;

        private readonly HashSet<string> completedKeys =
            new HashSet<string>(StringComparer.Ordinal);
        private Coroutine activeRoutine;
        private PerformanceExecutor activeActor;
        private SceneActionPlanPayload activePlan;
        private Action<string, SceneActionPlanPayload, string> activeReporter;
        private string actorTerminal;

        public bool IsBusy => activeRoutine != null;

        public void Configure(string configuredSessionId, NpcRegistry registry)
        {
            sessionId = configuredSessionId;
            npcRegistry = registry;
        }

        public bool TryExecute(
            SceneActionPlanPayload plan,
            Action<string, SceneActionPlanPayload, string> report)
        {
            string validationError = Validate(plan);
            if (validationError != null)
            {
                report?.Invoke("error", plan, validationError);
                return false;
            }
            if (completedKeys.Contains(plan.idempotency_key))
            {
                report?.Invoke("ack", plan, "duplicate");
                report?.Invoke("completed", plan, "duplicate");
                return true;
            }
            if (activeRoutine != null && activePlan.idempotency_key == plan.idempotency_key)
            {
                report?.Invoke("ack", plan, "duplicate_in_flight");
                report?.Invoke("started", plan, "duplicate_in_flight");
                return true;
            }
            if (activeRoutine != null)
            {
                report?.Invoke("error", plan, "another scene action is active");
                return false;
            }
            if (!npcRegistry.TryResolve(plan.action.actor_id, out activeActor))
            {
                report?.Invoke("error", plan, $"unknown actor_id: {plan.action.actor_id}");
                return false;
            }

            activePlan = plan;
            activeReporter = report;
            actorTerminal = null;
            report?.Invoke("ack", plan, null);
            activeRoutine = StartCoroutine(ExecuteRoutine());
            return true;
        }

        public void InterruptCurrent(string reason)
        {
            if (activeRoutine == null)
            {
                return;
            }
            StopCoroutine(activeRoutine);
            activeActor?.InterruptCurrent(reason);
            activeReporter?.Invoke("interrupted", activePlan, reason);
            ClearActive();
        }

        private IEnumerator ExecuteRoutine()
        {
            PerformancePlanPayload actorPlan = new PerformancePlanPayload
            {
                directive = activePlan.pre_commit_directive,
                idempotency_key = activePlan.idempotency_key
            };
            bool actorAccepted = activeActor.TryExecute(actorPlan, HandleActorEvent);
            if (!actorAccepted)
            {
                activeReporter?.Invoke("error", activePlan, "actor performance rejected locally");
                ClearActive();
                yield break;
            }

            activeReporter?.Invoke("started", activePlan, null);
            Transform objectTransform = ResolveObjectTransform(activePlan.action);
            Vector3 initialPosition = objectTransform != null
                ? objectTransform.localPosition
                : Vector3.zero;
            float elapsed = 0f;
            while (elapsed < objectActionSeconds || actorTerminal == null)
            {
                elapsed += Time.deltaTime;
                if (objectTransform != null)
                {
                    float phase = Mathf.Clamp01(elapsed / objectActionSeconds);
                    objectTransform.localPosition = initialPosition +
                        Vector3.up * (Mathf.Sin(phase * Mathf.PI) * 0.08f);
                }
                if (actorTerminal == "interrupted" || actorTerminal == "error")
                {
                    if (objectTransform != null)
                    {
                        objectTransform.localPosition = initialPosition;
                    }
                    activeReporter?.Invoke(actorTerminal, activePlan, "actor performance failed");
                    ClearActive();
                    yield break;
                }
                yield return null;
            }

            if (objectTransform != null)
            {
                objectTransform.localPosition = initialPosition;
            }
            completedKeys.Add(activePlan.idempotency_key);
            activeReporter?.Invoke("completed", activePlan, null);
            ClearActive();
        }

        private void HandleActorEvent(
            string eventType,
            string turnId,
            string idempotencyKey,
            string detail)
        {
            if (activePlan == null || activePlan.action.turn_id != turnId ||
                activePlan.idempotency_key != idempotencyKey)
            {
                return;
            }
            if (eventType == "completed" || eventType == "interrupted" || eventType == "error")
            {
                actorTerminal = eventType;
            }
        }

        private string Validate(SceneActionPlanPayload plan)
        {
            if (plan == null || plan.action == null || plan.pre_commit_directive == null ||
                string.IsNullOrWhiteSpace(plan.idempotency_key))
            {
                return "missing scene action fields";
            }
            if (plan.action.schema_version != "1.0" || plan.action.session_id != sessionId ||
                plan.pre_commit_directive.session_id != sessionId ||
                plan.pre_commit_directive.npc_id != plan.action.actor_id)
            {
                return "scene action identity or schema mismatch";
            }
            if (!AllowedActionTypes.Contains(plan.action.action_type))
            {
                return $"unknown action_type: {plan.action.action_type}";
            }
            string requiredObject = ObjectForAction(plan.action);
            if (!string.IsNullOrWhiteSpace(requiredObject) && GameObject.Find(requiredObject) == null)
            {
                return $"unknown object_id: {requiredObject}";
            }
            return null;
        }

        private static Transform ResolveObjectTransform(SceneActionCommand action)
        {
            string objectId = ObjectForAction(action);
            GameObject target = string.IsNullOrWhiteSpace(objectId)
                ? null
                : GameObject.Find(objectId);
            return target != null ? target.transform : null;
        }

        private static string ObjectForAction(SceneActionCommand action)
        {
            if (!string.IsNullOrWhiteSpace(action.object_id))
            {
                return action.object_id;
            }
            return action.action_type == "give_item" ? "cargo_crate_c12" : null;
        }

        private void ClearActive()
        {
            activeRoutine = null;
            activeActor = null;
            activePlan = null;
            activeReporter = null;
            actorTerminal = null;
        }
    }
}
