"""waitmybabe renderer: warm beige 'story + chat' Short.
Segment types: hook | narr | chat | key | question.  **text** = rose highlight (hook/key/question; use explicit \n)."""
import os, re
from PIL import Image, ImageDraw
from common import *

VOICES = {
    'me':  dict(voice='ko-KR-SunHiNeural', rate='+9%', pitch='+0Hz'),            # 1인칭 주인공
    'mil': dict(voice='ko-KR-SunHiNeural', rate='+0%', pitch='-14Hz'),           # 시어머니/엄마 세대 여성
    'husband': dict(voice='ko-KR-InJoonNeural', rate='+4%', pitch='+0Hz'),
    'fil': dict(voice='ko-KR-HyunsuMultilingualNeural', rate='-2%', pitch='-10Hz'),  # 시아버지/어른 남성
    'man2': dict(voice='ko-KR-HyunsuMultilingualNeural', rate='+4%', pitch='+0Hz'),
}
BG = (244, 236, 226); BG2 = (236, 224, 211)
INK = (59, 47, 42); SOFT = (140, 120, 108); ROSE = (192, 98, 107); CARD = (255, 251, 246)
KEYBG = (233, 214, 207)
BUBBLE = {'left': (255, 255, 255), 'me': (247, 222, 215)}
X0, X1 = SAFE[0] + 10, SAFE[2] - 10      # 70..890
TOP, BOT = 330, 1385

def bg(label):
    im = Image.new('RGBA', (W, H), BG + (255,))
    d = ImageDraw.Draw(im)
    for y in range(H):                      # soft vertical gradient
        k = y / H
        d.line([(0, y), (W, y)], fill=tuple(int(BG[i] * (1 - k) + BG2[i] * k) for i in range(3)))
    draw_line(im, (SAFE_CX, 262), label, font('gowun_b', 34), fill=SOFT)
    d.line([SAFE_CX - 60, 312, SAFE_CX + 60, 312], fill=(210, 190, 175), width=2)
    return im

def _rich_words(line, hi=False):
    """'a **b c** d' -> [('a',False),('b',True),('c',True),('d',False)]; returns (words, hi_state)"""
    out = []
    for w in line.split(' '):
        if not w: continue
        cnt = w.count('**'); clean = w.replace('**', '')
        starts = w.startswith('**')
        word_hi = hi or starts
        out.append((clean, word_hi))
        if cnt % 2 == 1: hi = not hi
    return out, hi

def _rich_lines(text, f, maxw):
    lines = []; hi = False
    for para in text.split('\n'):
        cur = []
        words, hi = _rich_words(para, hi)
        for w, h in words:
            cand = cur + [(w, h)]
            if cur and text_width(' '.join(x for x, _ in cand), f) > maxw:
                lines.append(cur); cur = [(w, h)]
            else:
                cur = cand
        lines.append(cur)
    return lines

def rich_block(img, cx, y, text, f, base, hi, maxw, gap=1.45):
    lh = int(f.size * gap)
    lines = _rich_lines(text, f, maxw)
    sp = f.getlength(' ')
    for i, ln in enumerate(lines):
        x = cx - text_width(' '.join(w for w, _ in ln), f) / 2
        for w, h in ln:
            draw_line(img, (x, y + i * lh), w, f, fill=hi if h else base, anchor_center=False)
            x += text_width(w, f) + sp
    return y + len(lines) * lh

def rich_height(text, f, maxw, gap=1.45):
    return len(_rich_lines(text, f, maxw)) * int(f.size * gap)

# ---- stack items (story cards & chat bubbles) ----
F_NARR = lambda: font('gowun_b', 54)
F_CHAT = lambda: font('sans_r', 47)
F_NAME = lambda: font('sans_b', 30)

def item_size(it):
    if it['type'] == 'narr':
        h = block_height(it['text'], F_NARR(), X1 - X0 - 80, 1.4) + 56
        return h
    h = block_height(it['text'], F_CHAT(), 600, 1.38) + 44
    if it.get('who') != '나': h += 40
    if it.get('photo'): h += 250
    if it.get('group_header'): h += 64
    return h

