using System;
using System.Collections.Generic;
using System.Linq;
using UnityEngine;

namespace LastLight
{
    public sealed class WorldItemIdentity : MonoBehaviour { public string id; }
    /// <summary>Exactly one live model for each authority item. No animation duplicates.</summary>
    public sealed class WorldItemRegistry
    {
        readonly Transform root;
        readonly Dictionary<string,GameObject> instances=new Dictionary<string,GameObject>();
        GameObject cable;
        readonly Dictionary<string,GameObject> toolParts=new Dictionary<string,GameObject>();
        public WorldItemRegistry(Transform parent){var go=new GameObject("PersistentItems");go.transform.SetParent(parent,false);root=go.transform;}
        public IEnumerable<string> Ids=>instances.Keys;
        public GameObject Get(string id)=>instances.TryGetValue(id??"",out var go)?go:null;
        public void DetachAll(){StowTools();foreach(var go in instances.Values)if(go!=null)go.transform.SetParent(root,true);}
        public void Clear(){foreach(var go in instances.Values)if(go!=null){go.SetActive(false);UnityEngine.Object.Destroy(go);}instances.Clear();toolParts.Clear();if(cable!=null)UnityEngine.Object.Destroy(cable);}
        public void Sync(GameView view,Func<string,TrainActor> actor,Func<string,GameObject> obj)
        {
            DetachAll();
            foreach(var go in instances.Values)go.SetActive(false);
            var used=new HashSet<string>();
            foreach(var item in (view.inventory??Array.Empty<ItemView>()).OrderBy(i=>Priority(i.id)))
            {
                if(item.state=="consumed"||item.room_id!=view.room_id)continue;
                if(!instances.TryGetValue(item.id,out var go))
                {
                    go=UnityEngine.Object.Instantiate(PresentationAssets.Required.Prop(item.id),root,false);go.name="Item_"+item.id;
                    go.AddComponent<WorldItemIdentity>().id=item.id;PresentationSockets.Attach(go,item.id);instances[item.id]=go;
                }
                go.SetActive(true);UpdateDisplay(go,item,view);var holder=actor(item.holder_id);
                if(item.id=="medical")
                {
                    var patient=actor("mother");go.transform.position=patient!=null?patient.transform.position+new Vector3(.55f,.03f,.12f):ObjectPoint(view,"oxygen");
                }
                else if(!string.IsNullOrEmpty(item.connected_to))
                {
                    string target=item.connected_to=="medical"?"medical":item.connected_to;
                    var device=Get(target)??obj(target);
                    go.transform.position=device!=null?device.transform.position+new Vector3(.43f,.03f,0):ObjectPoint(view,"backup_supply");
                }
                else if(holder!=null)
                {
                    string socket=used.Add(holder.Id)?(item.id=="stretcher"?"carry_front":"hand_r"):"stow";
                    Bind(item.id,holder.Socket(socket));holder.SetHolding(socket,true);
                }
                else
                {
                    string target=item.id=="stretcher"?"stretcher_rack":"tool_rack";
                    go.transform.position=ObjectPoint(view,target)+new Vector3(item.id=="lamp"?.2f:item.id=="spares"?.6f:-.3f,.75f,0);
                }
                if(item.id=="stretcher")go.transform.localScale=item.visual_state=="unfolded"||item.state=="prepared"||item.state=="deployed"?Vector3.one:new Vector3(.75f,.45f,1);
                go.transform.rotation=holder!=null&&string.IsNullOrEmpty(item.connected_to)?go.transform.rotation:Quaternion.identity;
            }
            EnsureToolParts();
            UpdateCable(view,obj);
        }
        void UpdateDisplay(GameObject go,ItemView item,GameView view)
        {
            if(item.id!="backup"&&item.id!="medical")return;
            bool external=item.id=="medical"&&item.connected_to=="backup";
            int power=external?(view.inventory??Array.Empty<ItemView>()).FirstOrDefault(i=>i.id=="backup")?.charge??0:item.charge;
            var panel=go.transform.Find("LivePowerDisplay");
            if(panel==null)panel=WorldGeometry.Box(go.transform,"LivePowerDisplay",new Vector3(0,.28f,.126f),new Vector3(.205f,.10f,.018f),WorldGeometry.Dark).transform;
            var text=go.transform.Find("LivePowerText");
            var label=text==null?WorldGeometry.Label(go.transform,"",new Vector3(0,.28f,.14f),.55f,WorldGeometry.Green):text.GetComponent<TMPro.TextMeshPro>();
            label.name="LivePowerText";label.gameObject.name="LivePowerText";label.transform.localRotation=Quaternion.Euler(0,180,0);
            label.text=power<=0?"断电":external?"外接":item.charge.ToString();
            label.color=power>0?WorldGeometry.Green:WorldGeometry.Warning;
            panel.GetComponent<Renderer>().sharedMaterial=WorldGeometry.Mat(power>0?WorldGeometry.Dark:WorldGeometry.Steel);
        }
        void EnsureToolParts()
        {
            var bag=Get("tools");if(bag==null)return;
            foreach(string id in new[]{"meter","driver"})
                if(!toolParts.ContainsKey(id))
                {
                    var part=UnityEngine.Object.Instantiate(PresentationAssets.Required.Prop(id),bag.transform,false);
                    part.name="ToolPart_"+id;part.SetActive(false);toolParts[id]=part;
                }
        }
        public void PresentTool(string id,TrainActor actor)
        {
            EnsureToolParts();if(actor==null||!toolParts.TryGetValue(id,out var part))return;
            part.SetActive(true);part.transform.SetParent(actor.Socket("hand_r"),false);
            part.transform.localPosition=Vector3.zero;part.transform.localRotation=Quaternion.identity;
        }
        public void StowTools()
        {
            var bag=Get("tools");
            foreach(var part in toolParts.Values)if(part!=null)
            {part.transform.SetParent(bag!=null?bag.transform:root,false);part.SetActive(false);}
        }
        static int Priority(string id)=>id=="medical"?0:id=="backup"?1:id=="stretcher"?2:3;
        static Vector3 ObjectPoint(GameView view,string id)
        {var o=(view.objects??Array.Empty<ObjectView>()).FirstOrDefault(x=>x.id==id);return o==null?Vector3.zero:new Vector3(o.x,0,o.z);}
        public void Bind(string id,Transform target)
        {var go=Get(id);if(go==null||target==null)return;go.transform.SetParent(target,false);go.transform.localPosition=Vector3.zero;go.transform.localRotation=Quaternion.identity;}
        public void Move(string id,Vector3 world){var go=Get(id);if(go==null)return;go.transform.SetParent(root,true);go.transform.position=world;}
        public void UpdateCable(GameView view,Func<string,GameObject> obj)
        {
            var supply=(view.inventory??Array.Empty<ItemView>()).FirstOrDefault(i=>i.id=="backup");
            var source=Get("backup");GameObject target=null;
            if(supply!=null)target=supply.connected_to=="medical"?Get("medical"):supply.connected_to=="radio"?obj("radio"):null;
            if(cable==null)
            {
                cable=new GameObject("Connection_backup");cable.transform.SetParent(root,false);
                var line=cable.AddComponent<LineRenderer>();line.positionCount=7;line.startWidth=line.endWidth=.017f;
                line.material=WorldGeometry.Mat(WorldGeometry.Dark);line.useWorldSpace=true;
            }
            cable.SetActive(source!=null&&source.activeInHierarchy&&target!=null&&target.activeInHierarchy);
            if(!cable.activeSelf)return;
            var renderer=cable.GetComponent<LineRenderer>();
            var output=PresentationSockets.Find(source,"power_out");
            var input=PresentationSockets.Find(target,supply.connected_to=="medical"?"medical_power":"radio_power");
            Vector3 a=output!=null?output.position:source.transform.position+Vector3.up*.19f,b=input!=null?input.position:target.transform.position+Vector3.up*.23f;
            for(int i=0;i<7;i++){float t=i/6f;renderer.SetPosition(i,Vector3.Lerp(a,b,t)-Vector3.up*Mathf.Sin(t*Mathf.PI)*.08f);}
        }
        public void Validate()
        {
            foreach(var group in root.parent.GetComponentsInChildren<WorldItemIdentity>(true).GroupBy(i=>i.id))
                if(group.Count(i=>i.gameObject.activeInHierarchy)>1)throw new InvalidOperationException("Duplicate visible item: "+group.Key);
        }
    }
}
