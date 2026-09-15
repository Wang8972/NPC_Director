using System;
using System.Collections;
using System.Linq;
using UnityEngine;

namespace LastLight
{
    public sealed partial class LastLightApp
    {
        void BeginPlan(string id)
        {
            if (!CanAct() || HasActiveTalk) return;
            if (view.execution != null && !string.IsNullOrEmpty(view.execution.id)) { ShowResumeExecution(view.execution); return; }
            Mutate("begin", new PlanIdRequest { plan_id = id, expected_revision = view.revision }, response =>
            {
                if (view.execution != null && !string.IsNullOrEmpty(view.execution.id)) ShowExecutionReview(view.execution, false);
                else { ToggleDrawer("plan", true); SetStatus("当前批次没有开始。请查看计划条件与人物反馈。", 10); }
            });
        }

        GameView executionBefore;
        ApiResponse committedResponse;
        bool executionCommitted;
        ExecutionView presentingExecution;
        public GameView AuthoritativeView => executionCommitted && committedResponse?.view != null ? committedResponse.view : view;

        void RunExecution(ExecutionView execution,bool skipAll=false)
        {
            if (execution == null || animating || completing || string.IsNullOrEmpty(execution.id)) return;
            CloseModal(); CancelTalk(); performancePlayer.StopAll("physical_action");
            executionBefore = view; presentingExecution = execution; committedResponse = null; executionCommitted = false;
            animating = true; skipAnimation = reducedMotion||skipAll; currentExecutionId = execution.id;
            world.SetInputBlocked(true); ToggleDrawer("plan", true); RefreshHud();
            SetStatus("正在接近目标并准备动作；结果尚未确认。", 60);
            executionRoutine = StartCoroutine(PrepareAndCommit(execution, sessionGeneration));
        }

        IEnumerator PrepareAndCommit(ExecutionView execution, int generation)
        {
            Exception failure = null;
            if (!completedAnimations.Contains(execution.id))
            {
                yield return PresentationRoutine.Run(world.Prepare(execution), () => generation != sessionGeneration,
                    error => failure = error, () => { if (skipAnimation) world.SkipAnimation(); });
                if (generation != sessionGeneration) yield break;
                if (failure != null)
                {
                    animating = false; executionRoutine = null; world.Apply(view);
                    ShowError("动作准备未完成：" + failure.Message); yield break;
                }
                completedAnimations.Add(execution.id);
            }
            if (generation != sessionGeneration) yield break;
            executionRoutine = null; FinishExecution(execution);
        }

        void SkipExecutionAnimation()
        {
            if (!animating || completing) return;
            skipAnimation = true; world.SkipAnimation();
        }

        void FinishExecution(ExecutionView execution)
        {
            if (completing || busy || executionCommitted) return;
            completing = true; busy = true; var generation = sessionGeneration;
            if (executionBefore == null) executionBefore = view;
            SetStatus("正在确认这批行动的实际结果…", 60);
            client.Post(SessionPath("complete"), new CompleteRequest { execution_id = execution.id, expected_revision = view.revision }, response =>
            {
                if (generation != sessionGeneration) return;
                completing = false;
                if (!response.ok || response.view == null)
                {
                    busy = animating = false;
                    if (response.view != null) ApplyView(response.view);
                    ShowCompletionRecovery(execution, response.error); RefreshInteractivity(); return;
                }
                executionCommitted = true; committedResponse = response; animating = true;
                SetStatus("结果已确认，正在完成交接与收尾。", 60);
                executionRoutine = StartCoroutine(PlayCommittedResult(execution, executionBefore, response, generation));
            });
        }

        IEnumerator PlayCommittedResult(ExecutionView execution, GameView before, ApiResponse response, int generation)
        {
            Exception failure = null;
            yield return PresentationRoutine.Run(world.Resolve(execution, before, response.view), () => generation != sessionGeneration,
                error => failure = error, () => { if (skipAnimation) world.SkipAnimation(); });
            if (generation != sessionGeneration) yield break;
            busy = completing = animating = false; executionRoutine = null; currentExecutionId = "";
            // Even if a cosmetic tail fails, committed facts cannot be rolled back or submitted again.
            ApplyView(response.view, true); world.PlayCue("resolve");
            executionBefore = null; committedResponse = null; executionCommitted = false; presentingExecution = null;
            if (response.job != null) AdoptJob(response.job);
            RefreshHud(); RefreshDrawer();
            if (failure != null) ShowError("结果已保存，但收尾演出中断：" + failure.Message);
            else SetStatus("行动结果已确认。先观察变化，再决定下一步。", 10);
            if (!string.IsNullOrEmpty(view.ending) && !HasActiveTalk) ShowEnding();
        }

