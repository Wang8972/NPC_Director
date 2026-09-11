using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.IO;
using UnityEngine;

namespace LastLight
{
    /// <summary>Starts only the packaged local service. It never installs Python or modifies credentials.</summary>
    public sealed class BackendLauncher : MonoBehaviour
    {
        Process process;
        string runningEndpoint = "";
        readonly Queue<string> tail = new Queue<string>();
        readonly object logLock = new object();
        public string Status { get; private set; } = "尚未启动";
        public bool OwnsProcess => process != null;

        public string RecentOutput
        {
            get { lock (logLock) return string.Join("\n", tail.ToArray()); }
        }

        public bool TryStart(string endpoint)
        {
            if (process != null)
            {
                try
                {
                    if (!process.HasExited)
                    {
                        if (runningEndpoint == endpoint) { Status = "本机后台正在运行"; return true; }
                        process.Kill();
                    }
                }
                catch (InvalidOperationException) { }
                process.Dispose(); process = null;
            }
            if (!LastLightClient.IsLoopbackEndpoint(endpoint)) { Status = "只允许启动本机后台"; return false; }
            var root = FindProjectRoot();
            if (root == null) { Status = "未找到 backend 目录。请使用完整发行包，或按 README 启动后台。"; return false; }
            var backend = Path.Combine(root, "backend");
            var exe = FindPython(root);
            var uri = new Uri(endpoint);
            var packaged = Path.Combine(root, "runtime", "last-light-server.exe");
            var runner = Path.Combine(root, "tools", "run_server.py");
            var arguments = "-m uvicorn last_light.api:app --host 127.0.0.1 --port " + uri.Port;
            if (File.Exists(packaged)) { exe = packaged; arguments = "--host 127.0.0.1 --port " + uri.Port; }
            else if (File.Exists(runner)) arguments = "\"" + runner + "\" --host 127.0.0.1 --port " + uri.Port;
            var start = new ProcessStartInfo
            {
                FileName = exe,
                Arguments = arguments,
                WorkingDirectory = Directory.Exists(backend) ? backend : root,
                UseShellExecute = false, CreateNoWindow = true,
                RedirectStandardOutput = true, RedirectStandardError = true
            };
            start.EnvironmentVariables["PYTHONUNBUFFERED"] = "1";
            start.EnvironmentVariables["PYTHONIOENCODING"] = "utf-8";
            try
            {
                process = new Process { StartInfo = start, EnableRaisingEvents = true };
                process.OutputDataReceived += CaptureOutput;
                process.ErrorDataReceived += CaptureOutput;
                if (!process.Start()) { Status = "后台进程未能启动"; process.Dispose(); process = null; return false; }
                process.BeginOutputReadLine(); process.BeginErrorReadLine();
                runningEndpoint = endpoint;
                Status = "后台正在启动";
                return true;
            }
            catch (Exception error)
            {
                Status = "无法启动本机后台：" + error.Message;
                if (process != null) process.Dispose();
                process = null; return false;
            }
        }

        void CaptureOutput(object sender, DataReceivedEventArgs data)
        {
            if (string.IsNullOrWhiteSpace(data.Data)) return;
            // The UI uses this only as a short local diagnostic; never dump environment variables.
            var line = data.Data.Length > 360 ? data.Data.Substring(0, 360) : data.Data;
            lock (logLock) { tail.Enqueue(line); while (tail.Count > 5) tail.Dequeue(); }
        }

        static string FindProjectRoot()
        {
            var candidates = new[] { Application.streamingAssetsPath, Application.dataPath, Path.GetDirectoryName(Application.dataPath), Environment.CurrentDirectory };
            foreach (var candidate in candidates)
            {
                if (string.IsNullOrEmpty(candidate)) continue;
                var directory = new DirectoryInfo(candidate);
                for (int i = 0; directory != null && i < 4; i++, directory = directory.Parent)
                    if (Directory.Exists(Path.Combine(directory.FullName, "backend", "last_light")) || File.Exists(Path.Combine(directory.FullName, "runtime", "last-light-server.exe"))) return directory.FullName;
            }
            return null;
        }

        static string FindPython(string root)
        {
            var configured = PlayerPrefs.GetString("lastlight.python", "");
            if (!string.IsNullOrEmpty(configured) && File.Exists(configured)) return configured;
            var paths = new[] { "runtime/python/python.exe", "runtime/python/bin/python3", "backend/.venv/Scripts/python.exe", "backend/.venv/bin/python", ".venv/Scripts/python.exe", ".venv/bin/python", "../npc-director/.venv/Scripts/python.exe", "../npc-director/.venv/bin/python" };
            foreach (var path in paths) { var full = Path.Combine(root, path); if (File.Exists(full)) return full; }
            return Application.platform == RuntimePlatform.WindowsPlayer || Application.platform == RuntimePlatform.WindowsEditor ? "python" : "python3";
        }

        void OnApplicationQuit()
        {
            // Only the process started by this instance is stopped. An existing external server is untouched.
            if (process == null) return;
            try { if (!process.HasExited) process.Kill(); } catch (Exception) { }
            process.Dispose(); process = null;
        }
    }
}
