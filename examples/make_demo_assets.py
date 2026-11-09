"""Original, clearly labelled demo images; no external media required."""
import json
from pathlib import Path
from PIL import Image, ImageDraw

root=Path(__file__).parent/'generated'
assets=root/'assets'
assets.mkdir(parents=True,exist_ok=True)
colors=[('#173f42','#bce9ba'),('#3a2449','#e9bced'),('#283d60','#b7d8fa'),('#583629','#f0cfa8')]
for i,(background,accent) in enumerate(colors):
    im=Image.new('RGB',(1080,1920),background)
    draw=ImageDraw.Draw(im)
    draw.ellipse((100,260,980,1140),fill=accent)
    draw.rounded_rectangle((290,680,790,1420),radius=90,fill='#f4eee3')
    draw.ellipse((290,620,790,800),fill='#e3bd86')
    draw.rectangle((480,480,520,800),fill='#f7f7ed')
    draw.text((90,110),'VOICEMIX / DEMO',fill='white',font_size=52)
    draw.text((90,1600),f'SCENE {i+1:02d} / ORIGINAL SAMPLE',fill=accent,font_size=42)
    im.save(assets/f'demo-{i+1:02d}.png')
scripts=['今天，用几个镜头记录小店的日常。','一杯饮品，从制作到完成，都有值得记录的细节。']
config=dict(script=scripts[0],batch_scripts=scripts,count=1,src_dir=str(assets.resolve()),
            out_dir=str((root/'output').resolve()),template='subs_only',allow_reuse=True,cover_template='none')
(root/'batch-request.json').write_text(json.dumps({'config':config,'preview_only':True},ensure_ascii=False,indent=2),encoding='utf-8')
print('Assets:',assets.resolve())
print('Example request:',(root/'batch-request.json').resolve())
