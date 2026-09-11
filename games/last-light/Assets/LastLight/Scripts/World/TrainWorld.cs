using System;
using System.Collections;
using System.Collections.Generic;
using System.Linq;
using UnityEngine;
using UnityEngine.EventSystems;
using UnityEngine.InputSystem;
using TMPro;

namespace LastLight
{
    public sealed class WorldPick : MonoBehaviour
    {
        public string Id;
        public bool Portal;
        public Vector3 StandAt;
    }

    /// <summary>Procedural cutaway presentation. This class never owns gameplay facts.</summary>
    [DefaultExecutionOrder(300)]
    public sealed partial class TrainWorld : MonoBehaviour
    {
        Action<string> onTarget,onRoom;
        Camera worldCamera;
        GameObject stage;
        Transform staticRoot,actorRoot,propRoot;
        Light keyLight,fillLight;
        ParticleSystem smoke;
        TrainAmbience ambience;
        readonly Dictionary<string,TrainActor> actors=new Dictionary<string,TrainActor>();
        readonly Dictionary<string,GameObject> objects=new Dictionary<string,GameObject>();
        readonly Dictionary<string,Texture> portraits=new Dictionary<string,Texture>();
        readonly Queue<Vector3> playerPath=new Queue<Vector3>();
        readonly List<GameObject> animationProps=new List<GameObject>();
        GameView current;
        string room="",session="",selected="",pendingTarget="";
        bool blocked=true,lowQuality,animating,skipAnimation,pendingPortal;
        Vector3 cameraCenter;
        GameObject selectRing;
        float focusUntil;
        Vector3 focusPosition;

        public void Initialize(Action<string> target,Action<string> transition)
        {
            onTarget=target;onRoom=transition;
            if(worldCamera!=null) return;
            var camObject=new GameObject("LastLight World Camera");
            worldCamera=camObject.AddComponent<Camera>();
            worldCamera.tag="MainCamera";worldCamera.cullingMask=~(1<<30);
            worldCamera.orthographic=true;
            worldCamera.orthographicSize=6.6f;
            worldCamera.nearClipPlane=.1f;worldCamera.farClipPlane=100;
            worldCamera.clearFlags=CameraClearFlags.SolidColor;
            worldCamera.backgroundColor=WorldGeometry.Hex("15232C");
            worldCamera.transform.position=new Vector3(0,8,-12);
            worldCamera.transform.LookAt(new Vector3(0,.6f,0));
            camObject.AddComponent<AudioListener>();
            RenderSettings.ambientMode=UnityEngine.Rendering.AmbientMode.Flat;
            RenderSettings.ambientLight=WorldGeometry.Hex("667D85")*.7f;
            var lightObj=new GameObject("Emergency Key Light");
            keyLight=lightObj.AddComponent<Light>();keyLight.type=LightType.Directional;
            keyLight.color=WorldGeometry.Hex("FFE3B8");keyLight.intensity=1.05f;
            keyLight.shadows=LightShadows.Soft;
            lightObj.transform.rotation=Quaternion.Euler(52,-28,0);
            var fillObj=new GameObject("Tunnel Fill");
            fillLight=fillObj.AddComponent<Light>();fillLight.type=LightType.Directional;
            fillLight.color=WorldGeometry.Hex("92AFBF");fillLight.intensity=.45f;
            fillObj.transform.rotation=Quaternion.Euler(35,150,0);
            fillLight.shadows=LightShadows.None;
            ambience=gameObject.AddComponent<TrainAmbience>();
            ambience.Initialize();
            // A title tableau contains no real NPC knowledge or hidden 05 interior.
            BuildRoom("cabin07");
        }