def draw_item(img, it, y, alpha=1.0, faded=False):
    lay = Image.new('RGBA', img.size, (0, 0, 0, 0))
    d = ImageDraw.Draw(lay)
    if it['type'] == 'narr':
        h = item_size(it)
        d.rounded_rectangle([X0, y, X1, y + h - 16], 28, fill=CARD + (255,))
        d.rounded_rectangle([X0, y, X0 + 10, y + h - 16], 5, fill=ROSE + (255,))
        draw_block(lay, SAFE_CX + 5, y + 18, it['text'], F_NARR(), SOFT if faded else INK, X1 - X0 - 80, 1.4)
    else:
        yy = y
        if it.get('group_header'):
            d.rounded_rectangle([SAFE_CX - 190, yy, SAFE_CX + 190, yy + 48], 24, fill=(222, 205, 190, 255))
            draw_line(lay, (SAFE_CX, yy + 4), it['group_header'], font('sans_b', 30), fill=INK)
            yy += 64
        mine = it.get('who') == '나'
        tw = min(600, max(text_width(l, F_CHAT()) for l in wrap(it['text'], F_CHAT(), 600)))
        bw = tw + 48 + (0 if not it.get('photo') else 0)
        if it.get('photo'): bw = max(bw, 420)
        bh = block_height(it['text'], F_CHAT(), 600, 1.38) + 28 + (250 if it.get('photo') else 0)
        if mine:
            bx1 = X1; bx0 = bx1 - bw
        else:
            ax = X0 + 40
            d.ellipse([X0, yy, X0 + 78, yy + 78], fill=(230, 212, 198, 255))
            draw_line(lay, (X0 + 39, yy + 12), it.get('avatar', '👤'), font('sans_b', 44), fill=INK)
            d.text((X0 + 96, yy), it['who'], font=F_NAME(), fill=SOFT)
            yy += 40; bx0 = X0 + 96; bx1 = bx0 + bw
        d.rounded_rectangle([bx0, yy, bx1, yy + bh], 26, fill=(BUBBLE['me'] if mine else BUBBLE['left']) + (255,))
        ty = yy + 14
        if it.get('photo'):
            d.rounded_rectangle([bx0 + 16, ty, bx1 - 16, ty + 230], 18, fill=(214, 190, 170, 255))
            draw_line(lay, ((bx0 + bx1) / 2, ty + 40), '🍳📷', font('sans_b', 84), fill=INK)
            draw_line(lay, ((bx0 + bx1) / 2, ty + 160), it['photo'], font('sans_b', 34), fill=(90, 70, 60))
            ty += 250
        lines = wrap(it['text'], F_CHAT(), 600)
        for i, ln in enumerate(lines):
            draw_line(lay, (bx0 + 24, ty + i * int(47 * 1.38)), ln, F_CHAT(), fill=SOFT if faded else INK, anchor_center=False)
    if alpha < 1:
        a = lay.split()[3].point(lambda v: int(v * alpha)); lay.putalpha(a)
    img.alpha_composite(lay)

def layout(stack):
    """Return y positions so that the newest item is fully visible (older ones scroll up/out)."""
    gap = 22
    hs = [item_size(it) for it in stack]
    total = sum(hs) + gap * (len(hs) - 1)
    y = TOP if total <= BOT - TOP else BOT - total
    ys = []
    for h in hs: ys.append(y); y += h + gap
    return ys

def render_stack(stack, label, new_alpha=1.0, slide=0):
    im = bg(label)
    ys = layout(stack)
    for i, (it, y) in enumerate(zip(stack, ys)):
        if y + item_size(it) < TOP - 10: continue
        last = i == len(stack) - 1
        if y < TOP:   # clipped at top -> skip partially hidden
            continue
        draw_item(im, it, y + (slide if last else 0), new_alpha if last else 1.0, faded=not last and i < len(stack) - 2)
    return im

