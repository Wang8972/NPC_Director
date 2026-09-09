# NPC Director Agent 架构对比

相较 legacy ReAct 路径，生产流程骨架更确定，但没有变成固定流水线：Main Agent 仍根据语义
决定所需能力并生成 Lore 查询；Runtime 负责权限、依赖顺序、预算、状态和普通分支的最终组装。

## 优化前 / legacy 结构（Idealab two-phase 路径）

```mermaid
flowchart TB
    Request["TurnRequest"] --> Guard["Input Guard"]
    Guard --> Context["DefaultContextBuilder<br/>角色 / 场景 / 历史 / Lore scope<br/>allowed_actions 优化前为全量枚举"]
    Context --> Director["Main Director Agent<br/>同时负责意图、路由、工具参数与汇总"]

    Director -. "按模型判断调用" .-> Narrative["Narrative Planner Agent"]
    Director -. "按模型判断调用" .-> Lore["Lore Specialist Agent"]
    Director -. "通常调用" .-> Writer["Screenwriter Agent"]
    Director -. "通常调用" .-> Performance["Performance Specialist Agent"]
    Director -. "谈判时 handoff" .-> Negotiator["Quest Negotiator Agent"]

    Narrative --> Director
    Lore --> Director
    Writer --> Director
    Performance --> Director

    Director --> Phase1["Phase 1 文本汇总<br/>工具记录 + 自由文本"]
    Phase1 --> Summary["Phase 2 Summary Agent<br/>重新生成完整 TurnProposal"]
    Negotiator -->|"可直接产生 Proposal"| Parse
    Summary --> Parse["解析 TurnProposal"]

    Hooks["Runtime Hooks<br/>记录真实 Specialist 调用"] --> Inject["解析成功后覆盖<br/>required_specialists"]
    Parse --> Inject
    Inject --> Normalize["Normalizer + Emotion Correction"]
    Normalize --> Governance["Governance + Finalizer"]
    Governance -->|"失败时整条链重跑"| Director
    Governance -->|"通过"| Unity["Unity / Runtime Directive"]

    classDef agent fill:#eef4ff,stroke:#4a6fa5,color:#17233c;
    classDef runtime fill:#f4f4f4,stroke:#666,color:#222;
    class Director,Narrative,Lore,Writer,Performance,Negotiator,Summary agent;
    class Guard,Context,Phase1,Parse,Hooks,Inject,Normalize,Governance,Unity runtime;
```

这条 legacy 路径的自由度集中在 Main Director 的 ReAct 循环中，但它也同时承担分类、路由、
参数拼装和最终语义汇总。因此自由度较高，运行路径却容易受模型和网关行为影响；阶段二还
可能重写阶段一的专家结果。仓库保留该路径用于 `react` 消融，生产默认不再使用。

## 优化后结构（受约束的动态 main-sub）

