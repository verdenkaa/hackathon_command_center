"""Code-native branding shared by the window, taskbar, and notification area."""
from pathlib import Path

ICON_DIR = Path(__file__).parent / 'static' / 'icons'


def build_icons() -> None:
    from PIL import Image, ImageDraw
    image = Image.new('RGBA', (256,256), (0,0,0,0))
    draw = ImageDraw.Draw(image)
    draw.rounded_rectangle((8,8,248,248), radius=55, fill='#101c32')
    draw.polygon([(128,35),(208,81),(208,175),(128,221),(48,175),(48,81)], fill='#192f50', outline='#76a5ff', width=10)
    for point in [(83,99),(173,99),(128,176)]:
        draw.line((128,128,*point),fill='#76a5ff',width=9)
        x,y=point
        draw.ellipse((x-17,y-17,x+17,y+17),fill='#54d4a3')
    draw.ellipse((105,105,151,151),fill='#e8f0ff')
    ICON_DIR.mkdir(parents=True,exist_ok=True)
    image.save(ICON_DIR / 'hub.png')
    image.save(ICON_DIR / 'hub.ico',sizes=[(16,16),(24,24),(32,32),(48,48),(64,64),(128,128),(256,256)])


if __name__ == '__main__':
    build_icons()
