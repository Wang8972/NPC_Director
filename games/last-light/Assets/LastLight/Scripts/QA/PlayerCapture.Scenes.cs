using System;
using System.Collections;
using System.IO;
using System.Linq;
using UnityEngine;

namespace LastLight.QA
{
    public sealed partial class PlayerCapture
    {
        IEnumerator Run()
        {
            Directory.CreateDirectory(outputDirectory);
            string oldReport=Path.Combine(outputDirectory,"qa-report.json");
            if(File.Exists(oldReport))File.Delete(oldReport);
            if(!Directory.Exists(inputDirectory)){Finish("Fixture directory is missing");yield break;}
            foreach(string failure in PresentationContractChecks.Run())Check(false,"contract",failure);
            Check(true,"contract_checks_executed");
            float deadline=Time.realtimeSinceStartup+20;
            while(app==null&&Time.realtimeSinceStartup<deadline)
            {app=UnityEngine.Object.FindAnyObjectByType<LastLightApp>();yield return null;}
            if(app==null){Finish("Game bootstrap failed");yield break;}
            world=app.GetComponent<TrainWorld>();
            if(world==null){Finish("World is missing");yield break;}
            yield return new WaitForSecondsRealtime(.8f);yield return Shot("00-title");
            var views=Directory.GetFiles(inputDirectory,"*.view.json");Array.Sort(views);
            Check(views.Length>0,"fixture_views_present");
            foreach(string file in views)
            {
                GameView snapshot=null;Exception error=null;
                try{snapshot=GameJson.Deserialize<GameView>(File.ReadAllText(file));}
                catch(Exception exception){error=exception;}
                if(error!=null||snapshot==null){Check(false,"parse_view",file);continue;}
                string name=Path.GetFileName(file).Replace(".view.json","");
                Show(snapshot);yield return new WaitForSecondsRealtime(.25f);
                Validate(snapshot,name+":entities");yield return Shot(name);yield return Measure(name);
                if(string.IsNullOrEmpty(snapshot.ending)&&snapshot.actors.Any(a=>a.id=="lin"))
                    if(performanceBefore==null||(snapshot.room_id=="cabin07"&&
                        (performanceBefore.room_id!="cabin07"||snapshot.tick<performanceBefore.tick)))performanceBefore=snapshot;
            }
            var sequences=Directory.GetFiles(inputDirectory,"*.sequence.json");Array.Sort(sequences);
            foreach(string file in sequences)
            {
                Sequence sequence=null;Exception error=null;
                try{sequence=GameJson.Deserialize<Sequence>(File.ReadAllText(file));}
                catch(Exception exception){error=exception;}
                if(error!=null||sequence?.before==null||sequence.execution==null||sequence.after==null)
                {Check(false,"parse_sequence",file);continue;}
                string name=Path.GetFileName(file).Replace(".sequence.json","");sequenceCount++;
                Show(sequence.before);app.CaptureCloseOverlay();yield return Shot(name+"-before");
                int committed=world.PhysicalPresentationCommits;
                yield return RunPhase(name+"-prepare",world.Prepare(sequence.execution));
                Check(world.PhysicalPresentationCommits==committed,name+":prepare_does_not_commit_result");
                Validate(sequence.before,name+":no_early_success");
                bool cancelled=(sequence.operation??"").IndexOf("cancel",StringComparison.OrdinalIgnoreCase)>=0;
                if(cancelled)
                {
                    world.SkipAnimation();world.Apply(sequence.after);
                    Check(world.PhysicalPresentationCommits==committed,name+":cancel_does_not_present_success");
                }
                else
                {
                    yield return RunPhase(name+"-result",world.Resolve(sequence.execution,sequence.before,sequence.after));
                    Check(world.PhysicalPresentationCommits==committed+1,name+":single_result_presentation");
                    yield return PresentationRoutine.Run(world.Resolve(sequence.execution,sequence.before,sequence.after),()=>false,
                        error=>Check(false,name+":duplicate_resolve",error.Message));
                    Check(world.PhysicalPresentationCommits==committed+1,name+":duplicate_result_is_idempotent");
                }
                Show(sequence.after);yield return new WaitForSecondsRealtime(.15f);
                Validate(sequence.after,name+":result");yield return Shot(name+"-after");
            }
            yield return RunPerformanceCases();
            if(performanceBefore!=null)
            {
                Show(performanceBefore);world.SetQuality(true);
                yield return new WaitForSecondsRealtime(.2f);yield return Shot("99-low-quality");
                Validate(performanceBefore,"low_quality:entities");
            }
            yield return WaitForWrittenFrames();
            Check(screenshots.Count>0,"screenshots_present");
            foreach(string file in screenshots)
                Check(IsCompletePng(file),"screenshot_written",Path.GetFileName(file));
            Finish();
        }
    }
}
