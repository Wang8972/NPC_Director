using System;
using System.Collections;
using System.Collections.Generic;
using System.Text;
using UnityEngine;
using UnityEngine.Networking;

namespace LastLight
{
    public sealed class LastLightClient : MonoBehaviour
    {
        public string Endpoint { get; set; } = "http://127.0.0.1:8765";
        public int TimeoutSeconds { get; set; } = 25;
        readonly HashSet<UnityWebRequest> requests = new HashSet<UnityWebRequest>();

        public Coroutine Get(string path, Action<ApiResponse> done) => StartCoroutine(Request("GET", path, null, done));
        public Coroutine Post(string path, object body, Action<ApiResponse> done) => StartCoroutine(Request("POST", path, body == null ? "{}" : JsonUtility.ToJson(body), done));

        IEnumerator Request(string method, string path, string json, Action<ApiResponse> done)
        {
            // Local model credentials never enter the Unity process or its save data.
            if (!IsLoopbackEndpoint(Endpoint))
            {
                done?.Invoke(new ApiResponse { error = "服务地址必须是本机 HTTP 地址（127.0.0.1 或 localhost）。", network_error = true });
                yield break;
            }
            using (var request = new UnityWebRequest(Endpoint.TrimEnd('/') + path, method))
            {
                request.downloadHandler = new DownloadHandlerBuffer();
                if (json != null)
                {
                    request.uploadHandler = new UploadHandlerRaw(Encoding.UTF8.GetBytes(json));
                    request.SetRequestHeader("Content-Type", "application/json; charset=utf-8");
                }
                request.SetRequestHeader("Accept", "application/json");
                request.timeout = path == "/health" ? 3 : TimeoutSeconds;
                requests.Add(request);
                yield return request.SendWebRequest();
                requests.Remove(request);
                ApiResponse result = null;
                string raw = request.downloadHandler == null ? "" : request.downloadHandler.text;
                if (!string.IsNullOrWhiteSpace(raw))
                {
                    try { result = JsonUtility.FromJson<ApiResponse>(raw); }
                    catch (Exception) { /* Return the bounded, readable error below. */ }
                }
                if (result == null) result = new ApiResponse();
                result.http_status = request.responseCode;
                if (request.result != UnityWebRequest.Result.Success)
                {
                    result.ok = false;
                    result.network_error = request.result == UnityWebRequest.Result.ConnectionError;
                    if (string.IsNullOrEmpty(result.error))
                        result.error = result.network_error ? "未连接到本机救援服务。请检查后台是否启动，然后重试。" : "服务未接受这次操作（HTTP " + request.responseCode + "）。请刷新当前进度。";
                }
                else if (path == "/health")
                {
                    result.ok = result.app_id == "last-light";
                    if(!result.ok)result.error="此端口正由其他本机服务使用。请在连接设置中改用空闲端口（例如 8766）。";
                }
                else if (!result.ok && string.IsNullOrEmpty(result.error)) result.error = "服务返回了无法识别的结果；世界状态尚未确认。";
                if(path=="/health"&&!result.network_error&&result.app_id!="last-light")
                {
                    result.ok=false;
                    result.error="此地址不是余灯服务，端口可能已被其他应用占用。请在连接设置中改用空闲端口（例如 8766）。";
                }
                done?.Invoke(result);
            }
        }

        public static bool IsLoopbackEndpoint(string value)
        {
            return Uri.TryCreate(value, UriKind.Absolute, out var uri) && uri.Scheme == "http" &&
                (uri.Host == "127.0.0.1" || uri.Host == "localhost" || uri.Host == "::1") &&
                uri.AbsolutePath.Trim('/') == "" && string.IsNullOrEmpty(uri.Query) && string.IsNullOrEmpty(uri.UserInfo);
        }

        void OnDestroy()
        {
            foreach (var request in requests) request.Abort();
            requests.Clear();
        }
    }
}
