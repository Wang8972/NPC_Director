using System;

namespace NPCDirector
{
    public sealed class PrototypeActionResult
    {
        public bool Accepted { get; private set; }
        public bool Changed { get; private set; }
        public string Code { get; private set; }
        public string Message { get; private set; }

        public static PrototypeActionResult Success(string code, string message, bool changed)
        {
            return new PrototypeActionResult
            {
                Accepted = true,
                Changed = changed,
                Code = code,
                Message = message
            };
        }

        public static PrototypeActionResult Reject(string code, string message)
        {
            return new PrototypeActionResult
            {
                Accepted = false,
                Changed = false,
                Code = code,
                Message = message
            };
        }
    }

    public static class PrototypePuzzleRules
    {
        public const string MarenId = "guard_captain_maren";
        public const string LiaId = "mechanic_lia";
        public const string FinnId = "porter_finn";

        public const string ObserveGateConsole = "observe_gate_console";
        public const string ObserveManifest = "observe_manifest_board";
        public const string ObserveCrate = "observe_cargo_crate_c12";
        public const string ObserveAlarm = "observe_alarm_lamp";
        public const string InspectGenerator = "inspect_generator";
        public const string TellDiagnosis = "tell_diagnosis";
        public const string TellManifest = "tell_manifest";
        public const string OfferCooperation = "offer_cooperation";
        public const string RequestProcedure = "request_procedure";
        public const string GiveFuse = "give_fuse";
        public const string InstallFuse = "install_fuse";
        public const string AuthorizeRestart = "authorize_restart";
        public const string RestartGate = "restart_gate";

        private const string FactConsoleE17 = "fact_console_e17";
        private const string FactMissingFuse = "fact_generator_missing_fuse";
        private const string FactManifestMovedC12 = "fact_manifest_finn_moved_c12";
        private const string FactCrateSealAnomaly = "fact_crate_c12_seal_anomaly";
        private const string FactCrateContainsFuse = "fact_crate_c12_contains_fuse";
        private const string FactFuseMovedToC12 = "fact_fuse_moved_to_c12";
        private const string FactFuseInstalled = "fact_fuse_installed";
        private const string FactGateRestarted = "fact_gate_restarted";

        public static bool IsCanonicalNpc(string npcId)
        {
            return npcId == MarenId || npcId == LiaId || npcId == FinnId;
        }

        public static PrototypeActionResult Apply(
            PrototypeWorldState state,
            string actionId,
            string selectedNpcId)
        {
            if (state == null)
            {
                return PrototypeActionResult.Reject("error_no_state", "本地状态尚未初始化。");
            }
            if (string.IsNullOrWhiteSpace(actionId))
            {
                return PrototypeActionResult.Reject("error_unknown_action", "没有指定操作。");
            }
            if (state.IsSuccess && actionId != ObserveAlarm)
            {
                return PrototypeActionResult.Reject(
                    "error_terminal_state",
                    "原型已经成功；请查看结果或点击重置。");
            }

            switch (actionId)
            {
                case ObserveGateConsole:
                    return ObserveGate(state);
                case ObserveManifest:
                    return DiscoverPlayerFact(
                        state,
                        FactManifestMovedC12,
                        "观察到搬运记录：费恩移动过 C-12，但这不能证明箱内装着什么。");
                case ObserveCrate:
                    return DiscoverPlayerFact(
                        state,
                        FactCrateSealAnomaly,
                        "C-12 的封条异常；仅凭封条不能推断保险丝位置。");
                case ObserveAlarm:
                    return PrototypeActionResult.Success(
                        "observed",
                        state.IsSuccess ? "警示灯已转为绿色常亮。" : "警示灯提示闸门供电异常。",
                        false);
                case InspectGenerator:
                    return Inspect(state, selectedNpcId);
                case TellDiagnosis:
                    return TellDiagnosisToSelectedNpc(state, selectedNpcId);
                case TellManifest:
                    return TellManifestToMaren(state, selectedNpcId);
                case OfferCooperation:
                    return AcceptCooperationOffer(state, selectedNpcId);
                case RequestProcedure:
                    return AuthorizeCrate(state, selectedNpcId);
                case GiveFuse:
                    return TransferFuse(state, selectedNpcId);
                case InstallFuse:
                    return Install(state, selectedNpcId);
                case AuthorizeRestart:
                    return AuthorizeControlCabinet(state, selectedNpcId);
                case RestartGate:
                    return Restart(state, selectedNpcId);
                default:
                    return PrototypeActionResult.Reject(
                        "error_unknown_action",
                        $"未知操作：{actionId}");
            }
        }

        private static PrototypeActionResult ObserveGate(PrototypeWorldState state)
        {
            if (!state.AddPlayerFact(FactConsoleE17))
            {
                return PrototypeActionResult.Success(
                    "already_observed",
                    "控制台仍显示 E-17；这条线索已经记录。",
                    false);
            }
            return Commit(
                state,
                "observed",
                "控制台显示 E-17。下一步应选择莉娅并点击发电机。");
        }