        WorldItemRegistry items;
        readonly Dictionary<string,string> objectStates=new Dictionary<string,string>();
        bool resolving;
        GameView visualConnections;
        public bool TryActor(string id,out TrainActor actor)=>actors.TryGetValue(id??"",out actor);
        GameObject Object(string id)=>objects.TryGetValue(id??"",out var go)?go:null;
        TrainActor Actor(string id)=>actors.TryGetValue(id??"",out var actor)?actor:null;
        public void SetPresentationPaused(bool value){PresentationClock.Paused=value;}
        public void Apply(GameView view)
        {
            if(view==null)return;
            if(items==null)items=new WorldItemRegistry(transform);
            bool newRoom=room!=view.room_id||session!=view.session_id;
            bool newSession=session!=""&&session!=view.session_id;
            if(newSession){items.Clear();ClearPortraits();}
            items.DetachAll();
            current=view;visualConnections=view;session=view.session_id;
            if(newRoom)BuildRoom(view.room_id);
            var visible=new HashSet<string>();
            foreach(var data in view.actors??Array.Empty<ActorView>())
            {
                if(data.room_id!=view.room_id)continue;
                visible.Add(data.id);
                if(!actors.TryGetValue(data.id,out var rig))
                {
                    rig=TrainActor.Create(actorRoot,data.id,Point(data.x,data.z));
                    rig.gameObject.AddComponent<WorldPick>().Id=data.id;rig.CanTraverse=CanTraverse;actors[data.id]=rig;
                }
                if(!resolving&&(data.id!="player"||newRoom))rig.Snap(Point(data.x,data.z));
                rig.Pose=data.pose??"idle";rig.Emotion=data.emotion??"neutral";
                rig.Activity=data.activity;rig.HealthDisplay=data.health_display;
                rig.ResetHolding();rig.GetComponent<WorldPick>().StandAt=Approach(rig.transform.position);
            }
            foreach(var id in actors.Keys.ToArray())if(!visible.Contains(id)){Destroy(actors[id].gameObject);actors.Remove(id);}
            var visibleObjects=new HashSet<string>();
            foreach(var data in view.objects??Array.Empty<ObjectView>())
            {
                if(data.room_id!=view.room_id||data.id=="backup_supply"||data.id=="oxygen")continue;
                visibleObjects.Add(data.id);
                if(!objects.TryGetValue(data.id,out var obj))
                {
                    obj=WorldGeometry.Prop(propRoot,data.id,data.state??"",Point(data.x,data.z));objects[data.id]=obj;
                    var pick=obj.AddComponent<WorldPick>();pick.Id=data.id;
                    var collider=obj.AddComponent<BoxCollider>();collider.center=Vector3.up*.65f;collider.size=new Vector3(1.1f,1.4f,.6f);
                    if(data.id=="blocked_door")obj.transform.localRotation=Quaternion.Euler(0,90,0);
                }
                obj.transform.position=Point(data.x,data.z);
                obj.GetComponent<WorldPick>().StandAt=data.id=="blocked_door"?new Vector3(-6.1f,0,-.3f):Approach(obj.transform.position);
                obj.GetComponent<Collider>().enabled=data.interactable;
                if(!objectStates.TryGetValue(data.id,out var old)||old!=data.state)
                {WorldGeometry.ApplyPropState(obj,data.id,data.state);objectStates[data.id]=data.state;}
            }
            foreach(string id in objects.Keys.ToArray())
                if(!id.StartsWith("portal_")&&id!="backup_supply"&&id!="oxygen"&&!visibleObjects.Contains(id))
                {Destroy(objects[id]);objects.Remove(id);objectStates.Remove(id);}
            items.Sync(view,Actor,Object);
            BindItemTarget("backup","backup_supply",view);BindItemTarget("medical","oxygen",view);
            AddPortals(view);
            foreach(var data in view.actors??Array.Empty<ActorView>())
                if(actors.TryGetValue(data.id,out var rig)&&TargetPosition(data.attention_target_id??"",out var focus))rig.BaseAttention=focus+Vector3.up*.9f;
            int level=(view.rooms??Array.Empty<RoomView>()).FirstOrDefault(r=>r.id==room)?.smoke??0;
            ApplySmoke(level);ApplySceneLighting(view,level);ambience?.SetScene(room,level,!string.IsNullOrEmpty(view.ending));
            if(newRoom){cameraCenter=Vector3.zero;Focus("player");}
            if(view.execution==null&&!resolving){animating=false;foreach(var rig in actors.Values)rig.StopWork();}
            items.Validate();
        }
        void BindItemTarget(string id,string objectId,GameView view)
        {
            var go=items.Get(id);if(go==null||!go.activeInHierarchy){objects.Remove(objectId);return;}
            objects[objectId]=go;var data=(view.objects??Array.Empty<ObjectView>()).FirstOrDefault(o=>o.id==objectId);
            if(data==null)return;
            var pick=go.GetComponent<WorldPick>()??go.AddComponent<WorldPick>();pick.Id=objectId;pick.StandAt=Approach(go.transform.position);
            var col=go.GetComponent<BoxCollider>()??go.AddComponent<BoxCollider>();col.center=Vector3.up*.22f;col.size=new Vector3(.38f,.48f,.26f);col.enabled=data.interactable;
        }
        bool CanTraverse(Vector3 from,Vector3 to)
        {
            Vector3 delta=to-from;if(delta.sqrMagnitude<1e-8f)return true;
            foreach(var pair in objects)
            {
                if(!pair.Key.Contains("door")||pair.Value==null)continue;
                var marker=pair.Value.transform.Find("PassageBlocker");
                if(marker==null||!marker.gameObject.activeInHierarchy)continue;
                var bounds=marker.GetComponent<BoxCollider>().bounds;
                bounds.Expand(new Vector3(.22f,0,.22f));
                Vector3 start=from+Vector3.up*.8f;
                if(!bounds.Contains(start)&&bounds.IntersectRay(new Ray(start,delta.normalized),out float distance)&&distance<=delta.magnitude+.02f)return false;
            }
            return true;
        }
        public bool ResolveGaze(string actorId,string target,out Vector3 position)
        {
            position=Vector3.zero;if(!actors.TryGetValue(actorId,out var rig))return false;
            if(target=="player_head"||target=="player_body")
            {if(!actors.TryGetValue("player",out var player))return false;position=player.transform.position+Vector3.up*(target=="player_head"?1.65f:1.05f);return true;}
            if(target=="away"){position=rig.transform.position+rig.transform.right*1.2f+Vector3.up*1.2f;return true;}
            if(target=="ground"){position=rig.transform.position+rig.transform.forward*.65f;return true;}
            if(target=="nearby_threat")
            {
                var info=(current?.rooms??Array.Empty<RoomView>()).FirstOrDefault(r=>r.id==room);
                if(info!=null&&info.smoke>0){position=rig.transform.position+Vector3.up*1.25f+Vector3.forward;return true;}
                // Visible warning indicators only; no hidden fault, child or private motive lookup.
                var warning=(current?.objects??Array.Empty<ObjectView>()).FirstOrDefault(o=>o.id=="cabinet"&&o.state=="live");
                if(warning!=null){position=new Vector3(warning.x,1.1f,warning.z);return true;}
            }
            position=rig.transform.position+rig.transform.forward*.65f;return false;
        }

