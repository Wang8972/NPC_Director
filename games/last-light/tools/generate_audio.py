#!/usr/bin/env python3
"""Deterministic, original procedural sound library. No downloaded recordings."""
from __future__ import annotations
import hashlib
import json
import math
from pathlib import Path
import random
import struct
import wave

ROOT = Path(__file__).resolve().parents[1]
RATE = 22050


def render(name: str, seconds: float, seed: int) -> bytes:
    rng = random.Random(seed)
    count = int(seconds * RATE)
    noise = 0.0
    values = []
    for i in range(count):
        t = i / RATE
        noise = noise * .94 + rng.uniform(-1, 1) * .06
        s = lambda hz: math.sin(2 * math.pi * hz * t)
        fade = min(1., t / .035, (seconds - t) / .08)
        if name == "ambient":
            v = .18*s(55)+.07*s(110)+.025*s(165)+noise*.8
        elif name == "tunnel":
            v = .13*s(38)+.055*s(76)+noise*.9+.025*s(231)
        elif name == "electrical":
            v = .1*s(100)+.035*s(200)+noise*.4
        elif name == "music":
            # A restrained suspended motif with a perfectly looping common period.
            v = sum(.05*math.sin(2*math.pi*f*t)*(0.55+.45*math.sin(2*math.pi*t/16+k))
                    for k,f in enumerate([55,82.5,110,146.6875,220]))
        elif name == "brake":
            v = .18*math.sin(2*math.pi*(620*t-50*t*t))*(1-t/seconds)+noise*1.3
        elif name == "click":
            v = .25*s(720)*math.exp(-t*36)+noise*.2
        elif name == "alert":
            v = .18*s(660)*(1 if (t % .36)<.17 else 0)
        elif name == "resolve":
            v = sum(.1*s(f) for f in [261.63,329.63,392])*math.exp(-t*1.7)
        elif name == "door":
            v = noise*2*math.sin(math.pi*t/seconds)+.14*s(92)*math.exp(-t*9)
        elif name == "footstep":
            v = (noise*3+.17*s(85))*math.exp(-t*20)
        elif name == "tools":
            v = .18*s(1500)*math.exp(-(t%.25)*55)+noise*.7
        else:
            v = 0
        # Periodic long beds need no volume pumping at their loop boundary.
        if name in {"ambient", "tunnel", "electrical", "music"}:
            fade = min(1., t/.015, (seconds-t)/.015)
        values.append(struct.pack("<h", int(max(-.8,min(.8,v*fade))*32767)))
    return b"".join(values)


def main():
    out = ROOT / "Assets/LastLight/Resources/Audio"
    out.mkdir(parents=True, exist_ok=True)
    durations = {"ambient":16,"tunnel":16,"electrical":8,"music":16,"brake":2.4,
                 "click":.12,"alert":.9,"resolve":1.8,"door":.8,"footstep":.22,"tools":1.1}
    manifest=[]
    for index,(name,duration) in enumerate(durations.items()):
        path=out/(name+".wav")
        with wave.open(str(path),"wb") as f:
            f.setparams((1,2,RATE,0,"NONE","not compressed"))
            f.writeframes(render(name,duration,20260911+index))
        manifest.append({"id":name,"seconds":duration,"sample_rate":RATE,
                         "sha256":hashlib.sha256(path.read_bytes()).hexdigest()})
    (out/"manifest.json").write_text(json.dumps({"source":"tools/generate_audio.py",
        "license":"Original project assets; no third-party samples", "clips":manifest},ensure_ascii=False,indent=2)+"\n")
    print(f"Generated {len(manifest)} original WAV assets in {out}")


if __name__=="__main__": main()