def full_card(label, text, sub=None, big=86, footer=None, tint=KEYBG):
    im = bg(label)
    d = ImageDraw.Draw(im)
    f = font('serif_b', big)
    h = rich_height(text, f, X1 - X0 - 60, 1.42)
    sub_h = (block_height(sub, font('gowun_b', 44), X1 - X0 - 60) + 30) if sub else 0
    if h + sub_h > BOT - TOP - 200: print(f'[WARN] card text too long: {text[:20]!r}')
    cy0 = max(TOP + 40, (TOP + BOT) // 2 - (h + sub_h) // 2 - 40)
    d.rounded_rectangle([X0, cy0 - 60, X1, cy0 + h + sub_h + 50], 40, fill=tint)
    y = rich_block(im, SAFE_CX, cy0, text, f, INK, ROSE, X1 - X0 - 60, 1.42)
    if sub: draw_block(im, SAFE_CX, y + 20, sub, font('gowun_b', 44), SOFT, X1 - X0 - 60)
    if footer: draw_block(im, SAFE_CX, BOT - 70, footer, font('sans_r', 30), SOFT, X1 - X0)
    return im

def render(spec, outdir):
    os.makedirs(outdir, exist_ok=True)
    wd = os.path.join(os.environ.get('SAYEON_WORKDIR', '/workspace/youtube/.work'), spec.get('slug', 'short')); os.makedirs(wd, exist_ok=True)
    for f_ in os.listdir(wd):
        if f_.endswith('.png'): os.remove(os.path.join(wd, f_))
    label = spec.get('label', '오늘의 사연')
    frames, audio, t = [], [], 0.0
    n = [0]
    def png(img):
        n[0] += 1; p = os.path.join(wd, f'f{n[0]:03d}.png'); img.convert('RGB').save(p); return p
    stack = []
    prev_chat = False
    for i, sg in enumerate(spec['segments']):
        v = VOICES[sg.get('voice', 'me')]
        wav = os.path.join(wd, f'a{i:03d}.wav')
        dur = tts(sg.get('spoken', sg['text'].replace('**', '').replace('\n', ' ')), **v, out_wav=wav)
        pause = sg.get('pause', 0.35 if sg['type'] in ('narr', 'chat') else 0.6)
        seg = dur + pause
        typ = sg['type']
        start = t
        if typ == 'hook':
            seg = max(seg, 2.5)
            frames.append((png(full_card(label, sg['text'], sub=sg.get('sub'), big=sg.get('size', 80))), seg))
            audio.append((wav, t + 0.05))
            stack = []; prev_chat = False
        elif typ in ('narr', 'chat'):
            it = dict(sg)
            if typ == 'chat' and sg.get('group') and not prev_chat:
                it['group_header'] = sg['group']
            prev_chat = typ == 'chat'
            stack.append(it)
            for a, sl in ((0.35, 18), (0.7, 8)):
                frames.append((png(render_stack(stack, label, a, sl)), 1 / 15))
            frames.append((png(render_stack(stack, label)), seg - 2 / 15))
            audio.append((wav, t + 0.08))
        elif typ == 'key':
            frames.append((png(full_card(label, sg['text'], sub=sg.get('sub'), big=sg.get('size', 78))), seg))
            audio.append((wav, t + 0.05))
            if sg.get('clear', True): stack = []; prev_chat = False
        elif typ == 'question':
            seg = dur + sg.get('tail', 1.6)
            frames.append((png(full_card(label, sg['text'], sub=sg.get('sub', '댓글로 알려주세요 👇'), big=sg.get('size', 76),
                                         footer=spec.get('disclosure', '※ 본 사연은 창작·각색된 이야기입니다.'))), seg))
            audio.append((wav, t + 0.05))
        t += seg
        print(f'[timing] {start:6.2f}s  {typ:8s} {sg["text"][:24]!r}')
    out = os.path.join(outdir, spec.get('slug', 'sayeon') + '.mp4')
    total = assemble(frames, audio, out, wd, bgm_mood='warm', bgm_db=-25)
    return out, total