        static Vector3 Point(float x,float z)=>new Vector3(Mathf.Clamp(x,-8,8),0,Mathf.Clamp(z,-2.4f,2.4f));
        static Vector3 Approach(Vector3 p)=>new Vector3(Mathf.Clamp(p.x,-7.4f,7.4f),0,Mathf.Clamp(p.z-.75f,-1f,.5f));

        void BuildRoom(string id)
        {
            items?.DetachAll();
            if(stage!=null) Destroy(stage);
            stage=new GameObject("Stage_"+id);stage.transform.SetParent(transform,false);
            staticRoot=WorldGeometry.Group(stage.transform,"Architecture",Vector3.zero).transform;
            actorRoot=WorldGeometry.Group(stage.transform,"Actors",Vector3.zero).transform;
            propRoot=WorldGeometry.Group(stage.transform,"Objects",Vector3.zero).transform;
            actors.Clear();objects.Clear();objectStates.Clear();playerPath.Clear();pendingTarget="";selected="";
            room=id;
            if(id=="service") WorldGeometry.Service(staticRoot);
            else if(id=="tunnel") WorldGeometry.Tunnel(staticRoot);
            else WorldGeometry.Carriage(staticRoot,id);
            var smokeGo=WorldGeometry.Group(stage.transform,"SmokeState",new Vector3(0,.55f,1.3f));
            smoke=smokeGo.AddComponent<ParticleSystem>();
            smoke.Stop(true,ParticleSystemStopBehavior.StopEmittingAndClear);
            var main=smoke.main;main.startLifetime=7;main.startSpeed=.12f;main.startSize=1.3f;
            main.startColor=new Color(.36f,.39f,.39f,.19f);main.maxParticles=140;main.simulationSpace=ParticleSystemSimulationSpace.World;
            main.useUnscaledTime=true;
            var shape=smoke.shape;shape.shapeType=ParticleSystemShapeType.Box;shape.scale=new Vector3(14,.6f,2.2f);
            var emission=smoke.emission;emission.rateOverTime=0;
            var renderer=smoke.GetComponent<ParticleSystemRenderer>();
            Shader shader=Shader.Find("Universal Render Pipeline/Particles/Unlit")??Shader.Find("Particles/Standard Unlit");
            var mat=new Material(shader);mat.SetColor("_BaseColor",new Color(.45f,.47f,.46f,.17f));
            if(mat.HasProperty("_Surface"))mat.SetFloat("_Surface",1);
            if(mat.HasProperty("_SrcBlend"))mat.SetFloat("_SrcBlend",(float)UnityEngine.Rendering.BlendMode.SrcAlpha);
            if(mat.HasProperty("_DstBlend"))mat.SetFloat("_DstBlend",(float)UnityEngine.Rendering.BlendMode.OneMinusSrcAlpha);
            if(mat.HasProperty("_ZWrite"))mat.SetFloat("_ZWrite",0);
            mat.EnableKeyword("_SURFACE_TYPE_TRANSPARENT");mat.renderQueue=3000;renderer.sharedMaterial=mat;
            selectRing=WorldGeometry.Shape(stage.transform,"Selection",PrimitiveType.Cylinder,new Vector3(0,.025f,0),new Vector3(.65f,.012f,.65f),WorldGeometry.Amber,false,true);
            selectRing.SetActive(false);
        }