```mermaid
flowchart TB
    Request["TurnRequest"] --> Guard["Input Guard"]
    Guard --> Policy["Capability Resolver / TurnPolicy<br/>动作、表情、精确状态路径、预算<br/>策略快照随 turn 持久化"]
    Policy --> Main["Main Agent / Semantic Router<br/>只理解语义并生成 RouteDecision"]
    Main --> Compiler["Runtime Route Compiler<br/>强制低置信澄清；校验依赖与预算"]

    Compiler -. "needs_narrative" .-> Narrative["Narrative Planner Agent<br/>剧情 beats + 状态建议"]
    Compiler -. "needs_lore" .-> Lore["Runtime Lore Retrieval<br/>查询、scope 与 token 预算过滤"]
    Compiler -. "negotiation" .-> Negotiator["Quest Negotiator Agent<br/>终止 handoff"]
    Negotiator --> HandoffSanitizer["Handoff Sanitizer<br/>清空状态变化；裁剪动作/表情"]

    Narrative --> Artifacts["Typed Artifacts<br/>Route / Narrative / Evidence"]
    Lore --> Artifacts
    Policy --> Artifacts
    Artifacts --> Writer["Screenwriter Agent<br/>服务端响应义务 + 证据 + 剧情约束"]
    Writer --> Performance["Performance Agent<br/>只贡献动作、表情、凝视与时序"]
    Policy --> Performance
    Performance --> Assemble["Deterministic Assembler<br/>字段所有权 + 状态/cue 裁剪<br/>从 completed ledger 注入真实 specialists"]
    Artifacts --> Assemble

    Compiler -. "低置信 / 歧义 / 超预算" .-> Clarify["Clarification Route<br/>不推进剧情或状态"]
    Clarify --> Writer
    Compiler -. "预算不足以运行 Writer + Performance" .-> BudgetFallback["Deterministic Safe Fallback<br/>无状态、无 cue、转人工审批"]

    Assemble --> Governance["Governance / Finalizer"]
    HandoffSanitizer --> Governance
    BudgetFallback --> Governance
    Governance -->|"persona / lore / safety 软失败<br/>复用 Route + Narrative + Lore"| Writer
    Governance -->|"通过"| Unity["Unity / Runtime Directive"]

    classDef agent fill:#eef4ff,stroke:#4a6fa5,color:#17233c;
    classDef runtime fill:#f4f4f4,stroke:#666,color:#222;
    class Main,Narrative,Negotiator,Writer,Performance agent;
    class Guard,Policy,Compiler,Lore,Artifacts,HandoffSanitizer,Assemble,Governance,Clarify,BudgetFallback,Unity runtime;
```

优化后的确定性主要体现在安全边界和数据流，而不是业务语义：

- **仍然动态**：Main Agent 通过 `RouteDecision` 决定是否需要 Lore、Narrative 或 Negotiator，
  并生成目标、查询与约束；它不直接执行任意子图。
- **变得确定**：Runtime 校验调用权限、依赖顺序和预算；状态路径与真实调用轨迹不再由模型
  自报。谈判分支由 Runtime 直接运行 Negotiator，再经过专用 sanitizer，而非普通 Assembler。
- **保留创作自由**：查询设计、剧情 beats、台词、情绪和允许范围内的演出仍由各 Specialist 生成。
- **局部恢复**：persona、Lore 或 safety 软失败时复用已完成的 Router、Narrative 与 Lore，
  只重跑 Screenwriter 和 Performance；该复用是单进程、单 executor 实例内的有界 LRU 缓存，
  其他反馈或实例切换会完整重路由以避免错误复用。

这仍然是 main-sub agents，只是从“Main Agent 自由执行所有控制流”转为“Main Agent 提出动态
语义需求，Runtime 在可信边界内执行”。它描述的是架构约束，不要求必须使用 LangGraph；
普通代码、Agents SDK 或 LangGraph 都可以实现。

## 垂直切片 Real 入口

P3/垂直切片的 Real 模式不得把“调用了真实模型”当成“调用了生产编排”。默认路径固定为：

```text
Unity / Mock Unity
  → PrototypeRealDirectorSession
  → Scene Action Planner（只拥有游戏域动作候选）
  → ResilientDirectorExecutor
  → BoundedDirectorExecutor
  → Semantic Router / Specialists / Deterministic Assembler
  → PrototypeRealGovernance
  → PrototypePuzzleRules
  → Unity scene action + completed 后提交
```

Scene Action Planner 是原型域适配器，只能填写 `PrototypeSceneActionProposal`；它不能生成最终
台词、演出或状态补丁。最终 `PerformanceDraft` 必须来自受约束生产编排，场景动作仍须通过
知识治理与确定性谜题规则。运行报告必须记录 `executor_chain`、`specialists_called` 和
`routing_trace`；P3/P4 阶段门只有在 `production_orchestration=true` 时才接受 Real 证据。

`OpenAIPrototypeTurnGenerator` 和对应 Codex 单调用适配仅为历史报告复现保留，不再作为 P3
默认路径，也不能单独产生新的 P3/P4 通过证据。
