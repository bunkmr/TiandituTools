# -*- coding: utf-8 -*-
"""生成 TiandituTools 的按钮图标与 Logo（开发工具，不随插件发布）。

设计语言（**新加的图标请沿用，别另起一套**）
--------------------------------------------
  * 底板：圆角方块，天地图蓝竖向渐变 #3B8FE0 -> #1462B4，描边 #0E4C8C，
    上缘加一层极淡的高光（alpha 34），整体观感与 Windows 现代工具条一致。
  * 图形：一律白色；强调点用暖橙 #FF9F1C（"加号 / 高亮块 / 定位点"）。
  * 五个按钮共用同一块蓝底板，靠**图形**区分 —— 同一支工具条上这样最整。
  * 渲染方式：每个目标尺寸都按 4 倍超采样绘制再 LANCZOS 缩小，
    所以 16px 也是干净的（旧的 16px 其实是把 32px 直接复用，必然糊）。

输出：TiandituTools/images/ 下的 PNG（ArcMap 工具条用）+ help_logo.gif
      （帮助页页眉；Tk 8.5 的 PhotoImage 不认 PNG，只认 GIF）。

用法：
    python dev_make_icons.py
"""

from __future__ import print_function

import os

from PIL import Image, ImageChops, ImageDraw, ImageFont

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "TiandituTools", "images")

SS = 4                      # 超采样倍数
PLATE_TOP = (59, 143, 224)      # #3B8FE0
PLATE_BOT = (20, 98, 180)       # #1462B4
PLATE_LINE = (14, 76, 140)      # #0E4C8C
ACCENT = (255, 159, 28)         # #FF9F1C
WHITE = (255, 255, 255)


def A(c, a=255):
    """补上 alpha —— 统一成 4 元组，避免 3 元组再 + (255,) 变成 5 元组"""
    return tuple(c) + (a,) if len(c) == 3 else tuple(c)
FONT_BOLD = r"C:\Windows\Fonts\msyhbd.ttc"
FONT_UI = r"C:\Windows\Fonts\msyh.ttc"


# ---------------------------------------------------------------------------
# 基础件
# ---------------------------------------------------------------------------

def _mix(a, b, t):
    return tuple(int(a[i] + (b[i] - a[i]) * t) for i in range(3))