        void ApplySmoke(int level)
        {
            if(smoke==null)return;
            var emission=smoke.emission;
            emission.rateOverTime=level==0?0:(level==1?4:10)*(lowQuality?.45f:1f);
            if(level==0)smoke.Stop(true,ParticleSystemStopBehavior.StopEmittingAndClear);
            else if(!smoke.isPlaying)smoke.Play();
            keyLight.intensity=level==2?.85f:1.05f; // Never hide interactable silhouettes.
        }

        void ApplySceneLighting(GameView view,int smokeLevel)
        {
            var info=(view.rooms??Array.Empty<RoomView>()).FirstOrDefault(r=>r.id==room);
            bool restored=info!=null&&info.lighting=="restored";
            bool routeLit=(info!=null&&info.lighting=="lit")||
                (view.objects??Array.Empty<ObjectView>()).Any(o=>o.id=="walkway"&&o.state=="lit");
            keyLight.intensity=(smokeLevel==2?.85f:1.05f)+(restored?.25f:0);
            fillLight.intensity=restored?.6f:.45f;
            foreach(var renderer in staticRoot.GetComponentsInChildren<Renderer>())
            {
                if(renderer.gameObject.name=="RouteLamp")
                    renderer.sharedMaterial=WorldGeometry.Mat(routeLit?WorldGeometry.Green:WorldGeometry.Steel,routeLit);
                if(renderer.gameObject.name=="AuxSafetyLamp")
                    renderer.sharedMaterial=WorldGeometry.Mat(restored?WorldGeometry.Pale:WorldGeometry.Steel,restored);
                if(renderer.gameObject.name=="EmergencyLight")
                    renderer.sharedMaterial=WorldGeometry.Mat(restored?WorldGeometry.Pale:WorldGeometry.Amber,true);
            }
        }

        void AddPortals(GameView view)
        {
            foreach(string id in objects.Keys.Where(k=>k.StartsWith("portal_")).ToArray()){Destroy(objects[id]);objects.Remove(id);}
            var neighbors=new List<(string id,Vector3 position)>();
            if(room=="cabin07") { neighbors.Add(("cabin06",new Vector3(-7.8f,0,-.3f)));neighbors.Add(("service",new Vector3(7.6f,0,.7f)));neighbors.Add(("tunnel",new Vector3(5,0,-2.1f))); }
            if(room=="cabin06") { neighbors.Add(("cabin07",new Vector3(7.8f,0,-.3f)));neighbors.Add(("cabin05",new Vector3(-7.8f,0,-.3f))); }
            if(room=="cabin05") { neighbors.Add(("cabin06",new Vector3(7.8f,0,-.3f)));neighbors.Add(("tunnel",new Vector3(-6,0,-2.1f))); }
            if(room=="service") neighbors.Add(("cabin07",new Vector3(7.7f,0,-.3f)));
            if(room=="tunnel") { neighbors.Add(("cabin07",new Vector3(-7,0,-.3f)));neighbors.Add(("cabin05",new Vector3(-5,0,-1.5f))); }
            foreach(var next in neighbors)
            {
                var info=(view.rooms??Array.Empty<RoomView>()).FirstOrDefault(r=>r.id==next.id);
                if(info==null||!info.direct_accessible)continue;
                var portal=WorldGeometry.Group(propRoot,"Portal_"+next.id,next.position);
                var pick=portal.AddComponent<WorldPick>();pick.Id=next.id;pick.Portal=true;pick.StandAt=Approach(next.position);
                var col=portal.AddComponent<BoxCollider>();col.center=Vector3.up*.7f;col.size=new Vector3(.55f,1.4f,.65f);
                WorldGeometry.Box(portal.transform,"Threshold",new Vector3(0,.035f,0),new Vector3(.65f,.04f,.85f),WorldGeometry.Green,false,true);
                var label=WorldGeometry.Label(portal.transform,info.title,new Vector3(0,1.8f,0),1.5f,WorldGeometry.Pale);
                label.transform.rotation=Quaternion.Euler(30,0,0);
                objects["portal_"+next.id]=portal;
            }
        }

