"""Label and assemble Blender asset renders; never mark these as Player captures."""
from pathlib import Path
import json
from PIL import Image, ImageDraw, ImageFont
ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'artifacts/presentation'
FONT=ROOT/'Assets/LastLight/Resources/Fonts/Chinese.otf'
def font(size):return ImageFont.truetype(str(FONT),size)
def sheet(entries,target,columns,tile=(320,400),title=''):
    rows=(len(entries)+columns-1)//columns
    image=Image.new('RGB',(columns*tile[0],rows*tile[1]+105),(11,25,32));draw=ImageDraw.Draw(image)
    draw.text((24,15),title,font=font(28),fill='#e1b67a')
    draw.text((24,59),'Blender 资产预览 · 非 Unity Player 截图',font=font(17),fill='#92a5ab')
    for index,(path,label) in enumerate(entries):
        x=(index%columns)*tile[0];y=(index//columns)*tile[1]+100
        frame=Image.open(path).convert('RGB');frame.thumbnail((tile[0]-12,tile[1]-45))
        image.paste(frame,(x+(tile[0]-frame.width)//2,y))
        draw.text((x+18,y+tile[1]-38),label,font=font(20),fill='#d6dedb')
    image.save(target)
people=[('player','玩家'),('lin','林岚'),('zhou','周屿'),('chen','陈默'),('xu','许宁'),('mother','许母'),('xiaoman','小满'),('passenger05','05 乘客'),('passenger07','07 乘客')]
sheet([(OUT/(id+'.png'),name) for id,name in people],OUT/'characters.png',3,title='余灯 / 人物资产')
sheet([(OUT/(id+'.png'),name) for id,name in people if id in ('lin','zhou','chen','xu')],OUT/'main-cast.png',4,tile=(240,360),title='余灯 / 四位主要人物')
faces=[('neutral','平静'),('happy','喜悦'),('sad','难过'),('angry','愤怒'),('surprised','惊讶'),('relieved_smile','释然'),('concerned','担忧'),('stern','严肃'),('suspicious','疑虑')]
sheet([(OUT/'faces'/(id+'.png'),name) for id,name in faces],OUT/'expressions.png',3,tile=(320,345),title='9 种表情 / 可连续调节强度')
for folder,name,ms in [(OUT/'turntable','turntable',100)]+[(p,p.name,133) for p in sorted((OUT/'motions').iterdir()) if p.is_dir()]:
    frames=[]
    for path in sorted(folder.glob('*.png')):
        frame=Image.open(path).convert('RGB');draw=ImageDraw.Draw(frame)
        draw.rectangle((0,0,frame.width,35),fill='#0b1920');draw.text((10,6),'Blender / '+name,font=font(15),fill='#d8b17b')
        frames.append(frame)
    if frames:frames[0].save(OUT/(name+'.gif'),save_all=True,append_images=frames[1:],duration=ms,loop=0,optimize=False)
print(json.dumps({'kind':'labelled Blender assets','sheets':['characters.png','expressions.png'],'animations':[p.name for p in OUT.glob('*.gif')]}))
