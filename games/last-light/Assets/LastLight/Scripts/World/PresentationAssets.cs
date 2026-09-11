using System;
using System.Linq;
using UnityEngine;

namespace LastLight
{
    [CreateAssetMenu(menuName="Last Light/Presentation assets")]
    public sealed class PresentationAssets : ScriptableObject
    {
        [Serializable] public sealed class Model { public string id; public GameObject prefab; }
        [Serializable] public sealed class Motion { public string id; public AnimationClip clip; public float duration; public bool loop; public float contact=.55f,release=.78f; }
        public Model[] characters=Array.Empty<Model>(),props=Array.Empty<Model>();
        public Motion[] motions=Array.Empty<Motion>();
        static PresentationAssets cached;
        public static PresentationAssets Required
        {
            get
            {
                if(cached==null)cached=Resources.Load<PresentationAssets>("Presentation/Assets");
                if(cached==null)throw new InvalidOperationException("Missing Last Light presentation assets. Run Last Light > Import art; primitive fallback is disabled.");
                return cached;
            }
        }
        public GameObject Character(string id)=>characters.FirstOrDefault(m=>m.id==id)?.prefab
            ??throw new InvalidOperationException("Missing character asset: "+id);
        public GameObject Prop(string id)=>props.FirstOrDefault(m=>m.id==id)?.prefab
            ??throw new InvalidOperationException("Missing prop asset: "+id);
        public Motion Clip(string id)=>motions.FirstOrDefault(m=>m.id==id)
            ??throw new InvalidOperationException("Missing animation: "+id);
    }
}