        void Update()
        {
            if(worldCamera==null)return;
            if(actors.TryGetValue("player",out var player))
            {
                Vector3 aim=Time.unscaledTime<focusUntil?focusPosition:player.transform.position;
                cameraCenter=Vector3.Lerp(cameraCenter,new Vector3(Mathf.Clamp(aim.x*.32f,-2.7f,2.7f),.65f,0),Time.unscaledDeltaTime*3f);
                float aspect=Mathf.Max(.7f,worldCamera.aspect);
                worldCamera.orthographicSize=Mathf.Max(5.5f,10.2f/aspect);
                worldCamera.transform.position=cameraCenter+new Vector3(0,8,-12);
                worldCamera.transform.LookAt(cameraCenter);
                if(!blocked&&!animating)
                {
                    TickMovement(player);
                    TickInput(player);
                }
                else
                {
                    playerPath.Clear();pendingTarget="";
                    if(!animating)player.Destination=player.transform.position;
                }
            }
            if(selectRing!=null&&selectRing.activeSelf)
            {
                Vector3 pos;
                if(TargetPosition(selected,out pos))selectRing.transform.position=new Vector3(pos.x,.025f,pos.z);
                else selectRing.SetActive(false);
            }
        }

        void TickMovement(TrainActor player)
        {
            if(playerPath.Count>0&&player.Arrived) player.Destination=playerPath.Dequeue();
            if(playerPath.Count==0&&player.Arrived&&pendingTarget!="")
            {
                string target=pendingTarget;bool portal=pendingPortal;pendingTarget="";
                PlayCue("click");
                if(portal)onRoom?.Invoke(target);else onTarget?.Invoke(target);
            }
        }

        void TickInput(TrainActor player)
        {
            if(EventSystem.current!=null&&EventSystem.current.currentSelectedGameObject!=null&&
                EventSystem.current.currentSelectedGameObject.GetComponent<TMP_InputField>()!=null)return;
            var keyboard=Keyboard.current;
            if(keyboard!=null)
            {
                Vector3 input=Vector3.zero;
                if(keyboard.aKey.isPressed||keyboard.leftArrowKey.isPressed)input.x-=1;
                if(keyboard.dKey.isPressed||keyboard.rightArrowKey.isPressed)input.x+=1;
                if(keyboard.wKey.isPressed||keyboard.upArrowKey.isPressed)input.z+=1;
                if(keyboard.sKey.isPressed||keyboard.downArrowKey.isPressed)input.z-=1;
                if(input.sqrMagnitude>.01f)
                {
                    playerPath.Clear();pendingTarget="";
                    Vector3 next=player.transform.position+input.normalized*Time.unscaledDeltaTime*3.4f;
                    next.x=Mathf.Clamp(next.x,-7.5f,7.5f);next.z=Mathf.Clamp(next.z,-1f,.45f);
                    player.Destination=next;
                }
                if(keyboard.eKey.wasPressedThisFrame)
                {
                    var nearest=stage.GetComponentsInChildren<WorldPick>().Where(p=>p.Id!="player")
                        .OrderBy(p=>Vector3.Distance(player.transform.position,p.StandAt)).FirstOrDefault();
                    if(nearest!=null&&Vector3.Distance(player.transform.position,nearest.StandAt)<1.8f)Select(nearest);
                }
            }
            var mouse=Mouse.current;
            if(mouse==null||!mouse.leftButton.wasPressedThisFrame)return;
            if(EventSystem.current!=null&&EventSystem.current.IsPointerOverGameObject())return;
            Ray ray=worldCamera.ScreenPointToRay(mouse.position.ReadValue());
            if(!Physics.Raycast(ray,out RaycastHit hit,80))return;
            var pick=hit.collider.GetComponentInParent<WorldPick>();
            if(pick!=null&&pick.Id!="player")Select(pick);
            else RoutePlayer(new Vector3(Mathf.Clamp(hit.point.x,-7.5f,7.5f),0,Mathf.Clamp(hit.point.z,-1,.4f)));
        }

