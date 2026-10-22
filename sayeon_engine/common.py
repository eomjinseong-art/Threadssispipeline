"""Shared helpers: TTS (edge-tts), text rendering w/ emoji, timeline -> mp4, original BGM synth."""
import asyncio, json, os, re, subprocess, math, wave, hashlib, shutil, time
import numpy as np
from PIL import Image, ImageDraw, ImageFont

W, H, FPS = 1080, 1920, 30
SAFE = (60, 250, 900, 1400)          # x0,y0,x1,y1 Shorts safe zone for text
SAFE_CX = (SAFE[0] + SAFE[2]) // 2   # 480
# edge-tts 7.2.8 gets 403 (rany2/edge-tts#490); prefer the repo's patched wrapper (new host + legacy fallback).
_FIXED_TTS = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'tools', 'edge-tts-fixed')
EDGE_TTS = os.environ.get('EDGE_TTS') or (_FIXED_TTS if os.path.exists(_FIXED_TTS) else None) or shutil.which('edge-tts') or os.path.expanduser('~/.local/bin/edge-tts')
_HERE = os.path.dirname(os.path.abspath(__file__))
_FONT_DIRS = [os.environ.get('SAYEON_FONT_DIR', ''), os.path.join(_HERE, '..', 'fonts'), os.path.join(_HERE, '..', 'assets', 'fonts'),
              '/usr/share/fonts/truetype/sand-box/google/Gowun Batang']
def _gowun(fname):
    for d in _FONT_DIRS:
        if d and os.path.exists(os.path.join(d, fname)):
            return os.path.join(d, fname)
    return os.path.join(_FONT_DIRS[-1], fname)
FONTS = {
    'sans_b': ('/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc', 1),
    'sans_r': ('/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc', 1),
    'serif_b': ('/usr/share/fonts/opentype/noto/NotoSerifCJK-Bold.ttc', 1),
    'serif_r': ('/usr/share/fonts/opentype/noto/NotoSerifCJK-Regular.ttc', 1),
    'gowun_b': (_gowun('GowunBatang-Bold.ttf'), 0),
    'gowun_r': (_gowun('GowunBatang-Regular.ttf'), 0),
}
EMOJI_FONT = '/usr/share/fonts/truetype/noto/NotoColorEmoji.ttf'
_fcache = {}

def font(name, size):
    k = (name, size)
    if k not in _fcache:
        p, i = FONTS[name]
        _fcache[k] = ImageFont.truetype(p, size, index=i)
    return _fcache[k]

_EMO = re.compile('[\U0001F000-\U0001FAFF\u2600-\u27BF\u2B50\u2764]')
_emoji_cache = {}

def _emoji_img(ch, size):
    k = (ch, size)
    if k not in _emoji_cache:
        f = ImageFont.truetype(EMOJI_FONT, 109)
        im = Image.new('RGBA', (140, 140), (0, 0, 0, 0))
        ImageDraw.Draw(im).text((5, 5), ch, font=f, embedded_color=True)
        bb = im.getbbox() or (0, 0, 1, 1)
        im = im.crop(bb)
        s = size / max(im.size) * 1.0
        _emoji_cache[k] = im.resize((max(1, int(im.width * s)), max(1, int(im.height * s))), Image.LANCZOS)
    return _emoji_cache[k]

def _tokens(s):
    s = s.replace('\ufe0f', '')
    out, buf = [], ''
    for ch in s:
        if _EMO.match(ch):
            if buf: out.append(('t', buf)); buf = ''
            out.append(('e', ch))
        else:
            buf += ch
    if buf: out.append(('t', buf))
    return out

def text_width(s, f):
    w = 0
    for kind, v in _tokens(s):
        w += f.getlength(v) if kind == 't' else f.size * 1.05
    return w

def wrap(s, f, maxw):
    """Wrap Korean text by words (fallback to chars). Respects explicit \n."""
    lines = []
    for para in s.split('\n'):
        cur = ''
        for word in para.split(' '):
            cand = (cur + ' ' + word) if cur else word
            if text_width(cand, f) <= maxw:
                cur = cand
            else:
                if cur: lines.append(cur)
                cur = word
                while text_width(cur, f) > maxw:   # very long word
                    i = len(cur)
                    while i > 1 and text_width(cur[:i], f) > maxw: i -= 1
                    lines.append(cur[:i]); cur = cur[i:]
        lines.append(cur)
    return lines

