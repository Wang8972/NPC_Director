using System;
using System.Collections;
using System.IO;
using System.Linq;
using UnityEngine;

namespace LastLight.QA
{
    public sealed partial class PlayerCapture
    {
        IEnumerator RunPerformanceCases()
        {
            foreach(string file in Directory.GetFiles(inputDirectory,"*.performance.json").OrderBy(f=>f))
            {
                PerformanceFixture fixture=null;Exception error=null;
                try{fixture=JsonUtility.FromJson<PerformanceFixture>(File.ReadAllText(file));}
                catch(Exception exception){error=exception;}
                if(error!=null||fixture?.before==null||fixture.line==null){Check(false,"performance_fixture",file);continue;}
                yield return RunLineFixture(fixture,false,false,false);
            }
            if(performanceBefore==null){Check(false,"performance_baseline_present");yield break;}
            var actor=performanceBefore.actors.First(a=>a.id=="lin");
            foreach(string face in PerformanceTimeline.Faces)
            {
                var p=PresentationContractChecks.Base();
                p.face_cues=new[]{new FaceCueView{preset=face,intensity=.85f,start_ms=0,duration_ms=900}};
                yield return RunLineFixture(MakePerformance("face-"+face,actor,p),face=="neutral",false,false);
            }
            int index=0;
            foreach(string action in PerformanceTimeline.Actions)
            {
                var p=PresentationContractChecks.Base();
                p.body_cues=new[]{new BodyCueView{action=action,layer=PerformanceTimeline.Layers[index++%3],priority=50,start_ms=0}};
                yield return RunLineFixture(MakePerformance("body-"+action,actor,p),false,false,false);
            }
            foreach(string target in PerformanceTimeline.GazeTargets)
                foreach(string mode in PerformanceTimeline.GazeModes)
                {
                    var p=PresentationContractChecks.Base();p.gaze=new GazeView{target=target,mode=mode};
                    yield return RunLineFixture(MakePerformance("gaze-"+target+"-"+mode,actor,p),false,false,false);
                }
            var layered=PresentationContractChecks.Base();
            layered.body_cues=new[]{
                new BodyCueView{action="step_forward",layer="full_body",priority=20,start_ms=0},
                new BodyCueView{action="nod",layer="upper_body",priority=30,start_ms=120},
                new BodyCueView{action="small_nod",layer="additive",priority=40,start_ms=200},
                new BodyCueView{action="point",layer="upper_body",priority=90,start_ms=400}};
            yield return RunLineFixture(MakePerformance("layer-priority",actor,layered),false,false,false);
            var interrupt=PresentationContractChecks.Base();
            interrupt.face_cues=new[]{new FaceCueView{preset="concerned",intensity=.8f,duration_ms=3500}};
            yield return RunLineFixture(MakePerformance("interrupted",actor,interrupt),false,true,false);
            yield return RunLineFixture(MakePerformance("explicit-skip",actor,interrupt),false,false,true);
            var remote=PresentationContractChecks.Base();
            remote.face_cues=new[]{new FaceCueView{preset="angry",intensity=1,duration_ms=800}};
            string remoteId=new[]{"chen","xu","zhou","lin"}.FirstOrDefault(id=>!performanceBefore.actors.Any(a=>a.id==id));
            if(remoteId!=null)
                yield return RunLineFixture(MakePerformance("offscreen-static",new ActorView{id=remoteId,name=remoteId=="chen"?"陈默":remoteId=="xu"?"许宁":remoteId=="zhou"?"周屿":"林岚"},remote),false,false,false);
            else Check(false,"offscreen_fixture_available");
        }
        PerformanceFixture MakePerformance(string id,ActorView actor,PerformanceView performance)
        {
            performance.npc_id=actor.id;performance.turn_id="qa-"+id;performance.session_id=performanceBefore.session_id;
            return new PerformanceFixture{id="qa-"+id,source="synthetic QA, no model call",before=performanceBefore,
                line=new DialogueLine{id="qa-"+id,npc_id=actor.id,speaker=actor.name,source="synthetic",
                    text=performance.dialogue.text,performance=performance}};
        }
    }
}
