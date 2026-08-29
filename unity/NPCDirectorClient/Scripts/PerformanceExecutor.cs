using System;
using System.Collections;
using System.Collections.Generic;
using UnityEngine;
using UnityEngine.UI;

namespace NPCDirector
{
    public interface INpcTtsPlayer
    {
        void Speak(string text, string voiceStyle);
        void Stop();
    }

    public sealed class PerformanceExecutor : MonoBehaviour
    {
        [SerializeField] private Animator animator;
        [SerializeField] private Text subtitle;
        [SerializeField] private ActionCatalog actionCatalog;
        [SerializeField] private FacialPresetController facialController;
        [SerializeField] private GazeController gazeController;
        [SerializeField] private MonoBehaviour ttsComponent;

        private readonly HashSet<string> completedKeys = new HashSet<string>(StringComparer.Ordinal);
        private readonly Queue<string> completedOrder = new Queue<string>();
        private const int MaxRememberedKeys = 256;
        private const string CompletedKeysPreference = "NPCDirector.CompletedKeys";
        private Coroutine activeRoutine;
        private int activePriority;
        private string activeInterruptPolicy;
        private string activeKey;
        private string activeTurnId;
        private Action<string, string, string, string> activeReporter;

        private INpcTtsPlayer TtsPlayer => ttsComponent as INpcTtsPlayer;

        public void Configure(
            Text subtitleText,
            ActionCatalog catalog,
            FacialPresetController faceController,
            GazeController gaze = null,
            Animator targetAnimator = null)
        {
            subtitle = subtitleText;
            actionCatalog = catalog;
            facialController = faceController;
            gazeController = gaze;
            animator = targetAnimator;
        }

        private void Awake()
        {
            string persisted = PlayerPrefs.GetString(CompletedKeysPreference, "");
            foreach (string key in persisted.Split(new[] { ';' }, StringSplitOptions.RemoveEmptyEntries))
            {
                if (completedKeys.Add(key))
                {
                    completedOrder.Enqueue(key);
                }
            }
        }

        public bool TryExecute(
            PerformancePlanPayload plan,
            Action<string, string, string, string> report)
        {
            if (plan == null || plan.directive == null || string.IsNullOrWhiteSpace(plan.idempotency_key))
            {
                return false;
            }
            if (!ValidateDirective(plan.directive))
            {
                return false;
            }
            if (completedKeys.Contains(plan.idempotency_key))
            {
                report?.Invoke("ack", plan.directive.turn_id, plan.idempotency_key, "duplicate");
                report?.Invoke("completed", plan.directive.turn_id, plan.idempotency_key, "duplicate");
                return true;
            }
            if (activeRoutine != null && activeKey == plan.idempotency_key)
            {
                report?.Invoke("ack", activeTurnId, activeKey, "duplicate_in_flight");
                report?.Invoke("started", activeTurnId, activeKey, "duplicate_in_flight");
                return true;
            }

            int incomingPriority = HighestPriority(plan.directive.body_cues);
            if (activeRoutine != null && !CanInterrupt(activeInterruptPolicy, incomingPriority))
            {
                return false;
            }
            if (activeRoutine != null)
            {
                InterruptCurrent("higher_priority_plan");
            }

            activeKey = plan.idempotency_key;
            activeTurnId = plan.directive.turn_id;
            activePriority = incomingPriority;
            activeInterruptPolicy = plan.directive.interrupt_policy;
            activeReporter = report;
            report?.Invoke("ack", activeTurnId, activeKey, null);
            activeRoutine = StartCoroutine(ExecuteRoutine(plan.directive));
            return true;
        }

        public void InterruptCurrent(string reason)
        {
            if (activeRoutine == null)
            {
                return;
            }
            StopCoroutine(activeRoutine);
            TtsPlayer?.Stop();
            activeReporter?.Invoke("interrupted", activeTurnId, activeKey, reason);
            ClearActive();
        }

        private IEnumerator ExecuteRoutine(PerformanceDirective directive)
        {
            activeReporter?.Invoke("started", activeTurnId, activeKey, null);
            if (subtitle != null)
            {
                subtitle.text = directive.dialogue != null ? directive.dialogue.text : "";
            }
            if (directive.dialogue != null)
            {
                TtsPlayer?.Speak(directive.dialogue.text, directive.dialogue.voice_style);
            }
            gazeController?.Apply(directive.gaze);

            int elapsed = 0;
            int bodyIndex = 0;
            int faceIndex = 0;
            while (bodyIndex < directive.body_cues.Length || faceIndex < directive.face_cues.Length)
            {
                while (bodyIndex < directive.body_cues.Length &&
                       directive.body_cues[bodyIndex].start_ms <= elapsed)
                {
                    PlayBodyCue(directive.body_cues[bodyIndex++]);
                }
                while (faceIndex < directive.face_cues.Length &&
                       directive.face_cues[faceIndex].start_ms <= elapsed)
                {
                    FaceCue cue = directive.face_cues[faceIndex++];
                    facialController?.Apply(cue.preset, cue.intensity);
                }
                yield return null;
                elapsed += Mathf.RoundToInt(Time.deltaTime * 1000f);
            }

            yield return new WaitForSeconds(0.2f);
            RememberCompleted(activeKey);
            activeReporter?.Invoke("completed", activeTurnId, activeKey, null);
            ClearActive();
        }

        private void PlayBodyCue(BodyCue cue)
        {
            if (animator == null || actionCatalog == null ||
                !actionCatalog.TryGet(cue.action, out ActionCatalogEntry entry))
            {
                return;
            }
            int layer = Mathf.Clamp(entry.layer, 0, animator.layerCount - 1);
            animator.CrossFade(entry.animatorState, 0.15f, layer);
        }

        private bool ValidateDirective(PerformanceDirective directive)
        {
            if (actionCatalog == null || facialController == null)
            {
                return false;
            }
            foreach (BodyCue cue in directive.body_cues ?? Array.Empty<BodyCue>())
            {
                if (!actionCatalog.TryGet(cue.action, out _))
                {
                    return false;
                }
            }
            foreach (FaceCue cue in directive.face_cues ?? Array.Empty<FaceCue>())
            {
                if (!facialController.Contains(cue.preset))
                {
                    return false;
                }
            }
            return true;
        }

        private bool CanInterrupt(string policy, int incomingPriority)
        {
            if (policy == "allow_any")
            {
                return true;
            }
            return policy == "allow_higher_priority" && incomingPriority > activePriority;
        }

        private static int HighestPriority(BodyCue[] cues)
        {
            int priority = 0;
            foreach (BodyCue cue in cues ?? Array.Empty<BodyCue>())
            {
                priority = Mathf.Max(priority, cue.priority);
            }
            return priority;
        }

        private void ClearActive()
        {
            activeRoutine = null;
            activePriority = 0;
            activeInterruptPolicy = null;
            activeKey = null;
            activeTurnId = null;
            activeReporter = null;
        }

        private void RememberCompleted(string key)
        {
            if (!completedKeys.Add(key))
            {
                return;
            }
            completedOrder.Enqueue(key);
            while (completedOrder.Count > MaxRememberedKeys)
            {
                completedKeys.Remove(completedOrder.Dequeue());
            }
            PlayerPrefs.SetString(CompletedKeysPreference, string.Join(";", completedOrder));
            PlayerPrefs.Save();
        }
    }
}
