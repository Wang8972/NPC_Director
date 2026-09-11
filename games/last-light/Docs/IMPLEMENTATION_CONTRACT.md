# 余灯 / LAST LIGHT — implementation contract v1

User-approved plan replaces old draft. Unity 6 LTS / URP / uGUI+TMP / New Input System, explorable 2.5D cutaway, ordinary passenger, 4 NPCs lin/zhou/chen/xu. 45–60min target. Python authoritative world + REAL default NPC Director v2. Diagnostic rehearsal clearly labelled; never pretend script/keyword dialogue is AI. No Unity-owned physical state. Full approved spec in GAME_SPEC.md (root writing).

## Ownership
Core: backend/last_light/{models,engine,repository,content}.py and data/**; backend/tests/test_engine*.py,test_repository*.py; Docs/RULES.md.
Director: backend/last_light/{director,director_contracts}.py,director_data/**; backend/tests/test_director*.py; tools/live_eval.py; Docs/DIRECTOR.md.
UI: Assets/LastLight/Scripts/UI/** and Net/** (wire DTOs, HTTP client, app/controller, process launcher, menus, TMP/new Input System UI).
Root: FastAPI app/glue; procedural 3D world/characters/camera/input in Scripts/World/**; assets/audio/fonts; Editor bootstrap/build; project config; packaging/verification.
Do not edit other ownership without coordination. Sibling npc-director changes require concrete coordination; no unrelated changes.

## Core API (Python synchronous, no model calls)
Package backend/last_light. WorldEngine(state:dict|None=None,session_id:str|None=None), serializable state with schema_version=1, revision,tick,mode,event history. Validate restores.
view()->dict projection; move(room_id)->result; inspect(target_id)->result; propose(steps:list[dict],title='')->result; begin(plan_id)->result; complete(execution_id)->result (idempotent); cancel(plan_id)->result; apply_decision(npc_id,decision:dict)->result (delivered social agreements only); npc_context(npc_id)->dict (own known facts, promises, legal actions, witnesses); talk_rehearsal(npc_id,text,topic_id='')->dict (explicit authored diagnostic, no arbitrary text side effects).
Result={ok:bool,error?:string,view:dict}. ValueError may be caught by API. Additional helpers allowed; communicate API adjustments.
propose validates IDs/abilities/dependencies/resources. begin reserves and produces simultaneous execution batch; physical effects commit only in complete. complete advances to next event boundary, pauses for reaction, preserves completed work on cancel. Free exploration never ticks. Engine owns all character knowledge/social rule boundaries too; Director proposes decisions only. Core should communicate fixed object/action IDs early.

## Projection JSON (snake_case; Unity collections MUST be arrays not maps)
GameView: session_id,mode,room_id,objective,chapter,ending,ending_title,ending_text strings; revision,tick ints; actors:ActorView[],rooms:RoomView[],objects:ObjectView[],actions:ActionView[],inventory:ItemView[],journal:JournalView[],dialogue:DialogueLine[],plans:PlanView[],execution:ExecutionView|null,epilogues:DialogueLine[].
ActorView: id,name,role,room_id,pose,emotion,carrying,task_status strings; x,z floats. ONLY visible actors (player,lin,zhou,chen,xu,mother,xiaoman,passenger05,passenger07).
RoomView: id,title,description strings; accessible,visited bool; smoke int 0/1/2. IDs cabin05,cabin06,cabin07,service,tunnel. Don't leak unvisited interiors.
ObjectView: id,label,room_id,state,description strings; interactable bool; x,z floats.
ActionView: id,label,description,target_id,kind,blocked_reason,default_actor strings; duration int; enabled bool; actor_ids string[].
ItemView: id,label,owner_id,holder_id,room_id,connected_to,state strings; charge int (-1 nonpowered).
JournalView: id,title,text,source,kind strings; tick int; kind observed/reported/verified/promise.
DialogueLine: id,npc_id,speaker,text,emotion,source strings; source live/rehearsal/narrative; speaker display Chinese name.
PlanStep: id,action_id,actor_id,target_id,status,reason strings; helpers,depends_on string[]; duration int.
PlanView: id,title,status,summary strings; total_ticks int; conditions string[]; steps PlanStep[]. Status proposed/accepted/waiting/executing/completed/failed/cancelled.
ExecutionView: id,plan_id,action_id,target_id,room_id strings; actor_ids string[]; duration int; steps PlanStep[]. Batch may have parallel steps. Unity animate then complete once, same effects if skipped.

## HTTP (root implements)
Base 127.0.0.1:8765. Response={ok,error,view:GameView|null,job:TalkJob|null,session_id}.
GET /health. POST /sessions {mode:live|rehearsal}; GET /sessions -> {sessions:[{session_id,updated_at,chapter,tick,mode}]}; GET /sessions/{sid}.
POST /sessions/{sid}/move {room_id,expected_revision}; /inspect {target_id,expected_revision}; /plan {title,steps:[{action_id,actor_id,target_id,helpers,depends_on}],expected_revision}; /begin {plan_id,expected_revision}; /complete {execution_id,expected_revision}; /cancel {plan_id,expected_revision}; /save {}; /restore {}.
POST /sessions/{sid}/talk {npc_id,text,topic_id,audience:string[],expected_revision} returns job immediately. GET /sessions/{sid}/talk/{job_id}; POST same path /ack {line_id}, /cancel {}.
TalkJob: id,status,error,source,episode_id,suggested_title strings; lines DialogueLine[]; suggested_steps PlanStep[]. status running/waiting_delivery/completed/failed/cancelled. ACK only lines actually displayed; job may expose successive NPC beats. Suggested plans require explicit confirmation and world validation.

## Director adapter (coordinate exact signature)
DirectorBridge(data_dir:Path,engine_lookup:Callable[[str],WorldEngine],persist:Callable[[str],None]).
async start(sid,npc_id,text,audience)->dict; get_job(sid,job_id)->dict; async acknowledge(sid,job_id,line_id)->dict; async cancel(sid,job_id)->dict; async sync_world(sid)->None; available()->dict.
Use true build_default_service, bounded v2 episodes, actual delivery lifecycle and private context. Need semantic train action/condition proposals, not just dialogue polishing; use v2 artifacts or guarded train planner integrated with same provider if needed (count budget). Physics ONLY engine. Never seed globally hidden facts to all NPCs. Whole-game session stable, event episodes bounded. No live calls until root requests after offline tests. qwen3.8-flash probe once; live aggregate budget 200000 tokens incl retries/runtime review; no automatic expensive model upgrade, no external judge.

## Unity shared API
Namespace LastLight. UI owns LastLightApp:MonoBehaviour (root bootstrap adds it) and GameView/DTOs in Net.
Root owns TrainWorld:MonoBehaviour:
Initialize(Action<string> onTarget,Action<string> onRoom); Apply(GameView view); SetInputBlocked(bool); Focus(string actorOrObjectId); IEnumerator Animate(ExecutionView); SetQuality(bool low); SetVolume(float); Emote(string actorId,string emotion); Texture Portrait(string actorId); PlayCue(string cue).
World owns camera/click/WASD/E and calls onTarget (npc/object ID) or onRoom (room ID). World never HTTP. UI blocks world during typing/modal and guards UI pointer. UI executes animation coroutine then POST complete then Apply. Root provides procedural meshes/rigs/materials, Resources/Fonts/Chinese.ttf and self-generated Audio clips. TMP dynamic Chinese font, no missing glyph fallback. 1920x1080 layout, usable 1280x720/16:10, dialogue scroll.

## Frozen invariants
Train 05—06—07; 05/06 trolley-jammed,06/07 open,service entered07; external walkway only with traffic+path+door separately verified. Fixed independent emergency phone in service, equipment/lighting preplaced.
Lin: initial electrical report/traffic unconfirmed/communication lost private; truthful uncertainty; verified smoke updates action; insulting never blocks basic aid; traffic != route safety.
Zhou: went07 for water leaving9-year-old Xiaoman05; attempted blockeddoor then returned07. Naturally explains child, no keyword or like gate. Audible != checked != reunited. Actual accepted rescuer + report checkpoint before delegation; care obligation remains after reunion.
Chen: previously temporary fixed aux06 joint, missed retest yet signed complete. Only suspects present cause until diagnostics. Independent auxiliary still live after main light trip. Isolation->repair->retest; disclosure != cooperation; no delete evidence/false retest.
Xu: mother's chronic respiratory condition stable on internal battery; compatible backup heldXu. Limited loan with purpose/deadline/reserve. Actual smoke exposure + sustained need may invalidate agreement; protection genuinely prevents. Withdraw request doesn't teleport item or refund charge. Actual transfer/return separately committed.
Free talk/read/network wait never advances risk. Parallel tasks and cancellations preserve causal state. Endings stay_all/evacuate_all/costly/failed never auto-rescue omitted people. UI never shows unobserved 05 or secret motives. Source/tokens/untested Windows results reported truthfully.
