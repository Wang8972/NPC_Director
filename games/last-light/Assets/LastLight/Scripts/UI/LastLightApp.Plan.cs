using System;
using System.Collections;
using System.Collections.Generic;
using System.Linq;
using UnityEngine;
using UnityEngine.UI;

namespace LastLight
{
    public sealed partial class LastLightApp
    {
        readonly List<PlanStep> draftSteps = new List<PlanStep>();
        string draftTitle = "救援协作方案";
        int stepSequence;

        void AddDraft(ActionView action)
        {
            if (draftSteps.Count >= 12) { ShowError("一份计划最多安排 12 个步骤。可以先完成这一批，再继续安排。"); return; }
            draftSteps.Add(new PlanStep
            {
                id = "s" + (++stepSequence), action_id = action.id,
                actor_id = string.IsNullOrEmpty(action.default_actor) ? "player" : action.default_actor,
                target_id = action.target_id, duration = action.duration, helpers = Array.Empty<string>(),
                depends_on = draftSteps.Count == 0 ? Array.Empty<string>() : new[] { draftSteps[draftSteps.Count - 1].id }
            });
            ToggleDrawer("plan", true);
            SetStatus("已加入草案。可修改分工与前后依赖，再检查条件与成本。", 8);
        }

        void RenderPlans()
        {
            drawerTitle.text = "协作计划";
            UiFactory.FlowText(drawerContent, "交谈达成意愿，计划安排动作。实际完成行动后，设备与物品状态才会改变。", 23, UiFactory.Muted);
            if (view.execution != null)
            {
                var pending = view.execution;
                UiFactory.FlowText(drawerContent,(animating ? "正在执行" : "等待你开始") + " · 本批 " + pending.duration + " 时段",26,UiFactory.Amber);
                if (animating) UiFactory.Button("Skip current batch",drawerContent,"略过演出，保留相同结果",SkipExecutionAnimation);
                else
                {
                    var resume = UiFactory.Button("Resume current batch",drawerContent,"查看并继续本批行动",()=>ShowResumeExecution(pending),true);
                    resume.interactable = !busy && !HasActiveTalk;
                }
                var cancel = UiFactory.Button("Cancel current batch",drawerContent,"取消尚未完成的安排",()=>
                    Confirm("取消余下计划","尚未完成的动作将停止，已经完成的工作和消耗会保留。","取消余下行动",()=>CancelPlan(pending.plan_id)));
                cancel.interactable = !busy && !completing && !HasActiveTalk;
                Divider(drawerContent);
            }
            if (suggestedSteps.Length > 0)
            {
                UiFactory.FlowText(drawerContent, "人物建议 · " + suggestedTitle, 25, UiFactory.Amber);
                foreach (var step in suggestedSteps)
                    UiFactory.FlowText(drawerContent, ActorName(step.actor_id) + " → " + ActionLabel(step.action_id), 23);
                var use = UiFactory.Button("Use suggestion", drawerContent, "载入草案，继续修改", LoadSuggestedPlan, true);
                use.interactable = !HasActiveTalk && CanAct(); Divider(drawerContent);
            }
            if (draftSteps.Count > 0)
            {
                UiFactory.FlowText(drawerContent, "尚未执行的草案", 21, UiFactory.Amber);
                var title = UiFactory.Input("Draft title", drawerContent, "方案名称", 52);
                title.text = draftTitle; title.characterLimit = 80; title.onValueChanged.AddListener(value => draftTitle = value);
                for (int i = 0; i < draftSteps.Count; i++)
                {
                    var step = draftSteps[i]; var index = i;
                    UiFactory.FlowText(drawerContent, (i + 1) + ". " + ActionLabel(step.action_id), 25);
                    UiFactory.FlowText(drawerContent, "负责 · " + ActorName(step.actor_id) + "\n协助 · " + JoinActors(step.helpers) + "\n开始条件 · " + DependencyDescription(step), 22, UiFactory.Muted);
                    var row = UiFactory.Row("Edit draft", drawerContent, 9, 42);
                    UiFactory.Button("Edit step", row, "分工 / 依赖", () => EditStep(index), false, 42);
                    UiFactory.Button("Delete step", row, "移除", () => RemoveDraftStep(index), false, 42);
                }
                UiFactory.FlowText(drawerContent, "没有依赖的步骤可并行。相同人物、物品与通道冲突会由规则检查。", 22, UiFactory.Muted);
                var submit = UiFactory.Button("Validate draft", drawerContent, "检查条件与行动成本", ProposeDraft, true, 55);
                submit.interactable = CanAct() && !HasActiveTalk;
                UiFactory.Button("Add more", drawerContent, "添加其他行动", ShowActionPicker);
                UiFactory.Button("Clear draft", drawerContent, "清空草案", () => { draftSteps.Clear(); RefreshDrawer(); });
                Divider(drawerContent);
            }
            else
            {
                UiFactory.FlowText(drawerContent, "还没有行动草案。选择场景中的物件，或从行动列表开始。也可以向人物描述你的方案。", 24);
                UiFactory.Button("Browse actions", drawerContent, "查看已知行动", ShowActionPicker, true);
            }
            foreach (var plan in view.plans.Reverse().Take(8))
            {
                var captured = plan;
                UiFactory.FlowText(drawerContent, plan.title + "  ·  " + PlanStatus(plan.status), 25, plan.status == "completed" ? UiFactory.Blue : UiFactory.Amber);
                UiFactory.FlowText(drawerContent, plan.summary, 23, UiFactory.Muted);
                foreach (var step in plan.steps ?? Array.Empty<PlanStep>())
                    UiFactory.FlowText(drawerContent, StepStatus(step.status) + "  " + ActorName(step.actor_id) + " · " + ActionLabel(step.action_id) + (string.IsNullOrEmpty(step.reason) ? "" : "\n" + step.reason), 22);
                foreach (var condition in plan.conditions ?? Array.Empty<string>())
                    UiFactory.FlowText(drawerContent, "尚需 · " + condition, 22, UiFactory.Amber);
                if (plan.status != "completed" && plan.status != "cancelled" && plan.status != "failed")
                {
                    if (animating && view.execution != null && view.execution.plan_id == plan.id)
                    {
                        UiFactory.Button("Skip animation", drawerContent, "略过演出，保留相同结果", SkipExecutionAnimation);
                        UiFactory.Button("Stop current", drawerContent, "中止未完成的行动", () => ConfirmCancelPlan(captured));
                    }
                    else if (view.execution != null && view.execution.plan_id == plan.id)
                    {
                        var pending = view.execution;
                        var resume = UiFactory.Button("Resume pending",drawerContent,"继续尚未完成的行动",()=>ShowResumeExecution(pending),true);
                        resume.interactable = !busy && !HasActiveTalk;
                        var cancel = UiFactory.Button("Cancel pending",drawerContent,"取消余下计划",()=>ConfirmCancelPlan(captured));
                        cancel.interactable = !busy && !HasActiveTalk;
                    }
                    else
                    {
                        var begin = UiFactory.Button("Review plan", drawerContent, "查看并确认行动", () => ShowPlanReview(captured), true);
                        begin.interactable = CanAct() && !HasActiveTalk;
                        var cancel = UiFactory.Button("Cancel plan", drawerContent, "取消余下计划", () => ConfirmCancelPlan(captured));
                        cancel.interactable = !busy && !HasActiveTalk;
                    }
                }
                if (plan.status != "executing")
                    UiFactory.Button("Copy plan", drawerContent, "复制到草案", () => CopyPlan(captured));
                Divider(drawerContent);
            }
        }

