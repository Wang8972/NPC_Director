"""Encode actual Player frames using their capture timestamps; no synthetic gameplay."""
from __future__ import annotations
import argparse,json,re,subprocess
from pathlib import Path

def encode(directory:Path):
    from imageio_ffmpeg import get_ffmpeg_exe
    report=json.loads((directory/'qa-report.json').read_text(encoding='utf-8'))
    groups={}
    for frame in report.get('frames',[]):
        name=Path(frame['file']).name
        # Group a preparation and its result together; static before/after shots are not sampled videos.
        match=re.match(r'(.+?)(?:-(?:prepare|result))?-\d{3}\.png$',name)
        if match:groups.setdefault(match.group(1),[]).append(frame)
    outputs=[]
    for name,frames in groups.items():
        frames.sort(key=lambda f:f['realtime'])
        if len(frames)<2:continue
        lines=['ffconcat version 1.0']
        for index,frame in enumerate(frames):
            path=Path(frame['file'])
            if not path.is_absolute():path=directory/path
            if not path.is_file():raise FileNotFoundError(path)
            escaped=path.resolve().as_posix().replace("'", "'\\''")
            lines.append("file '"+escaped+"'")
            duration=(frames[index+1]['realtime']-frame['realtime']) if index+1<len(frames) else .2
            lines.append(f'duration {max(.01,duration):.6f}')
        lines.append(lines[-2])
        concat=directory/(name+'.ffconcat');concat.write_text('\n'.join(lines)+'\n',encoding='utf-8')
        target=directory/(name+'.mp4')
        subprocess.run([get_ffmpeg_exe(),'-hide_banner','-loglevel','error','-y','-safe','0','-f','concat','-i',str(concat),
            '-vf','pad=ceil(iw/2)*2:ceil(ih/2)*2','-c:v','libx264','-pix_fmt','yuv420p','-movflags','+faststart',str(target)],check=True)
        outputs.append({'file':target.name,'source_frames':len(frames),'source':'actual Player capture timestamps'})
    if not outputs:raise RuntimeError('No sampled Player frame sequences; screenshots alone are not video evidence.')
    (directory/'video-manifest.json').write_text(json.dumps({'kind':'encoded actual Player capture, not live AI validation','videos':outputs},indent=2)+'\n')
    print(json.dumps({'videos':len(outputs),'directory':str(directory)}))

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('directory',type=Path);encode(parser.parse_args().directory)
