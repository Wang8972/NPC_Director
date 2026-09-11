using System;
using System.Linq;
using UnityEngine;

namespace LastLight
{
    public static class PresentationSockets
    {
        [Serializable] public sealed class Entry {public string id,owner,bone;public float x,y,z;}
        [Serializable] public sealed class Catalog {public Entry[] sockets;}
        static Catalog catalog;
        public static Entry[] All
        {
            get
            {
                if(catalog==null)
                {
                    var text=Resources.Load<TextAsset>("Presentation/Sockets");
                    if(text==null)throw new InvalidOperationException("Missing socket catalog");
                    catalog=JsonUtility.FromJson<Catalog>(text.text);
                }
                return catalog.sockets;
            }
        }
        public static void Attach(GameObject root,string owner)
        {
            foreach(var entry in All.Where(e=>e.owner==owner))
            {
                if(root.GetComponentsInChildren<Transform>().Any(t=>t.name=="Socket_"+entry.id))continue;
                var parent=string.IsNullOrEmpty(entry.bone)?root.transform:
                    root.GetComponentsInChildren<Transform>().FirstOrDefault(t=>t.name==entry.bone);
                if(parent==null)throw new InvalidOperationException(owner+" missing socket bone "+entry.bone);
                var go=new GameObject("Socket_"+entry.id);go.transform.SetParent(parent,false);
                go.transform.localPosition=new Vector3(entry.x,entry.y,entry.z);
            }
        }
        public static Transform Find(GameObject root,string id)=>root==null?null:root.GetComponentsInChildren<Transform>().FirstOrDefault(t=>t.name=="Socket_"+id);
    }
}
