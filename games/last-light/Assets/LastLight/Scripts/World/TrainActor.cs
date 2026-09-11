using System;
using System.Collections.Generic;
using System.Linq;
using UnityEngine;

namespace LastLight
{
    /// <summary>Imported, skinned actor. Authority owns positions; this owns presentation only.</summary>
    [DefaultExecutionOrder(250)]
    public sealed class TrainActor : MonoBehaviour
    {
        public string Id { get; private set; }
        public Vector3 Destination;
        public string Pose="idle",Emotion="neutral",Activity="",HealthDisplay="";
        public bool Working,ExternalMovement;
        public Func<Vector3,Vector3,bool> CanTraverse;
        public bool Arrived=>Vector3.Distance(transform.position,Destination)<.035f;
        public bool HasHeldItem=>heldHands.Count>0||personalCup!=null;
        public GameObject Visual { get; private set; }
        public string ActiveClip { get; private set; }="idle";
        public float Phase { get; private set; }
        readonly Dictionary<string,Transform> bones=new Dictionary<string,Transform>();
        readonly Dictionary<string,Transform> sockets=new Dictionary<string,Transform>();
        readonly HashSet<string> heldHands=new HashSet<string>();
        readonly Dictionary<string,(Vector3 p,Quaternion q)> bind=new Dictionary<string,(Vector3,Quaternion)>();
        SkinnedMeshRenderer face;
        string workClip="",legacyGesture="";
        float workPhase,legacyPhase;
        float moodArousal=.4f,moodIntensity;
        Vector3? gaze,leftContact,rightContact;
        public Vector3? BaseAttention;
        string gazeMode="soft_focus";
        Transform personalCup,personalRadio,personalBag,personalKey;
        public static TrainActor Create(Transform parent,string id,Vector3 position)
        {
            var go=new GameObject("Actor_"+id);go.transform.SetParent(parent,false);go.transform.localPosition=position;
            var actor=go.AddComponent<TrainActor>();actor.Id=id;go.transform.localRotation=Quaternion.Euler(0,180,0);actor.Destination=go.transform.position;actor.Build();return actor;
        }
        void Build()
        {
            Visual=Instantiate(PresentationAssets.Required.Character(Id),transform,false);Visual.name="Visual";PresentationSockets.Attach(Visual,"actor");
            foreach(var t in Visual.GetComponentsInChildren<Transform>())
            {if(!bones.ContainsKey(t.name)){bones[t.name]=t;bind[t.name]=(t.localPosition,t.localRotation);}}
            face=Visual.GetComponentsInChildren<SkinnedMeshRenderer>().FirstOrDefault(r=>r.sharedMesh.blendShapeCount>0);
            Socket("hand_r");Socket("hand_l");Socket("carry_front");Socket("stow");Socket("support_l");Socket("support_r");
            if(Id=="zhou")
            {
                personalBag=Instantiate(PresentationAssets.Required.Prop("tools"),Socket("stow"),false).transform;
                personalBag.name="Personal_zhou_cup_pouch";personalBag.localScale=Vector3.one*.45f;
                personalCup=Instantiate(PresentationAssets.Required.Prop("cup"),Socket("hand_l"),false).transform;personalCup.name="Personal_zhou_cup";
            }
            if(Id=="lin")
            {
                personalRadio=Instantiate(PresentationAssets.Required.Prop("radio_handset"),Socket("chest"),false).transform;
                personalRadio.name="Personal_lin_radio";
                personalKey=Instantiate(PresentationAssets.Required.Prop("key"),Socket("stow"),false).transform;personalKey.name="Personal_lin_staff_key";
            }
            var collider=gameObject.AddComponent<BoxCollider>();collider.center=Vector3.up*.9f;collider.size=new Vector3(.6f,1.8f,.5f);
            if(Id=="xiaoman"){collider.center*=.76f;collider.size*=.76f;}
        }
        public Transform Socket(string id)
        {
            if(sockets.TryGetValue(id,out var existing))return existing;
            var found=PresentationSockets.Find(Visual,id);
            if(found==null)throw new InvalidOperationException("Missing actor socket: "+id);
            sockets[id]=found;return found;
        }
        public void SetHolding(string socket,bool occupied){if(occupied)heldHands.Add(socket);else heldHands.Remove(socket);}
        public void ResetHolding(){heldHands.Clear();}
        public void SetCarrying(string item) { /* Inventory registry binds the sole world item, never creates a copy. */ }
        public void Snap(Vector3 point){transform.position=Destination=point;}
        public void PlayWork(string clip,bool hold=false){workClip=clip;workPhase=0;Working=true;holdWork=hold;}
        bool holdWork;
        public void StopWork(){Working=false;workClip="";leftContact=rightContact=null;}
        public void SetHandTarget(bool left,Vector3? point){if(left)leftContact=point;else rightContact=point;}
        public float GestureDuration(string action)=>PresentationAssets.Required.Clip(action).duration;
        public bool CanGesture(string action,string layer)
        {
            bool usesHands=new[]{"point","reach_out","cross_arms","open_palms"}.Contains(action);
            if(usesHands&&(Working||HasHeldItem))return false;
            return !Working||new[]{"idle","nod","small_nod","shake_head"}.Contains(action);
        }
        public void PlayGesture(string action){legacyGesture=action??"idle";legacyPhase=0;}
        public void SetFace(string preset,float intensity)
        {
            if(face==null)return;
            for(int i=0;i<face.sharedMesh.blendShapeCount;i++)face.SetBlendShapeWeight(i,0);
            int at=face.sharedMesh.GetBlendShapeIndex(preset??"neutral");
            if(at>=0)face.SetBlendShapeWeight(at,Mathf.Clamp01(intensity)*100);
            int blink=face.sharedMesh.GetBlendShapeIndex("blink");
            if(blink>=0)face.SetBlendShapeWeight(blink,Mathf.Repeat(Phase+StableOffset(Id),4.7f)<.12f?100:0);
        }
        static float StableOffset(string text){int n=0;foreach(char c in text)n=(n*31+c)%997;return n/997f;}
        public void SetGaze(Vector3? position,string mode){gaze=position;gazeMode=mode??"soft_focus";}
        public void ClearPerformance(){moodArousal=.4f;moodIntensity=0;SampleBase();SetFace(Emotion,.45f);gaze=BaseAttention;}
        public void SetMood(EmotionView value){moodArousal=Mathf.Clamp01(value?.arousal??.4f);moodIntensity=Mathf.Clamp01(value?.intensity??0);}
        public void SampleGesture(string action,string layer,float seconds)
        {
            if(!CanGesture(action,layer))return;
            var before=bones.ToDictionary(k=>k.Key,k=>(p:k.Value.localPosition,q:k.Value.localRotation));
            var motion=PresentationAssets.Required.Clip(action);motion.clip.SampleAnimation(Visual,Mathf.Clamp(seconds,0,motion.duration));
            foreach(var pair in bones)
            {
                string name=pair.Key;var t=pair.Value;var old=before[name];
                bool upper=name.Contains("Arm_")||name.Contains("Forearm_")||name.Contains("Hand_")||name.Contains("Grip_")||name.Contains("Shoulder_")||name=="Chest"||name=="Spine"||name=="Neck"||name=="Head";
                bool excluded=name=="Root"||name=="Hips"||(!upper&&layer!="full_body")||
                    ((Working||HasHeldItem)&&!(name=="Head"||name=="Neck"));
                if(excluded){t.localPosition=old.p;t.localRotation=old.q;}
                else
                {
                    t.localPosition=old.p; // Conversational animation has no translational authority.
                    if(layer=="additive")t.localRotation=old.q*Quaternion.Inverse(bind[name].q)*t.localRotation;
                }
            }
        }
        void SampleBase()
        {
            foreach(var pair in bones){pair.Value.localPosition=bind[pair.Key].p;pair.Value.localRotation=bind[pair.Key].q;}
            string clip=Working&&!string.IsNullOrEmpty(workClip)?workClip:!Arrived?"walk":Pose=="carried_litter"?"carried_litter":
                Pose=="sitting"||Id=="mother"?"seated":Pose=="assisted_walk"?"escort_walk":"idle";
            float idleWindow=Mathf.Repeat(Phase+StableOffset(Id)*7,11);
            if(clip=="idle"&&idleWindow<2.4f)
                clip=Activity=="checking_radio"?"look_radio":Activity=="caregiving"&&BaseAttention.HasValue?"check_patient":Activity=="checking_equipment"?"inspect_stand":Activity=="waiting_at_door"?"observe":clip;
            var motion=PresentationAssets.Required.Clip(clip);float time=Working?workPhase:(motion.loop?Phase:idleWindow);
            if(motion.loop)time=Mathf.Repeat(time,motion.duration);
            else time=Mathf.Min(time,holdWork?motion.duration*.55f:motion.duration);
            motion.clip.SampleAnimation(Visual,time);ActiveClip=clip;
            if(ExternalMovement&&Pose!="carried_litter")
                foreach(var side in new[]{"L","R"})
                {
                    float stride=Mathf.Sin(Phase*6)*(side=="L"?1:-1);
                    bones["Thigh_"+side].localRotation=bind["Thigh_"+side].q*Quaternion.Euler(stride*18,0,0);
                    bones["Shin_"+side].localRotation=bind["Shin_"+side].q*Quaternion.Euler(Mathf.Max(0,-stride)*25,0,0);
                }
            if((HealthDisplay=="labored"||HealthDisplay=="needs_support"||HealthDisplay=="needs_urgent_support")&&!Working&&Arrived&&bones.TryGetValue("Chest",out var chest))
                chest.localRotation*=Quaternion.Euler(4+Mathf.Sin(Phase*3)*1.8f,0,0);
        }
        void Update()
        {
            float dt=PresentationClock.Delta;gaze=BaseAttention;Phase+=dt;workPhase+=dt;
            Vector3 delta=Destination-transform.position;
            if(!Arrived&&!ExternalMovement)
            {
                var next=Vector3.MoveTowards(transform.position,Destination,dt*2.0f);
                if(CanTraverse==null||CanTraverse(transform.position,next))transform.position=next;
                transform.rotation=Quaternion.Slerp(transform.rotation,Quaternion.LookRotation(delta.normalized,Vector3.up),dt*7);
            }
            SampleBase();SetFace(Emotion,.45f);
            if(!string.IsNullOrEmpty(legacyGesture)&&legacyGesture!="idle")
            {
                legacyPhase+=dt;
                if(legacyPhase<GestureDuration(legacyGesture))SampleGesture(legacyGesture,"upper_body",legacyPhase);else legacyGesture="";
            }
            if(personalRadio!=null)
            {
                var radioSocket=(ActiveClip=="use_radio"||ActiveClip=="announce"||ActiveClip=="look_radio")?Socket("hand_r"):Socket("chest");
                if(personalRadio.parent!=radioSocket)personalRadio.SetParent(radioSocket,false);
            }
            if(personalKey!=null)
            {
                var keySocket=ActiveClip=="operate_door"?Socket("hand_r"):Socket("stow");
                if(personalKey.parent!=keySocket)personalKey.SetParent(keySocket,false);
            }
            if(personalCup!=null)
            {
                var target=Working||heldHands.Contains("hand_l")?Socket("stow"):Socket("hand_l");
                if(personalCup.parent!=target)personalCup.SetParent(target,false);
            }
        }
        void LateUpdate()
        {
            if(gaze.HasValue&&bones.TryGetValue("Head",out var head))
            {
                Vector3 aim=gaze.Value;
                if(gazeMode=="scanning")aim+=transform.right*Mathf.Sin(Phase*.7f)*.35f;
                if(gazeMode=="avoidant")aim+=transform.right*.65f-Vector3.up*.25f;
                var local=transform.InverseTransformDirection(aim-head.position);
                float yaw=Mathf.Clamp(Mathf.Atan2(local.x,local.z)*Mathf.Rad2Deg,-55,55);
                float pitch=Mathf.Clamp(-Mathf.Atan2(local.y,new Vector2(local.x,local.z).magnitude)*Mathf.Rad2Deg,-22,25);
                if(gazeMode=="soft_focus"){yaw*=.6f;pitch*=.6f;}
                head.localRotation*=Quaternion.Euler(pitch,yaw,0);
                foreach(string side in new[]{"L","R"})if(bones.TryGetValue("Eye_"+side,out var eye))eye.localRotation*=Quaternion.Euler(pitch*.2f,yaw*.25f,0);
            }
            if(moodIntensity>0&&bones.TryGetValue("Chest",out var torso))torso.localRotation*=Quaternion.Euler(Mathf.Sin(Phase*(1.2f+moodArousal))*moodIntensity*.8f,0,0);
            if(leftContact.HasValue)Reach("L",leftContact.Value);
            if(rightContact.HasValue)Reach("R",rightContact.Value);
        }
        void Reach(string side,Vector3 target)
        {
            var upper=bones["UpperArm_"+side];var elbow=bones["Forearm_"+side];var hand=bones["Hand_"+side];
            float a=Vector3.Distance(upper.position,elbow.position),b=Vector3.Distance(elbow.position,hand.position);
            Vector3 delta=target-upper.position;float length=Mathf.Clamp(delta.magnitude,.02f,a+b-.001f);Vector3 dir=delta.normalized;
            Vector3 pole=Vector3.Cross(dir,transform.forward);if(pole.sqrMagnitude<.001f)pole=transform.right;
            pole=Vector3.Cross(pole.normalized,dir).normalized;
            float adjacent=(a*a+length*length-b*b)/(2*length);float high=Mathf.Sqrt(Mathf.Max(0,a*a-adjacent*adjacent));
            Vector3 desired=upper.position+dir*adjacent+pole*high;
            upper.rotation=Quaternion.FromToRotation(elbow.position-upper.position,desired-upper.position)*upper.rotation;
            elbow.rotation=Quaternion.FromToRotation(hand.position-elbow.position,target-elbow.position)*elbow.rotation;
        }
        public void CopyPoseTo(TrainActor target)
        {
            foreach(var pair in bones)if(target.bones.TryGetValue(pair.Key,out var t)){t.localPosition=pair.Value.localPosition;t.localRotation=pair.Value.localRotation;}
            if(face!=null&&target.face!=null)for(int i=0;i<face.sharedMesh.blendShapeCount;i++)target.face.SetBlendShapeWeight(i,face.GetBlendShapeWeight(i));
        }
    }
}
