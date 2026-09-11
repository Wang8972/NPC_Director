using System.Collections.Generic;
using UnityEngine;

namespace LastLight
{
    public sealed class TrainAmbience : MonoBehaviour
    {
        AudioSource ambience,mechanical,oneShot,music;
        readonly Dictionary<string,AudioClip> clips=new Dictionary<string,AudioClip>();
        float volume=.65f;
        public void Initialize()
        {
            ambience=Source(true);mechanical=Source(true);oneShot=Source(false);music=Source(true);
            foreach(string name in new[]{"ambient","tunnel","electrical","click","alert","resolve","brake","door","footstep","tools","music"})
            { var clip=Resources.Load<AudioClip>("Audio/"+name);if(clip!=null)clips[name]=clip; }
            if(clips.TryGetValue("music",out var score)){music.clip=score;music.volume=volume*.13f;music.Play();}
            SetScene("cabin07",0,false);
        }
        AudioSource Source(bool loop){var s=gameObject.AddComponent<AudioSource>();s.loop=loop;s.playOnAwake=false;s.spatialBlend=0;return s;}
        public void SetVolume(float value){volume=Mathf.Clamp01(value);if(ambience!=null)ambience.volume=volume*.44f;if(mechanical!=null)mechanical.volume=volume*.13f;if(music!=null)music.volume=volume*.13f;}
        public void SetScene(string room,int smoke,bool ended)
        {
            string key=room=="tunnel"?"tunnel":"ambient";
            if(clips.TryGetValue(key,out var clip)&&ambience.clip!=clip){ambience.clip=clip;ambience.volume=volume*.44f;ambience.Play();}
            if(room=="service"&&smoke>0&&clips.TryGetValue("electrical",out var hum))
            {if(mechanical.clip!=hum||!mechanical.isPlaying){mechanical.clip=hum;mechanical.volume=volume*.13f;mechanical.Play();}}
            else mechanical.Stop();
            if(ended)mechanical.Stop();
        }
        public void Cue(string key){if(oneShot!=null&&clips.TryGetValue(key,out var clip))oneShot.PlayOneShot(clip,volume*.65f);}
    }
}