def draw_line(img, xy, s, f, fill, anchor_center=True, stroke=0, stroke_fill=None):
    d = ImageDraw.Draw(img)
    x, y = xy
    w = text_width(s, f)
    if anchor_center: x = x - w / 2
    for kind, v in _tokens(s):
        if kind == 't':
            d.text((x, y), v, font=f, fill=fill, stroke_width=stroke, stroke_fill=stroke_fill)
            x += f.getlength(v)
        else:
            e = _emoji_img(v, int(f.size * 0.95))
            img.alpha_composite(e, (int(x + f.size * 0.05), int(y + f.size * 0.18))) if img.mode == 'RGBA' else img.paste(e, (int(x), int(y + f.size * 0.18)), e)
            x += f.size * 1.05
    return w

def draw_block(img, cx, y, s, f, fill, maxw, line_gap=1.35, **kw):
    """Draws wrapped centered block; returns (bottom_y, lines, block_width)."""
    lines = wrap(s, f, maxw)
    lh = int(f.size * line_gap)
    bw = 0
    for i, ln in enumerate(lines):
        bw = max(bw, draw_line(img, (cx, y + i * lh), ln, f, fill, **kw))
    return y + len(lines) * lh, lines, bw

def block_height(s, f, maxw, line_gap=1.35):
    return len(wrap(s, f, maxw)) * int(f.size * line_gap)

# ---------------- audio ----------------
def run(cmd):
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError(' '.join(cmd) + '\n' + r.stderr[-2000:])
    return r.stdout

def duration(path):
    return float(run(['ffprobe', '-v', 'error', '-show_entries', 'format=duration', '-of', 'default=nw=1:nk=1', path]).strip())

_OA_VOICE = {  # edge voice/pitch -> OpenAI voice + acting note
    ('ko-KR-SunHiNeural', False): ('coral', '30대 한국 여성, 차분하지만 억울함이 살짝 묻어나는 사연 낭독 톤.'),
    ('ko-KR-SunHiNeural', True): ('sage', '60대 한국 시어머니, 낮고 느긋한 말투, 은근히 생색내는 톤.'),
    ('ko-KR-InJoonNeural', False): ('ash', '30대 한국 남편, 무심하고 가볍게 넘기는 말투.'),
    ('ko-KR-HyunsuMultilingualNeural', True): ('onyx', '60대 한국 시아버지, 낮고 점잖은 말투.'),
    ('ko-KR-HyunsuMultilingualNeural', False): ('echo', '친절하고 사무적인 한국 남성 직원 말투.'),
}

def openai_tts(text, voice, rate, pitch, mp3):
    """OpenAI gpt-4o-mini-tts (OPENAI_API_KEY_FIXED or OPENAI_API_KEY)."""
    from openai import OpenAI
    low = pitch.startswith('-') and pitch not in ('-0Hz',)
    ov, note = _OA_VOICE.get((voice, low)) or _OA_VOICE.get((voice, not low)) or ('coral', '한국어 사연 낭독.')
    try: speed = 1.0 + int(rate.strip('%+')) / 100 if rate else 1.0
    except ValueError: speed = 1.0
    client = OpenAI(api_key=os.environ.get('OPENAI_API_KEY_FIXED') or os.environ.get('OPENAI_API_KEY'))
    r = client.audio.speech.create(model='gpt-4o-mini-tts', voice=ov, input=text, instructions=note + ' 자연스러운 한국어로.', response_format='mp3', speed=max(0.8, min(1.3, speed * 1.08)))
    with open(mp3, 'wb') as f: f.write(r.read())

# 2026-10-21 daily run: api.msedgeservices.com answered 429 mid-render.
# Immediate retries hit the same limit. Sleep between attempts, then stop
# calling edge-tts for the rest of this process.
TTS_RATE_LIMIT_DELAYS = (2, 4, 8, 16, 32)
_edge_rate_limited = False


def tts_error_is_rate_limit(err: BaseException) -> bool:
    """True for edge-tts websocket 429/503. Ignores a 429 that only appears in the spoken text."""
    text = str(err)
    if "Too Many Requests" in text:
        return True
    if "WSServerHandshakeError" not in text and "Invalid response status" not in text:
        return False
    return bool(re.search(r"\b(429|503)\b", text))


def _openai_tts_key() -> str:
    return os.environ.get("OPENAI_API_KEY_FIXED") or os.environ.get("OPENAI_API_KEY") or ""