        string JoinActors(string[] ids) => ids == null || ids.Length == 0 ? "无" : string.Join("、", ids.Select(ActorName));
        string DependencyDescription(PlanStep step)
        {
            if (step.depends_on == null || step.depends_on.Length == 0) return "可独立开始";
            return string.Join("、", step.depends_on.Select(id => { var i = draftSteps.FindIndex(s => s.id == id); return i >= 0 ? "步骤 " + (i + 1) + " 完成" : "缺失步骤 " + id; }));
        }
        void RemoveDraftStep(int index)
        {
            if (index < 0 || index >= draftSteps.Count) return;
            var id = draftSteps[index].id; draftSteps.RemoveAt(index);
            foreach (var step in draftSteps) step.depends_on = (step.depends_on ?? Array.Empty<string>()).Where(d => d != id).ToArray();
            RefreshDrawer();
        }

        void EditStep(int index)
        {
            if (index < 0 || index >= draftSteps.Count) return;
            var step = draftSteps[index]; var action = view.actions.FirstOrDefault(a => a.id == step.action_id);
            var column = OpenModal("步骤 " + (index + 1) + " · " + ActionLabel(step.action_id), 780, 870);
            UiFactory.FlowText(column, action?.description ?? "安排执行者、协助者与前置步骤。", 24, UiFactory.Muted);
            UiFactory.FlowText(column, "执行者", 24, UiFactory.Amber);
            var candidates = action?.actor_ids ?? Array.Empty<string>();
            if (candidates.Length == 0) candidates = new[] { string.IsNullOrEmpty(step.actor_id) ? "player" : step.actor_id };
            var actorRow = UiFactory.Row("Actors", column, 9, 48);
            foreach (var candidate in candidates.Distinct())
            {
                var id = candidate;
                UiFactory.Button("Actor " + id, actorRow, ActorName(id), () =>
                { step.actor_id = id; step.helpers = (step.helpers ?? Array.Empty<string>()).Where(h => h != id).ToArray(); CloseModal(); EditStep(index); }, step.actor_id == id, 48);
            }
            UiFactory.FlowText(column, "协助者", 24, UiFactory.Amber);
            var helpers = new HashSet<string>(step.helpers ?? Array.Empty<string>());
            foreach (var actor in view.actors.Where(a => (a.id == "player" || IsNpc(a.id)) && a.id != step.actor_id))
            {
                var id = actor.id;
                UiFactory.Toggle(column, actor.name, helpers.Contains(id), enabled => { if (enabled) helpers.Add(id); else helpers.Remove(id); step.helpers = helpers.ToArray(); });
            }
            UiFactory.FlowText(column, "必须先完成的步骤", 24, UiFactory.Amber);
            UiFactory.FlowText(column, "不勾选表示可独立开始。规则会检查循环与资源冲突。", 22, UiFactory.Muted);
            var dependencies = new HashSet<string>(step.depends_on ?? Array.Empty<string>());
            for (int i = 0; i < draftSteps.Count; i++)
            {
                if (i == index) continue;
                var other = draftSteps[i]; var id = other.id;
                UiFactory.Toggle(column, (i + 1) + ". " + ActionLabel(other.action_id), dependencies.Contains(id), enabled => { if (enabled) dependencies.Add(id); else dependencies.Remove(id); step.depends_on = dependencies.ToArray(); });
            }
            UiFactory.Button("Done editing", column, "完成编辑", () => { CloseModal(); RefreshDrawer(); }, true);
        }