        private static PrototypeActionResult Inspect(
            PrototypeWorldState state,
            string selectedNpcId)
        {
            PrototypeActionResult actorCheck = RequireActor(selectedNpcId, LiaId, "检查发电机需要莉娅。");
            if (actorCheck != null)
            {
                return actorCheck;
            }
            if (!state.PlayerKnows(FactConsoleE17))
            {
                return PrototypeActionResult.Reject(
                    "error_missing_fact",
                    "先点击控制台确认 E-17，再请莉娅检查发电机。");
            }
            if (state.PlayerKnows(FactMissingFuse))
            {
                return PrototypeActionResult.Success(
                    "already_applied",
                    "莉娅已经确认发电机缺少备用保险丝。",
                    false);
            }
            state.AddPlayerFact(FactMissingFuse);
            state.AddLiaFact(FactMissingFuse);
            state.ObjectiveState = "find_fuse";
            return Commit(
                state,
                "completed",
                "莉娅完成检查：发电机缺少备用保险丝。请争取费恩合作或调查记录后申请授权。");
        }

        private static PrototypeActionResult TellDiagnosisToSelectedNpc(
            PrototypeWorldState state,
            string selectedNpcId)
        {
            if (!state.PlayerKnows(FactMissingFuse))
            {
                return PrototypeActionResult.Reject(
                    "error_actor_missing_fact",
                    "你还不知道发电机缺少保险丝，请先让莉娅完成检查。");
            }
            bool changed;
            if (selectedNpcId == FinnId)
            {
                changed = state.AddFinnFact(FactMissingFuse);
            }
            else if (selectedNpcId == MarenId)
            {
                changed = state.AddMarenFact(FactMissingFuse);
            }
            else
            {
                return PrototypeActionResult.Reject(
                    "error_wrong_target",
                    "请先选择费恩或玛伦，再转述缺少保险丝的诊断。");
            }
            if (!changed)
            {
                return PrototypeActionResult.Success(
                    "already_applied",
                    "当前 NPC 已经知道缺少保险丝。",
                    false);
            }
            return Commit(state, "completed", "诊断事实已转述给当前 NPC。");
        }

        private static PrototypeActionResult TellManifestToMaren(
            PrototypeWorldState state,
            string selectedNpcId)
        {
            PrototypeActionResult actorCheck = RequireActor(selectedNpcId, MarenId, "搬运记录应提交给玛伦。");
            if (actorCheck != null)
            {
                return actorCheck;
            }
            if (!state.PlayerKnows(FactManifestMovedC12))
            {
                return PrototypeActionResult.Reject(
                    "error_actor_missing_fact",
                    "你还没有查看搬运记录板。");
            }
            if (!state.AddMarenFact(FactManifestMovedC12))
            {
                return PrototypeActionResult.Success(
                    "already_applied",
                    "玛伦已经收到 C-12 的搬运记录。",
                    false);
            }
            return Commit(state, "completed", "C-12 搬运记录已提交给玛伦。");
        }

        private static PrototypeActionResult AcceptCooperationOffer(
            PrototypeWorldState state,
            string selectedNpcId)
        {
            PrototypeActionResult actorCheck = RequireActor(selectedNpcId, FinnId, "合作请求应直接向费恩提出。");
            if (actorCheck != null)
            {
                return actorCheck;
            }
            if (state.ObjectiveState != "find_fuse")
            {
                return PrototypeActionResult.Reject(
                    "error_missing_precondition",
                    "先完成故障诊断，再与费恩讨论交付。");
            }
            if (!state.FinnKnows(FactMissingFuse))
            {
                return PrototypeActionResult.Reject(
                    "error_missing_fact",
                    "费恩还不知道维修需要保险丝，请先把莉娅的诊断告诉他。");
            }
            if (state.FuseLocation != "cargo_crate_c12")
            {
                return PrototypeActionResult.Success(
                    "already_applied",
                    "保险丝已经完成交付。",
                    false);
            }
            state.AddPlayerFact(FactFuseMovedToC12);
            return CompleteFuseTransfer(
                state,
                "cooperation",
                "费恩接受先维修、后处理责任的合作提议，并把保险丝交给莉娅。");
        }

        private static PrototypeActionResult AuthorizeCrate(
            PrototypeWorldState state,
            string selectedNpcId)
        {
            PrototypeActionResult actorCheck = RequireActor(selectedNpcId, MarenId, "程序授权必须由玛伦处理。");
            if (actorCheck != null)
            {
                return actorCheck;
            }
            if (!state.MarenKnows(FactMissingFuse) || !state.MarenKnows(FactManifestMovedC12))
            {
                return PrototypeActionResult.Reject(
                    "error_missing_fact",
                    "玛伦需要同时收到缺少保险丝的诊断和 C-12 搬运记录。");
            }
            if (state.CrateAuthorized)
            {
                return PrototypeActionResult.Success(
                    "already_applied",
                    "玛伦已经授权检查 C-12。",
                    false);
            }
            state.CrateAuthorized = true;
            return Commit(
                state,
                "completed",
                "玛伦依据诊断和搬运记录授权检查 C-12。选择费恩并点击货箱完成交付。");
        }

