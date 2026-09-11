using System;

namespace LastLight
{
    /// <summary>One cosmetic clock. Only LastLightApp.Update advances it; world time stays server-owned.</summary>
    public static class PresentationClock
    {
        public static float Delta { get; private set; }
        public static float Elapsed { get; private set; }
        public static bool Paused { get; set; }
        public static long Ticks { get; private set; }
        public static void Tick(float unscaledDelta)
        {
            Delta = Paused || float.IsNaN(unscaledDelta) || float.IsInfinity(unscaledDelta)
                ? 0 : Math.Max(0, Math.Min(.1f, unscaledDelta));
            Elapsed += Delta; Ticks++;
        }
        public static void Reset()
        {
            Delta=0;Elapsed=0;Ticks=0;Paused=false;
        }
    }
}