def run_tts_command(cmd, *, sleep=None, rate_delays=TTS_RATE_LIMIT_DELAYS):
    """Run one edge-tts CLI call.

    Other errors are retried twice immediately (three tries total).
    429/503 sleeps through `rate_delays` (seconds) before the last failure is raised.
    """
    if sleep is None:
        sleep = time.sleep
    other_failures = 0
    rate_failures = 0
    while True:
        try:
            return run(cmd)
        except RuntimeError as exc:
            if tts_error_is_rate_limit(exc):
                if rate_failures >= len(rate_delays):
                    raise
                delay = rate_delays[rate_failures]
                rate_failures += 1
                print(
                    f"[tts] rate limited (429/503), retry in {delay:.0f}s "
                    f"({rate_failures}/{len(rate_delays)})"
                )
                sleep(delay)
                continue
            other_failures += 1
            if other_failures >= 3:
                raise
            print("[tts] edge-tts failed, retrying")


def tts(text, voice, out_wav, rate='+0%', pitch='+0Hz', cache_dir=None):
    """edge-tts -> 48k mono wav, leading/trailing silence trimmed.

    A 429/503 backs off inside run_tts_command. If the budget is used up and an
    OpenAI key is set, this segment and later ones in the same process use
    gpt-4o-mini-tts instead of hammering the websocket again.
    """
    global _edge_rate_limited
    key = hashlib.md5(f'{text}|{voice}|{rate}|{pitch}'.encode()).hexdigest()[:12]
    cache_dir = cache_dir or os.path.join(os.path.dirname(out_wav), '_ttscache')
    os.makedirs(cache_dir, exist_ok=True)
    cached = os.path.join(cache_dir, key + '.wav')
    if not os.path.exists(cached):
        mp3 = cached[:-4] + '.mp3'
        backend = os.environ.get('TTS_BACKEND', 'edge')
        if backend != 'openai' and _edge_rate_limited:
            backend = 'openai'
        if backend != 'openai':
            try:
                run_tts_command([EDGE_TTS, '--voice', voice, f'--rate={rate}', f'--pitch={pitch}', '--text', text, '--write-media', mp3])
            except RuntimeError as exc:
                if tts_error_is_rate_limit(exc):
                    _edge_rate_limited = True
                if not _openai_tts_key():
                    raise
                print('[tts] edge-tts failed, falling back to OpenAI gpt-4o-mini-tts')
                backend = 'openai'
        if backend == 'openai':
            openai_tts(text, voice, rate, pitch, mp3)
        run(['ffmpeg', '-v', 'error', '-y', '-i', mp3, '-af',
             'silenceremove=start_periods=1:start_threshold=-50dB,areverse,silenceremove=start_periods=1:start_threshold=-50dB,areverse',
             '-ar', '48000', '-ac', '1', cached])
    shutil.copy(cached, out_wav)
    return duration(out_wav)

def mix_same_line(wavs, out_wav):
    """Overlay several voices saying the same line (e.g. both partners)."""
    ins = sum([['-i', w] for w in wavs], [])
    run(['ffmpeg', '-v', 'error', '-y', *ins, '-filter_complex',
         f'amix=inputs={len(wavs)}:duration=longest:normalize=0,volume=0.8', '-ar', '48000', '-ac', '1', out_wav])
    return duration(out_wav)

def read_wav(p):
    with wave.open(p) as w:
        a = np.frombuffer(w.readframes(w.getnframes()), dtype=np.int16).astype(np.float32) / 32768
    return a

def write_wav(p, a, sr=48000):
    a = np.clip(a, -1, 1)
    with wave.open(p, 'w') as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(sr)
        w.writeframes((a * 32767).astype(np.int16).tobytes())

