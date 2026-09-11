using System;
using System.Collections;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using UnityEngine;

namespace LastLight.QA
{
    public sealed partial class PlayerCapture : MonoBehaviour
    {
        string inputDirectory, outputDirectory;
        LastLightApp app;
        TrainWorld world;
        GameView performanceBefore;
        readonly List<Sample> samples = new List<Sample>();
        readonly List<Assertion> assertions = new List<Assertion>();
        readonly List<string> screenshots = new List<string>();
        readonly List<FrameRecord> frameRecords = new List<FrameRecord>();
        readonly HashSet<string> consoleErrors = new HashSet<string>();
        int sequenceCount, performanceCount;
        bool finishing,captureAborted;
        readonly string runId=Guid.NewGuid().ToString("N");
        [Serializable] public sealed class Sequence
        { public string id, operation, source; public GameView before; public ExecutionView execution; public GameView after; }
        [Serializable] public sealed class PerformanceFixture
        { public string id, source; public GameView before; public DialogueLine line; }
        [Serializable] public sealed class Sample
        { public string name; public int frames; public float mean_frame_ms, p95_frame_ms; }
        [Serializable] public sealed class Assertion
        { public string name, detail; public bool passed; }
        [Serializable] public sealed class FrameRecord
        { public string file; public float realtime, presentation_time; }
        [Serializable] public sealed class Report
        {
            public string kind = "Actual Unity Player capture of deterministic fixtures. Performance events use a local QA sink; not a server or live model test.";
            public string unity, platform, gpu, cpu, error;
            public string run_id;
            public int width, height, memory_mb, sequences, performances;
            public bool passed;
            public Sample[] samples;
            public Assertion[] assertions;
            public string[] console_errors, screenshots;
            public FrameRecord[] frames;
            public PerformanceTrace[] performance_trace;
            public PlaybackEventLog[] playback_events;
        }
        [RuntimeInitializeOnLoadMethod(RuntimeInitializeLoadType.AfterSceneLoad)]
        static void StartIfRequested()
        {
            var args = Environment.GetCommandLineArgs();
            int input = Array.IndexOf(args, "--qa-capture"), output = Array.IndexOf(args, "--qa-output");
            if (input < 0) return;
            var capture = new GameObject("LastLight Windows QA").AddComponent<PlayerCapture>();
            capture.inputDirectory = input + 1 < args.Length ? Path.GetFullPath(args[input + 1]) : "";
            capture.outputDirectory = output >= 0 && output + 1 < args.Length ? Path.GetFullPath(args[output + 1]) : Path.Combine(Application.persistentDataPath, "qa");
            Application.logMessageReceived += capture.RecordConsole;
            capture.StartCoroutine(capture.RunGuarded());
        }
        void RecordConsole(string message, string trace, LogType type)
        {
            if (type == LogType.Error || type == LogType.Exception || type == LogType.Assert)
                consoleErrors.Add(message + "\n" + trace);
        }
        void Check(bool passed, string name, string detail = "")
        { assertions.Add(new Assertion { name = name, passed = passed, detail = detail }); }
        void Validate(GameView expected, string label)
        {
            try { var issues = world.ValidatePresentation(expected); Check(issues.Length == 0, label, string.Join("; ", issues)); }
            catch (Exception error) { Check(false, label, error.Message); }
        }
        void Show(GameView snapshot)
        {
            app.CaptureOpenView(snapshot); world.SetInputBlocked(true); Canvas.ForceUpdateCanvases();
        }
        void Finish(string error = "")
        {
            if (finishing) return; finishing = true;
            Application.logMessageReceived -= RecordConsole;
            var report = new Report
            {
                unity = Application.unityVersion, platform = Application.platform.ToString(), gpu = SystemInfo.graphicsDeviceName,
                run_id = runId,
                cpu = SystemInfo.processorType, memory_mb = SystemInfo.systemMemorySize, width = Screen.width, height = Screen.height,
                error = error, sequences = sequenceCount, performances = performanceCount,
                passed = string.IsNullOrEmpty(error) && consoleErrors.Count == 0 && assertions.Count > 0 && assertions.All(a => a.passed),
                samples = samples.ToArray(), assertions = assertions.ToArray(), console_errors = consoleErrors.ToArray(), screenshots = screenshots.ToArray(),
                frames = frameRecords.ToArray(),
                performance_trace = app == null ? Array.Empty<PerformanceTrace>() : app.Performance.Traces.ToArray(),
                playback_events = app == null ? Array.Empty<PlaybackEventLog>() : app.PlaybackEvents.ToArray()
            };
            File.WriteAllText(Path.Combine(outputDirectory, "qa-report.json"), JsonUtility.ToJson(report, true));
            Debug.Log("[LAST_LIGHT_PLAYER_QA] " + (report.passed ? "validated" : "failed") + " " + outputDirectory);
            Application.Quit(report.passed ? 0 : 2);
        }
    }
}
