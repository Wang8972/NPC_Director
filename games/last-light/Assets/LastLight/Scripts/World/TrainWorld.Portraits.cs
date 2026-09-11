using System;
using System.Collections.Generic;
using UnityEngine;

namespace LastLight
{
    public sealed partial class TrainWorld
    {
        sealed class PortraitStudio {public GameObject root;public TrainActor actor;public Camera camera;public RenderTexture image;}
        readonly Dictionary<string,PortraitStudio> studios=new Dictionary<string,PortraitStudio>();
        float nextPortraitFrame;
        public Texture Portrait(string id)
        {
            if(portraits.TryGetValue(id??"",out var image))return image;
            if(!actors.ContainsKey(id??""))return Texture2D.grayTexture; // Never manufacture an unseen remote face.
            var holder=new GameObject("Portrait_"+id);holder.transform.SetParent(transform,false);holder.transform.localPosition=new Vector3(studios.Count*4f,-100,0);
            var clone=TrainActor.Create(holder.transform,id,Vector3.zero);clone.enabled=false;clone.transform.localRotation=Quaternion.identity;
            foreach(var collider in clone.GetComponentsInChildren<Collider>())collider.enabled=false;
            foreach(var node in holder.GetComponentsInChildren<Transform>())node.gameObject.layer=30;
            var cg=new GameObject("PortraitCamera");cg.transform.SetParent(holder.transform,false);
            var camera=cg.AddComponent<Camera>();camera.orthographic=true;camera.orthographicSize=.29f;
            camera.clearFlags=CameraClearFlags.SolidColor;camera.backgroundColor=WorldGeometry.Dark;camera.cullingMask=1<<30;
            camera.nearClipPlane=.03f;camera.farClipPlane=5;camera.enabled=false;
            var texture=new RenderTexture(256,256,16){name="Portrait_"+id};texture.Create();camera.targetTexture=texture;
            studios[id]=new PortraitStudio{root=holder,actor=clone,camera=camera,image=texture};portraits[id]=texture;
            return texture;
        }
        void ClearPortraits()
        {
            foreach(var studio in studios.Values){studio.image.Release();Destroy(studio.image);Destroy(studio.root);}
            studios.Clear();portraits.Clear();
        }
        void LateUpdate()
        {
            if(current!=null)
            {
                foreach(var data in current.actors??Array.Empty<ActorView>())
                    if(actors.TryGetValue(data.id,out var actor))
                        actor.BaseAttention=TargetPosition(data.attention_target_id??"",out var at)?at+Vector3.up*.95f:(Vector3?)null;
                items?.UpdateCable(visualConnections??current,Object);
            }
            if(Time.unscaledTime<nextPortraitFrame)return;
            nextPortraitFrame=Time.unscaledTime+(lowQuality?1f/15:1f/30);
            foreach(var pair in studios)
            {
                if(!actors.TryGetValue(pair.Key,out var source))continue; // Last observed image remains frozen.
                var studio=pair.Value;source.CopyPoseTo(studio.actor);
                Vector3 head=studio.actor.Socket("head").position+Vector3.up*.10f;
                studio.camera.transform.position=head+new Vector3(0,.015f,1.8f);studio.camera.transform.LookAt(head);
                if(UnityEngine.Rendering.GraphicsSettings.currentRenderPipeline==null)studio.camera.Render();
                else
                {
                    var request=new UnityEngine.Rendering.Universal.UniversalRenderPipeline.SingleCameraRequest{destination=studio.image};
                    if(UnityEngine.Rendering.RenderPipeline.SupportsRenderRequest(studio.camera,request))
                        UnityEngine.Rendering.RenderPipeline.SubmitRenderRequest(studio.camera,request);
                }
            }
        }
    }
}