def _plate(s, radius=0.235):
    """圆角渐变底板（s = 实际画布边长，已含超采样）"""
    r = int(radius * s)
    img = Image.new("RGBA", (s, s), (0, 0, 0, 0))

    mask = Image.new("L", (s, s), 0)
    ImageDraw.Draw(mask).rounded_rectangle([0, 0, s - 1, s - 1], radius=r, fill=255)

    grad = Image.new("RGBA", (1, s))
    for y in range(s):
        grad.putpixel((0, y), _mix(PLATE_TOP, PLATE_BOT, y / float(max(1, s - 1))) + (255,))
    img.paste(grad.resize((s, s), Image.BILINEAR), (0, 0), mask)

    # 上缘高光：只留上面 46%，再用底板形状裁一次
    gloss = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    ImageDraw.Draw(gloss).rounded_rectangle(
        [0, 0, s - 1, int(s * 0.46)], radius=r, fill=(255, 255, 255, 30))
    ga = ImageChops.multiply(gloss.split()[3], mask)
    gloss.putalpha(ga)
    img = Image.alpha_composite(img, gloss)

    # 描边（画在形状内侧，缩小时才不会溢出）
    w = max(2, int(s * 0.012))
    ImageDraw.Draw(img).rounded_rectangle(
        [w // 2, w // 2, s - 1 - w // 2, s - 1 - w // 2],
        radius=r, outline=A(PLATE_LINE), width=w)
    return img


def _canvas(size):
    """返回 (超采样画布, 边长, 缩放后保存函数)"""
    s = size * SS
    img = _plate(s)
    return img, s


def _down(img, size, name):
    out = img.resize((size, size), Image.LANCZOS)
    path = os.path.join(OUT, name)
    out.save(path, "PNG", optimize=True)
    return path


def _stroke(s, frac, minimum=1.6):
    """线宽：按边长比例算，但保证小尺寸下不小于 minimum 像素"""
    return max(s * frac, minimum * SS)


def _w(draw, pts, width, color=WHITE, joint=True):
    draw.line(pts, fill=color, width=int(round(width)), joint="curve" if joint else None)


# ---------------------------------------------------------------------------
# 图形要素
# ---------------------------------------------------------------------------

def _globe(d, cx, cy, radius, width):
    """经纬网地球：外圈 + 一条竖椭圆经线 + 一条赤道。

    **不要加纬线**：试过 ±0.5r 两条纬线，32px 就糊成华夫饼、
    16px 干脆成了一团白 —— 小尺寸下要素越少越清楚。
    """
    r = radius
    w = int(round(width))
    d.ellipse([cx - r, cy - r, cx + r, cy + r], outline=WHITE, width=w)
    d.ellipse([cx - r * 0.47, cy - r, cx + r * 0.47, cy + r],
              outline=WHITE, width=max(1, int(round(w * 0.75))))
    _w(d, [(cx - r, cy), (cx + r, cy)], width)


def _rhombus(d, cx, cy, hw, hh, fill):
    d.polygon([(cx, cy - hh), (cx + hw, cy), (cx, cy + hh), (cx - hw, cy)], fill=fill)


def _layers(d, cx, cy, hw, hh, gap, back_alpha=120):
    """叠层（像几张叠起来的地图）——「添加底图」用它，跟 Logo 的地球区分开"""
    # 后排：半透明白，产生层次又不抢前排
    _rhombus(d, cx, cy - gap, hw, hh, (255, 255, 255, back_alpha))
    # 前排：实心白 + 一圈底板色描边（16px 下没有这道描边会糊成一坨）
    _rhombus(d, cx, cy + gap, hw, hh, A(PLATE_BOT))
    _rhombus(d, cx, cy + gap, hw * 0.93, hh * 0.88, WHITE)


def _plus(d, cx, cy, arm, width, color=ACCENT):
    w = int(round(width))
    _w(d, [(cx - arm, cy), (cx + arm, cy)], width, color)
    _w(d, [(cx, cy - arm), (cx, cy + arm)], width, color)


def _pin(d, cx, cy, h, color=ACCENT):
    """定位点：圆头 + 尖尾"""
    r = h * 0.34
    top = cy - h * 0.5
    d.ellipse([cx - r, top - r, cx + r, top + r], fill=A(color))
    d.polygon([(cx - r * 0.72, top + r * 0.62),
               (cx + r * 0.72, top + r * 0.62),
               (cx, cy + h * 0.5)], fill=A(color))
    hr = r * 0.36
    d.ellipse([cx - hr, top - hr, cx + hr, top + hr], fill=WHITE)


def _gear(d, cx, cy, r_out, r_in, teeth, width, color=WHITE):
    """齿轮：每齿 6 个采样点，2 个落在齿顶、4 个落在齿谷。

    比例要克制 —— 全用"4 采样、2 个在齿顶"的话齿顶占 30°、齿谷只占 30°，
    画出来是**六角星**不是齿轮。2/6 才是齿顶窄、齿谷宽的常规齿轮形。
    r_in 也不能跟 r_out 差太少（齿深要 >= 0.09*S），否则 16px 下齿谷
    被抗锯齿抹平，整个齿轮变成一个白饼。
    """
    import math
    n = teeth * 6
    pts = []
    for k in range(n):
        a = 2 * math.pi * k / n - math.pi / 2
        rr = r_out if (k % 6) in (0, 1) else r_in
        pts.append((cx + rr * math.cos(a), cy + rr * math.sin(a)))
    d.polygon(pts, fill=A(color))
    hr = r_in * 0.44
    d.ellipse([cx - hr, cy - hr, cx + hr, cy + hr], fill=A(PLATE_BOT))


def _tiles(d, cx, cy, side, gap, hi=1, color=WHITE):
    """2x2 瓦片块，其中一块用橙色高亮。

    画完之后**再补一个底板色的十字**把四块隔开 —— 只靠"留缝"在 16px 下
    缝会被抗锯齿吃掉，四块连成一个白方块，一眼看不出是瓦片。
    """
    h = side / 2.0
    boxes = [(cx - h - gap, cy - h - gap), (cx + gap, cy - h - gap),
             (cx - h - gap, cy + gap), (cx + gap, cy + gap)]
    r = side * 0.20
    for i, (x, y) in enumerate(boxes):
        fill = A(ACCENT) if i == hi else color
        d.rounded_rectangle([x, y, x + side, y + side], radius=r, fill=fill)
    bw = max(1, int(round(gap * 1.5)))
    d.rectangle([cx - h - gap, cy - bw / 2.0, cx + h + gap, cy + bw / 2.0],
                fill=A(PLATE_BOT))
    d.rectangle([cx - bw / 2.0, cy - h - gap, cx + bw / 2.0, cy + h + gap],
                fill=A(PLATE_BOT))


def _glyph_text(img, s, ch, frac=0.80, font_path=FONT_BOLD):
    """用字体画单个字符并精确居中（问号用这个，比手画弧线干净得多）"""
    f = ImageFont.truetype(font_path, int(s * frac))
    box = f.getbbox(ch)
    w, h = box[2] - box[0], box[3] - box[1]
    layer = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    ImageDraw.Draw(layer).text(((s - w) / 2 - box[0], (s - h) / 2 - box[1]),
                               ch, font=f, fill=WHITE)
    return Image.alpha_composite(img, layer)


# ---------------------------------------------------------------------------
# 五个按钮图标
# ---------------------------------------------------------------------------

def icon_add(size):
    """添加底图 = 叠层 + 加号（跟 Logo 的地球+定位点区分开）"""
    img, s = _canvas(size)
    d = ImageDraw.Draw(img)
    _layers(d, s * 0.395, s * 0.430, s * 0.290, s * 0.180, s * 0.098)
    # 加号徽标：先垫一圈底板色把叠层"切"开，再描白环
    bx, by = s * 0.720, s * 0.725
    br = s * 0.228
    d.ellipse([bx - br * 1.14, by - br * 1.14, bx + br * 1.14, by + br * 1.14],
              fill=A(PLATE_BOT))
    d.ellipse([bx - br, by - br, bx + br, by + br],
              outline=WHITE, width=int(round(_stroke(s, 0.032))))
    _plus(d, bx, by, s * 0.102, _stroke(s, 0.062), ACCENT)
    return _down(img, size, "add%d.png" % size)


def icon_search(size):
    img, s = _canvas(size)
    d = ImageDraw.Draw(img)
    r = s * 0.235
    cx, cy = s * 0.455, s * 0.435
    w = _stroke(s, 0.058)
    d.ellipse([cx - r, cy - r, cx + r, cy + r], outline=WHITE, width=int(round(w)))
    # 镜片里放一点橙，跟其它按钮同源又一眼可辨
    hr = r * 0.40
    d.ellipse([cx - hr, cy - hr, cx + hr, cy + hr], fill=A(ACCENT))
    d.line([(cx + r * 0.72, cy + r * 0.72), (s * 0.805, s * 0.805)],
           fill=WHITE, width=int(round(w * 1.08)))
    return _down(img, size, "search%d.png" % size)


def icon_setting(size):
    img, s = _canvas(size)
    d = ImageDraw.Draw(img)
    c = s * 0.5
    _gear(d, c, c, s * 0.345, s * 0.240, 6, _stroke(s, 0.05))
    hr = s * 0.072
    d.ellipse([c - hr, c - hr, c + hr, c + hr], fill=A(ACCENT))
    return _down(img, size, "setting%d.png" % size)


def icon_help(size):
    img, s = _canvas(size)
    img = _glyph_text(img, s, u"?", 0.86)
    return _down(img, size, "help%d.png" % size)


def icon_xyz(size):
    img, s = _canvas(size)
    d = ImageDraw.Draw(img)
    _tiles(d, s * 0.5, s * 0.5, s * 0.252, s * 0.048, hi=1)
    return _down(img, size, "xyz%d.png" % size)


# ---------------------------------------------------------------------------
# Logo（Add-In 图标 / 帮助页页眉）
# ---------------------------------------------------------------------------

def logo_mark(size, pin=True):
    img, s = _canvas(size)
    d = ImageDraw.Draw(img)
    _globe(d, s * 0.475, s * 0.515, s * 0.285, _stroke(s, 0.058))
    if pin:
        _pin(d, s * 0.715, s * 0.335, s * 0.46)
    return _down(img, size, "toolbar%d.png" % size)


def help_logo_gif(path, w=460, h=86):
    """帮助页页眉（GIF —— Tk 8.5 只认 GIF/PPM）"""
    img = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.rounded_rectangle([0, 0, w - 1, h - 1], radius=10, fill=(16, 74, 128, 255))
    # 左侧的标记（复用同一套地球 + 定位点）
    mark = Image.new("RGBA", (h * SS, h * SS), (0, 0, 0, 0))
    md = ImageDraw.Draw(mark)
    S = h * SS
    _globe(md, S * 0.5, S * 0.5, S * 0.29, max(6, S * 0.056))
    _pin(md, S * 0.72, S * 0.34, S * 0.46)
    img.alpha_composite(mark.resize((h, h), Image.LANCZOS), (4, 0))

    f1 = ImageFont.truetype(FONT_BOLD, 27)
    f2 = ImageFont.truetype(FONT_UI, 13)
    d.text((h + 16, 16), u"天地图 Tools", font=f1, fill=(255, 255, 255, 255))
    d.text((h + 18, 52), u"ArcMap 在线底图 / 搜索 / 自定义图源",
           font=f2, fill=(168, 206, 240, 255))
    d.text((w - 96, 62), u"v0.8.0", font=f2, fill=(120, 170, 215, 255))

    img.convert("RGB").convert(
        "P", palette=Image.ADAPTIVE, colors=200, dither=Image.Dither.NONE
    ).save(path, "GIF", optimize=True)
    return path


def wechat_qr_gif(path, size=150):
    """微信公众号二维码的**占位图**（GIF）。

    文章/二维码还没到位，但不该在帮助页留一个空白方块 —— 画一张一眼能看懂
    "这里以后放二维码"的卡片：白底 + 虚线框 + 三个定位角 + 一行提示。
    真二维码拿到后，直接用同名文件覆盖 images/wechat_qr.gif 即可，
    帮助页会自动换成真图（ui_help 只判断文件在不在）。
    """
    S = size * SS
    img = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.rounded_rectangle([0, 0, S - 1, S - 1], radius=S * 0.06,
                        fill=(255, 255, 255, 255),
                        outline=A((150, 160, 172)), width=int(S * 0.006))

    # 虚线内框
    m = S * 0.085
    step = S * 0.055
    x = m
    while x < S - m:
        d.line([(x, m), (min(x + step * 0.55, S - m), m)], fill=A((205, 212, 220)),
               width=int(S * 0.010))
        d.line([(x, S - m), (min(x + step * 0.55, S - m), S - m)],
               fill=A((205, 212, 220)), width=int(S * 0.010))
        x += step
    y = m
    while y < S - m:
        d.line([(m, y), (m, min(y + step * 0.55, S - m))], fill=A((205, 212, 220)),
               width=int(S * 0.010))
        d.line([(S - m, y), (S - m, min(y + step * 0.55, S - m))],
               fill=A((205, 212, 220)), width=int(S * 0.010))
        y += step

    # 三个定位角（真二维码的"回"字，一眼认得出）
    def corner(cx, cy):
        side = S * 0.175
        r = side / 2.0
        d.rounded_rectangle([cx - r, cy - r, cx + r, cy + r],
                            radius=S * 0.022, outline=A(PLATE_BOT),
                            width=int(S * 0.020))
        d.rounded_rectangle([cx - r * 0.44, cy - r * 0.44, cx + r * 0.44, cy + r * 0.44],
                            radius=S * 0.010, fill=A(PLATE_BOT))

    o = S * 0.205
    corner(o, o)
    corner(S - o, o)
    corner(o, S - o)

    f = ImageFont.truetype(FONT_BOLD, int(S * 0.098))
    t1 = u"微信公众号二维码"
    t2 = u"待 补 充"
    for t, dy, fill in ((t1, S * 0.345, (40, 52, 66, 255)),
                        (t2, S * 0.485, (120, 132, 146, 255))):
        box = f.getbbox(t)
        d.text(((S - (box[2] - box[0])) / 2.0 - box[0], dy), t, font=f, fill=fill)

    img.convert("RGB").convert(
        "P", palette=Image.ADAPTIVE, colors=200, dither=Image.Dither.NONE
    ).save(path, "GIF", optimize=True)
    return path


# ---------------------------------------------------------------------------

def main():
    if not os.path.isdir(OUT):
        os.makedirs(OUT)
    made = []
    for fn in (icon_add, icon_search, icon_setting, icon_help, icon_xyz):
        for size in (16, 24, 32):
            made.append(fn(size))
    for size in (16, 24, 32, 48):
        made.append(logo_mark(size, pin=(size >= 24)))
    made.append(help_logo_gif(os.path.join(OUT, "help_logo.gif")))
    # 只在新装机（文件不存在）时铺占位图 —— 别把用户换上的真二维码覆盖掉
    qr = os.path.join(OUT, "wechat_qr.gif")
    if not os.path.isfile(qr):
        made.append(wechat_qr_gif(qr))
    else:
        print("  = wechat_qr.gif 已存在，跳过（保留你放进去的二维码）")

    # 清掉旧的对不上号的文件（toolbar32 以前是 16 像素的假图标）
    for name in ("toolbar16.png", "toolbar32.png"):
        p = os.path.join(OUT, name)
        if os.path.isfile(p):
            made.append(p)

    for p in made:
        print("  + %s  (%d bytes)" % (os.path.relpath(p, HERE), os.path.getsize(p)))


if __name__ == "__main__":
    main()
