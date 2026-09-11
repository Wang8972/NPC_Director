using UnityEngine;

namespace LastLight
{
    public static class Bootstrap
    {
        [RuntimeInitializeOnLoadMethod(RuntimeInitializeLoadType.AfterSceneLoad)]
        public static void StartGame()
        {
            if (Object.FindAnyObjectByType<LastLightApp>() == null)
                new GameObject("Last Light — 余灯").AddComponent<LastLightApp>();
        }
    }
}