        private static PrototypeActionResult TransferFuse(
            PrototypeWorldState state,
            string selectedNpcId)
        {
            PrototypeActionResult actorCheck = RequireActor(selectedNpcId, FinnId, "只有费恩可以从 C-12 交付保险丝。");
            if (actorCheck != null)
            {
                return actorCheck;
            }
            if (state.ObjectiveState != "find_fuse" || state.FuseLocation != "cargo_crate_c12")
            {
                return PrototypeActionResult.Reject(
                    "error_item_unavailable",
                    "保险丝当前不能从 C-12 再次交付。");
            }
            if (!state.CrateAuthorized)
            {
                return PrototypeActionResult.Reject(
                    "error_object_locked",
                    "C-12 尚未获得玛伦授权；也可以改走合作路线直接请求费恩先交付。");
            }
            return CompleteFuseTransfer(
                state,
                "procedure",
                "费恩按玛伦的授权把保险丝交给莉娅。");
        }

        private static PrototypeActionResult CompleteFuseTransfer(
            PrototypeWorldState state,
            string route,
            string message)
        {
            state.FuseRoute = route;
            state.FuseLocation = LiaId;
            state.ObjectiveState = "install_fuse";
            state.AddPlayerFact(FactCrateContainsFuse);
            state.AddLiaFact(FactCrateContainsFuse);
            return Commit(state, "completed", message);
        }

        private static PrototypeActionResult Install(
            PrototypeWorldState state,
            string selectedNpcId)
        {
            PrototypeActionResult actorCheck = RequireActor(selectedNpcId, LiaId, "安装保险丝需要莉娅。");
            if (actorCheck != null)
            {
                return actorCheck;
            }
            if (state.FuseLocation != LiaId)
            {
                return PrototypeActionResult.Reject(
                    "error_item_unavailable",
                    "保险丝还没有交到莉娅手中。");
            }
            state.FuseLocation = "generator";
            state.ObjectiveState = "restart_gate";
            state.AddPlayerFact(FactFuseInstalled);
            state.AddLiaFact(FactFuseInstalled);
            return Commit(
                state,
                "completed",
                "莉娅已安装保险丝。下一步选择玛伦并点击控制柜授权重启。");
        }

        private static PrototypeActionResult AuthorizeControlCabinet(
            PrototypeWorldState state,
            string selectedNpcId)
        {
            PrototypeActionResult actorCheck = RequireActor(selectedNpcId, MarenId, "控制柜授权需要玛伦。");
            if (actorCheck != null)
            {
                return actorCheck;
            }
            if (state.FuseLocation != "generator")
            {
                return PrototypeActionResult.Reject(
                    "error_missing_precondition",
                    "先让莉娅安装保险丝。");
            }
            if (state.ControlCabinetAuthorized)
            {
                return PrototypeActionResult.Success(
                    "already_applied",
                    "控制柜已经授权；再次点击即可重启。",
                    false);
            }
            state.ControlCabinetAuthorized = true;
            return Commit(
                state,
                "completed",
                "玛伦已授权控制柜。再次点击控制柜执行最终重启。");
        }

        private static PrototypeActionResult Restart(
            PrototypeWorldState state,
            string selectedNpcId)
        {
            PrototypeActionResult actorCheck = RequireActor(selectedNpcId, MarenId, "最终重启只能由玛伦执行。");
            if (actorCheck != null)
            {
                return actorCheck;
            }
            if (!state.ControlCabinetAuthorized || state.FuseLocation != "generator")
            {
                return PrototypeActionResult.Reject(
                    "error_missing_precondition",
                    "重启前必须先安装保险丝并授权控制柜。");
            }
            state.ObjectiveState = PrototypeWorldState.SuccessObjective;
            state.AddPlayerFact(FactGateRestarted);
            state.AddMarenFact(FactGateRestarted);
            return Commit(
                state,
                "completed",
                "Prototype Success：供电恢复，闸门重新上线。");
        }

        private static PrototypeActionResult DiscoverPlayerFact(
            PrototypeWorldState state,
            string factId,
            string message)
        {
            if (!state.AddPlayerFact(factId))
            {
                return PrototypeActionResult.Success("already_observed", message, false);
            }
            return Commit(state, "observed", message);
        }

        private static PrototypeActionResult RequireActor(
            string selectedNpcId,
            string expectedNpcId,
            string message)
        {
            if (selectedNpcId == expectedNpcId)
            {
                return null;
            }
            return PrototypeActionResult.Reject("error_actor_not_authorized", message);
        }

        private static PrototypeActionResult Commit(
            PrototypeWorldState state,
            string code,
            string message)
        {
            state.CommitChange();
            return PrototypeActionResult.Success(code, message, true);
        }

    }
}
