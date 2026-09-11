using System;
using System.Collections;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using UnityEngine;

namespace LastLight.QA
{
    public sealed partial class PlayerCapture
    {
        IEnumerator RunPhase(string name,IEnumerator phase)
        {
            bool running=true;int startCount=screenshots.Count;
            var capture=StartCoroutine(CaptureFrames(name,()=>running));
            Exception failure=null;float deadline=Time.realtimeSinceStartup+45;
            yield return PresentationRoutine.Run(phase,()=>Time.realtimeSinceStartup>deadline,error=>failure=error);
            running=false;StopCoroutine(capture);
            Check(failure==null&&Time.realtimeSinceStartup<=deadline,name+":completed",failure?.Message??"");
            yield return Shot(name+"-end");
            Check(screenshots.Count>startCount,name+":frames");
        }
        IEnumerator CaptureFrames(string name,Func<bool> alive)
        {
            int index=0;float next=0;
            // Independent from the action iterator: nested movement and transfer routines are captured too.
            while(!captureAborted&&alive()&&index<160)
            {
                yield return new WaitForEndOfFrame();
                if(Time.realtimeSinceStartup>=next)
                {
                    Capture(name+"-"+index.ToString("000"));index++;
                    next=Time.realtimeSinceStartup+.2f;
                }
                yield return null;
            }
        }
        IEnumerator Shot(string name)
        {
            yield return new WaitForEndOfFrame();Capture(name);yield return null;
        }
        void Capture(string name)
        {
            foreach(char invalid in Path.GetInvalidFileNameChars())name=name.Replace(invalid,'_');
            string path=Path.Combine(outputDirectory,name+".png");
            try{if(File.Exists(path))File.Delete(path);}
            catch(IOException error){Check(false,"replace_old_screenshot",error.Message);return;}
            ScreenCapture.CaptureScreenshot(path);screenshots.Add(path);
            frameRecords.Add(new FrameRecord{file=path,realtime=Time.realtimeSinceStartup,presentation_time=PresentationClock.Elapsed});
        }
        IEnumerator Measure(string name)
        {
            var frameTimes=new List<float>();
            for(int i=0;i<60;i++){yield return null;frameTimes.Add(Time.unscaledDeltaTime*1000);}
            var sorted=frameTimes.OrderBy(v=>v).ToArray();
            samples.Add(new Sample{name=name,frames=sorted.Length,mean_frame_ms=frameTimes.Average(),p95_frame_ms=sorted[(int)(sorted.Length*.95f)-1]});
        }
        IEnumerator WaitForWrittenFrames()
        {
            float deadline=Time.realtimeSinceStartup+15;
            while(Time.realtimeSinceStartup<deadline&&!screenshots.All(IsCompletePng))
                yield return new WaitForSecondsRealtime(.1f);
        }
        static bool IsCompletePng(string path)
        {
            try
            {
                using(var stream=new FileStream(path,FileMode.Open,FileAccess.Read,FileShare.ReadWrite))
                {
                    if(stream.Length<57)return false;
                    byte[] signature={137,80,78,71,13,10,26,10};
                    foreach(byte expected in signature)if(stream.ReadByte()!=expected)return false;
                    stream.Seek(-12,SeekOrigin.End);
                    byte[] end={0,0,0,0,73,69,78,68,174,66,96,130};
                    foreach(byte expected in end)if(stream.ReadByte()!=expected)return false;
                    return true;
                }
            }
            catch(IOException){return false;}
            catch(UnauthorizedAccessException){return false;}
        }
        IEnumerator RunGuarded()
        {
            var stack=new Stack<IEnumerator>();stack.Push(Run());
            Exception failure=null;float deadline=Time.realtimeSinceStartup+1200;
            try
            {
                while(stack.Count>0&&!finishing)
                {
                    if(Time.realtimeSinceStartup>deadline){failure=new TimeoutException("Player QA exceeded its deadline.");break;}
                    var step=stack.Peek();bool next=false;
                    try{next=step.MoveNext();}catch(Exception error){failure=error;}
                    if(failure!=null)break;
                    if(!next){(stack.Pop() as IDisposable)?.Dispose();continue;}
                    if(step.Current is IEnumerator nested){stack.Push(nested);continue;}
                    yield return step.Current;
                }
            }
            finally{while(stack.Count>0)(stack.Pop() as IDisposable)?.Dispose();}
            if(failure!=null)
            {
                captureAborted=true;
                if(!Directory.Exists(outputDirectory))Directory.CreateDirectory(outputDirectory);
                yield return WaitForWrittenFrames();Finish(failure.GetType().Name+": "+failure.Message);
            }
        }
    }
}