        void ShowCompletionRecovery(ExecutionView execution, string error)
        {
            var column = OpenModal("行动结果尚未确认", 790, 530);
            UiFactory.FlowText(column, error ?? "没有收到服务的结算结果。", 25);
            UiFactory.FlowText(column, "先读取最新进度。若这批行动仍在等待结算，可以安全重试；已经完成的效果不会重复发生。", 24, UiFactory.Muted);
            UiFactory.Button("Refresh execution", column, "读取进度并继续", () =>
            {
                CloseModal(); RefreshProgress(() =>
                {
                    if (view.execution != null && view.execution.id == execution.id) FinishExecution(view.execution);
                    else SetStatus("已同步最新进度；这批行动不再等待结算。", 8);
                });
            }, true);
            UiFactory.Button("Leave pending", column, "稍后处理", CloseModal);
        }

        void ShowResumeExecution(ExecutionView execution)
        {
            ShowExecutionReview(execution, true);
        }

        void ShowExecutionReview(ExecutionView execution, bool resuming)
        {
            var column = OpenModal(resuming ? "继续尚未完成的行动" : "本批行动与成本", 800, 710);
            UiFactory.FlowText(column, resuming ? "当前进度中有一批已安排、尚未确认完成的行动。" : "参与者与资源已经安排。开始执行后，再统一确认实际结果。", 25);
            UiFactory.FlowText(column, "本批实际推进 · " + execution.duration + " 个行动时段",29,UiFactory.Amber);
            foreach (var step in execution.steps ?? Array.Empty<PlanStep>())
                UiFactory.FlowText(column, ActorName(step.actor_id) + " · " + ActionLabel(step.action_id), 25, UiFactory.Amber);
            UiFactory.FlowText(column, "继续将保留相同的规则成本与结果。取消时，已经完成的工作也会保留。", 23, UiFactory.Muted);
            UiFactory.Button("Resume animation", column, resuming ? "继续行动" : "开始执行本批", () => { CloseModal(); RunExecution(execution); }, true);
            UiFactory.Button("Skip resume", column, "略过演出并结算", () => { CloseModal(); RunExecution(execution,true); });
            UiFactory.Button("Cancel pending", column, "取消余下计划", () => { CloseModal(); CancelPlan(execution.plan_id); });
        }

        void ShowExecutionControls()
        {
            if (!animating) return;
            if(executionCommitted)
            {
                var settled=OpenModal("结果已经确认",720,400);
                UiFactory.FlowText(settled,"当前正在播放接住、插入或到达的收尾。可以略过演出，已经发生的结果会保留。",25);
                UiFactory.Button("Continue result",settled,"继续观看",CloseModal,true);
                UiFactory.Button("Skip result",settled,"略过收尾",()=>{SkipExecutionAnimation();CloseModal();});return;
            }
            if(view?.execution==null)return;
            if (completing)
            {
                var waiting = OpenModal("正在确认行动结果", 720, 350);
                UiFactory.FlowText(waiting, "服务正在确认结果。结果返回前不会再发送一次行动。",25);
                UiFactory.Button("Back",waiting,"返回现场",CloseModal,true); return;
            }
            var column = OpenModal("行动正在进行", 720, 470);
            UiFactory.FlowText(column, "正在准备动作。确认结果之前可以取消；略过演出不会改变成本。", 25);
            UiFactory.Button("Resume watching", column, "继续观看", CloseModal, true);
            UiFactory.Button("Skip watching", column, "略过演出", () => { SkipExecutionAnimation(); CloseModal(); });
            UiFactory.Button("Cancel watching", column, "中止未完成行动", () => { var id = view.execution.plan_id; CloseModal(); CancelPlan(id); });
        }

        void ConfirmCancelPlan(PlanView plan)
        {
            if (busy || completing) return;
            Confirm("取消余下计划", "尚未完成的动作将停止。已经完成的工作、物品交接、时间和电量消耗都会保留。", "取消余下行动", () => CancelPlan(plan.id));
        }
        void CancelPlan(string id)
        {
            if(executionCommitted){SkipExecutionAnimation();SetStatus("这一批结果已经确认，已略过剩余演出。",8);return;}
            if (busy || completing || view == null) return;
            // Compatibility with saves/views produced before execution.plan_id
            // was included: recover the only cancellable plan instead of
            // serializing a null plan_id (which FastAPI correctly rejects).
            if (string.IsNullOrEmpty(id) && view.execution != null)
            {
                var executing = (view.plans ?? Array.Empty<PlanView>()).FirstOrDefault(plan => plan.status == "executing");
                if (executing != null) id = executing.id;
            }
            if (string.IsNullOrEmpty(id))
            {
                var candidates = (view.plans ?? Array.Empty<PlanView>()).Where(plan =>
                    plan.status != "completed" && plan.status != "cancelled" && plan.status != "failed").ToArray();
                if (candidates.Length == 1) id = candidates[0].id;
            }
            if (string.IsNullOrEmpty(id)) { ShowError("无法确定要取消的计划，请刷新当前进度后重试。"); return; }
            if (executionRoutine != null) StopCoroutine(executionRoutine);
            world.SkipAnimation(); executionRoutine = null; animating = false; currentExecutionId = "";
            Mutate("cancel", new PlanIdRequest { plan_id = id, expected_revision = view.revision }, response =>
            {
                world.Apply(view); RefreshHud(); SetStatus("未完成的行动已取消。已完成工作保留。", 8);
            });
        }
    }
}