        void ShowActionPicker()
        {
            if (view == null) return;
            var column = OpenModal("已知的行动", 850, 880);
            UiFactory.FlowText(column, "将多项行动组合后再检查完整条件。未满足的条件会明确列出。", 24, UiFactory.Muted);
            foreach (var action in view.actions)
            {
                if (action.kind == "talk" || (action.kind == "inspect" && action.duration == 0)) continue;
                var captured = action;
                UiFactory.FlowText(column, action.label + "  ·  " + action.duration + " 时段", 26);
                UiFactory.FlowText(column, action.description + (action.enabled ? "" : "\n目前尚需 · " + action.blocked_reason), 23, action.enabled ? UiFactory.Muted : UiFactory.Amber);
                var button = UiFactory.Button("Pick " + action.id, column, "加入草案", () => { AddDraft(captured); CloseModal(); }, action.enabled);
                button.interactable = CanAct() && !HasActiveTalk; Divider(column);
            }
            if (view.actions.Length == 0) UiFactory.FlowText(column, "还没有可安排的行动。请先调查附近场景。", 25);
        }
        void CopyPlan(PlanView plan)
        { draftTitle = (plan.title ?? "救援方案") + " · 调整"; LoadDraftSteps(plan.steps); ToggleDrawer("plan", true); }
        void LoadSuggestedPlan()
        { draftTitle = string.IsNullOrEmpty(suggestedTitle) ? "共同拟定的救援方案" : suggestedTitle; LoadDraftSteps(suggestedSteps); suggestedSteps = Array.Empty<PlanStep>(); RefreshDrawer(); }
        void LoadDraftSteps(PlanStep[] source)
        {
            draftSteps.Clear(); stepSequence = 0; var ids = new Dictionary<string, string>();
            foreach (var original in source ?? Array.Empty<PlanStep>())
            {
                var nextId = "s" + (++stepSequence);
                if (!string.IsNullOrEmpty(original.id)) ids[original.id] = nextId;
                draftSteps.Add(new PlanStep { id = nextId, action_id = original.action_id, actor_id = original.actor_id, target_id = original.target_id, duration = original.duration, helpers = (original.helpers ?? Array.Empty<string>()).ToArray(), depends_on = (original.depends_on ?? Array.Empty<string>()).ToArray() });
            }
            foreach (var step in draftSteps) step.depends_on = step.depends_on.Select(id => ids.TryGetValue(id, out var mapped) ? mapped : id).ToArray();
        }
        void ProposeDraft()
        {
            if (!CanAct() || HasActiveTalk || draftSteps.Count == 0) return;
            var error = ValidateDraftGraph();
            if (!string.IsNullOrEmpty(error)) { ShowError(error); return; }
            var submittedIds = new HashSet<string>(view.plans.Select(p => p.id));
            var wireSteps = draftSteps.Select(step => new PlanStepRequest
            {
                id = step.id ?? "", action_id = step.action_id ?? "", actor_id = step.actor_id ?? "",
                target_id = step.target_id ?? "",
                helpers = step.helpers ?? Array.Empty<string>(), depends_on = step.depends_on ?? Array.Empty<string>()
            }).ToArray();
            Mutate("plan", new PlanRequest { title = string.IsNullOrWhiteSpace(draftTitle) ? "救援协作方案" : draftTitle.Trim(), steps = wireSteps, expected_revision = view.revision }, response =>
            {
                var created = view.plans.LastOrDefault(p => !submittedIds.Contains(p.id)) ?? view.plans.LastOrDefault();
                if (created != null) ShowPlanReview(created); else SetStatus("方案已检查。请查看计划条件。", 8);
            });
        }
        string ValidateDraftGraph()
        {
            var ids = new HashSet<string>();
            foreach (var step in draftSteps)
            {
                if (string.IsNullOrEmpty(step.id) || !ids.Add(step.id)) return "步骤编号重复或缺失，请重新加入该项行动。";
                if (string.IsNullOrEmpty(step.action_id) || string.IsNullOrEmpty(step.actor_id)) return "每项行动都需要动作和执行者。";
            }
            foreach (var step in draftSteps)
                foreach (var dependency in step.depends_on ?? Array.Empty<string>())
                    if (!ids.Contains(dependency)) return "方案依赖一个已移除的步骤，请修改依赖关系。";
            var completed = new HashSet<string>();
            for (int pass = 0; pass < draftSteps.Count; pass++)
                foreach (var step in draftSteps)
                    if ((step.depends_on ?? Array.Empty<string>()).All(completed.Contains)) completed.Add(step.id);
            return completed.Count == draftSteps.Count ? null : "步骤之间形成了循环依赖。至少一项行动需要能够先开始。";
        }
        void ShowPlanReview(PlanView plan)
        {
            if (plan == null) return;
            var column = OpenModal(plan.title, 850, 830);
            UiFactory.FlowText(column, plan.summary, 25);
            UiFactory.FlowText(column, "规则预计 · " + plan.total_ticks + " 个行动时段", 29, UiFactory.Amber);
            UiFactory.FlowText(column, "执行推进环境与设备消耗；并行步骤按共同事件边界结算。阅读和交谈不推进危险。", 23, UiFactory.Muted);
            foreach (var step in plan.steps ?? Array.Empty<PlanStep>())
            {
                UiFactory.FlowText(column, ActorName(step.actor_id) + " → " + ActionLabel(step.action_id), 25);
                UiFactory.FlowText(column, "协助 · " + JoinActors(step.helpers) + "   /   " + step.duration + " 时段" + (string.IsNullOrEmpty(step.reason) ? "" : "\n" + step.reason), 22, UiFactory.Muted);
            }
            foreach (var condition in plan.conditions ?? Array.Empty<string>()) UiFactory.FlowText(column, "条件 · " + condition, 23, UiFactory.Amber);
            var begin = UiFactory.Button("Begin plan", column, "检查并安排下一批", () => { CloseModal(); BeginPlan(plan.id); }, true, 56);
            begin.interactable = CanAct() && !HasActiveTalk && plan.status != "failed" && plan.status != "cancelled" && plan.status != "completed";
            UiFactory.Button("Edit review", column, "返回修改分工", () => { CloseModal(); CopyPlan(plan); });
        }
        static string PlanStatus(string status)
        {
            switch (status) { case "proposed": return "已提议"; case "accepted": return "可执行"; case "waiting": return "等待条件"; case "executing": return "执行中"; case "completed": return "已完成"; case "failed": return "无法执行"; case "cancelled": return "已取消"; default: return status; }
        }
        static string StepStatus(string status)
        {
            switch (status) { case "completed": return "✓"; case "executing": return "进行中"; case "failed": return "受阻"; case "cancelled": return "已取消"; case "waiting": return "等待"; default: return "待办"; }
        }
    }
}