def synth_bgm(seconds, mood='warm', sr=48000, seed=1):
    """Original, royalty-free generated background loop (simple chord pad / plucks)."""
    rng = np.random.default_rng(seed)
    n = int(seconds * sr); t = np.arange(n) / sr
    out = np.zeros(n, np.float32)
    def note(freq, start, dur, amp, decay):
        s = int(start * sr); e = min(n, s + int(dur * sr))
        if s >= n: return
        tt = np.arange(e - s) / sr
        env = np.exp(-tt * decay) * np.minimum(1, tt / 0.01)
        wv = np.sin(2 * np.pi * freq * tt) + 0.35 * np.sin(4 * np.pi * freq * tt) + 0.12 * np.sin(6 * np.pi * freq * tt)
        out[s:e] += (amp * env * wv).astype(np.float32)
    m = lambda k: 440 * 2 ** ((k - 69) / 12)
    if mood == 'warm':     # Fmaj7 - Em7 - Dm7 - Cmaj7 soft piano, 72bpm
        prog = [[53, 57, 60, 64], [52, 55, 59, 62], [50, 53, 57, 60], [48, 52, 55, 59]]
        beat = 60 / 72; bar = beat * 4; i = 0; tt0 = 0
        while tt0 < seconds:
            ch = prog[i % 4]
            note(m(ch[0] - 12), tt0, bar, 0.10, 0.9)
            for j, k in enumerate(ch[1:] + [ch[1] + 12]):
                note(m(k), tt0 + j * beat, beat * 2.5, 0.055, 1.6)
            tt0 += bar; i += 1
    else:                   # 'playful' plucks, 100bpm
        prog = [[60, 64, 67], [57, 60, 64], [65, 69, 72], [67, 71, 74]]
        beat = 60 / 100; bar = beat * 4; i = 0; tt0 = 0
        while tt0 < seconds:
            ch = prog[i % 4]
            note(m(ch[0] - 24), tt0, bar, 0.09, 1.2)
            for j in range(8):
                k = ch[[0, 1, 2, 1][j % 4]] + (12 if j in (3, 7) else 0)
                note(m(k), tt0 + j * beat / 2, beat, 0.045, 5.0)
            tt0 += bar; i += 1
    fade = int(1.5 * sr)
    out[:fade] *= np.linspace(0, 1, fade); out[-fade:] *= np.linspace(1, 0, fade)
    return out / (np.abs(out).max() + 1e-6) * 0.5

# ---------------- assembly ----------------
def assemble(frames, audio_segments, out_mp4, workdir, bgm_mood='warm', bgm_db=-24):
    """frames: list of (png_path, seconds). audio_segments: list of (wav_path or None, start_sec)."""
    total = sum(d for _, d in frames)
    sr = 48000
    voice = np.zeros(int(total * sr) + sr, np.float32)
    for wav, start in audio_segments:
        a = read_wav(wav); s = int(start * sr)
        voice[s:s + len(a)] += a[:len(voice) - s]
    voice = voice[:int(total * sr)]
    bgm = synth_bgm(total, bgm_mood) * (10 ** (bgm_db / 20)) / 0.5
    # light ducking: lower bgm under speech
    env = np.convolve(np.abs(voice), np.ones(4800) / 4800, mode='same')
    duck = np.where(env > 0.01, 0.55, 1.0).astype(np.float32)
    duck = np.convolve(duck, np.ones(9600) / 9600, mode='same')
    mix = voice + bgm * duck
    wav_path = os.path.join(workdir, 'mix.wav'); write_wav(wav_path, mix)
    lst = os.path.join(workdir, 'frames.txt')
    with open(lst, 'w') as f:
        for p, d in frames:
            f.write(f"file '{os.path.abspath(p)}'\nduration {d:.4f}\n")
        f.write(f"file '{os.path.abspath(frames[-1][0])}'\n")
    run(['ffmpeg', '-v', 'error', '-y', '-f', 'concat', '-safe', '0', '-i', lst, '-i', wav_path,
         '-vf', f'fps={FPS},format=yuv420p', '-c:v', 'libx264', '-preset', 'medium', '-crf', '18',
         '-af', 'loudnorm=I=-14:TP=-1.5:LRA=11', '-c:a', 'aac', '-b:a', '192k', '-ar', '48000',
         '-t', f'{total:.3f}', '-movflags', '+faststart', out_mp4])
    return total

def talk_frames(png_a, png_b, seconds, step=0.16):
    """Alternate two frames (mouth open/closed) for a talking effect."""
    out, t, i = [], 0.0, 0
    while t < seconds - 1e-6:
        d = min(step, seconds - t)
        out.append((png_a if i % 2 == 0 else png_b, d)); t += d; i += 1
    return out

def safe_overlay(png_in, png_out):
    im = Image.open(png_in).convert('RGBA')
    ov = Image.new('RGBA', im.size, (0, 0, 0, 0)); d = ImageDraw.Draw(ov)
    x0, y0, x1, y1 = SAFE
    d.rectangle([0, 0, W, y0], fill=(255, 0, 0, 60)); d.rectangle([0, y1, W, H], fill=(255, 0, 0, 60))
    d.rectangle([0, y0, x0, y1], fill=(255, 0, 0, 60)); d.rectangle([x1, y0, W, y1], fill=(255, 0, 0, 60))
    d.rectangle([x0, y0, x1, y1], outline=(0, 255, 0, 255), width=4)
    Image.alpha_composite(im, ov).convert('RGB').save(png_out)