        void Select(WorldPick pick)
        {
            Focus(pick.Id);
            RoutePlayer(pick.StandAt);
            pendingTarget=pick.Id;pendingPortal=pick.Portal;
        }

        void RoutePlayer(Vector3 destination)
        {
            if(!actors.TryGetValue("player",out var player))return;
            pendingTarget="";playerPath.Clear();
            player.Destination=new Vector3(player.transform.position.x,0,-.3f);
            playerPath.Enqueue(new Vector3(destination.x,0,-.3f));playerPath.Enqueue(destination);
        }

        public void SetInputBlocked(bool value)
        {
            blocked=value;
            if(value&&actors.TryGetValue("player",out var p))
            {
                playerPath.Clear();pendingTarget="";
                if(!animating)p.Destination=p.transform.position;
            }
        }

        public void Focus(string id)
        {
            selected=id;
            if(TargetPosition(id,out var position))
            {
                focusPosition=position;focusUntil=Time.unscaledTime+2;
                if(selectRing!=null){selectRing.SetActive(true);selectRing.transform.position=new Vector3(position.x,.025f,position.z);}
            }
        }

        bool TargetPosition(string id,out Vector3 position)
        {
            if(actors.TryGetValue(id,out var actor)){position=actor.transform.position;return true;}
            if(objects.TryGetValue(id,out var obj)){position=obj.transform.position;return true;}
            position=Vector3.zero;return false;
        }

        Vector3 ExitTowards(string destination)
        {
            var path=(current?.rooms??Array.Empty<RoomView>()).FirstOrDefault(r=>r.id==destination);
            if(path!=null&&!string.IsNullOrEmpty(path.exit_via))destination=path.exit_via;
            if(room=="cabin05")
            {
                bool internalOpen=current!=null&&(current.rooms??Array.Empty<RoomView>()).Any(r=>r.id=="cabin06"&&r.direct_accessible);
                return destination=="tunnel"||!internalOpen?new Vector3(-6,0,-.9f):new Vector3(7.2f,0,-.3f);
            }
            if(room=="cabin06")return new Vector3(destination=="cabin05"?-7.2f:7.2f,0,-.3f);
            if(room=="cabin07")return destination=="tunnel"?new Vector3(5,0,-1):new Vector3(-7.2f,0,-.3f);
            if(room=="tunnel")return new Vector3(destination=="cabin05"?-5:-7,0,-.8f);
            return new Vector3(7.2f,0,-.3f);
        }

        void ClearAnimationProps()
        {
            foreach(var prop in animationProps)if(prop!=null)Destroy(prop);
            animationProps.Clear();
        }

        public void SkipAnimation(){skipAnimation=true;}
        public void SetQuality(bool low){lowQuality=low;if(keyLight!=null)keyLight.shadows=low?LightShadows.None:LightShadows.Soft;}
        public void SetVolume(float volume){if(ambience!=null)ambience.SetVolume(volume);}
        public void PlayCue(string cue){ambience?.Cue(cue);}
        public void Emote(string actorId,string emotion){if(actors.TryGetValue(actorId,out var rig)){rig.Emotion=emotion;rig.Pose="talking";}}
        public void Gesture(string actorId,string action)
        {
            // Only the ten Director capabilities are accepted; none execute game actions.
            switch(action)
            {
                case "idle":case "nod":case "small_nod":case "shake_head":case "step_forward":
                case "step_back":case "point":case "reach_out":case "cross_arms":case "open_palms":
                    if(actors.TryGetValue(actorId,out var rig))rig.PlayGesture(action);
                    break;
            }
        }

        void OnDestroy()
        {
            items?.Clear();
            foreach(var studio in studios.Values)if(studio.root!=null)Destroy(studio.root);
            foreach(var texture in portraits.Values)if(texture is RenderTexture render){render.Release();Destroy(render);}
            if(worldCamera!=null)Destroy(worldCamera.gameObject);
            if(keyLight!=null)Destroy(keyLight.gameObject);
            if(fillLight!=null)Destroy(fillLight.gameObject);
        }
    }
}
