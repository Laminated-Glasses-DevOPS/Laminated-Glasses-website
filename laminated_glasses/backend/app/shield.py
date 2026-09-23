"""Honeypot qatlami: SQL Injection va XSS urinishlarini aniqlaydi.

Muhim: backend'da SQL so'rovlarining barchasi SQLAlchemy ORM orqali
parametrlangan holda yuboriladi (hech qayerda raw string qo'shilmaydi),
shuning uchun SQL Injection zaifligi haqiqatda mavjud emas. Ushbu modul
qo'shimcha himoya qatlami: shubhali urinishni ERTAROQ ushlab, real xato
(stack trace, DB xabari) ko'rsatmasdan, hujumchini "yo'qotib" qo'yadigan
kinoyali javob bilan to'xtatadi va urinishni jurnalga yozadi.

False-positive xavfini kamaytirish uchun naqshlar (patterns) sayt uchun
xos bo'lmagan, klassik hujum imzolariga asoslangan (masalan "UNION SELECT",
"' OR '1'='1", "<script>", "onerror=") -- oddiy matn (mahsulot tavsifi,
mijoz ismi, xabar) bunga tasodifan mos kelib qolish ehtimoli juda past.
"""

import base64
import html
import re
from pathlib import Path
from typing import Optional

_ASSETS_DIR = Path(__file__).resolve().parent / "assets"
_SKULL_PATH = _ASSETS_DIR / "skull.png"


def _skull_data_uri() -> str:
    """skull.png ni base64 data URI sifatida qaytaradi, honeypot sahifasi
    hech qanday tashqi statik faylga bog'liq bo'lmasligi uchun."""
    try:
        data = _SKULL_PATH.read_bytes()
        return "data:image/png;base64," + base64.b64encode(data).decode("ascii")
    except Exception:
        return ""


_SKULL_DATA_URI = _skull_data_uri()

# --- SQL Injection imzolari -------------------------------------------------

_SQLI_PATTERNS = [
    re.compile(r"\bunion\b\s*(all\s*)?\bselect\b", re.I),
    re.compile(r"\bselect\b.{1,60}\bfrom\b.{1,60}\bwhere\b", re.I),
    re.compile(r"\binsert\s+into\b", re.I),
    re.compile(r"\bdrop\s+table\b", re.I),
    re.compile(r"\balter\s+table\b", re.I),
    re.compile(r"\bupdate\b.{1,40}\bset\b.{1,40}\bwhere\b", re.I),
    re.compile(r"['\"]\s*or\s*['\"]?\s*\d+\s*=\s*\d+", re.I),
    re.compile(r"\bor\b\s*['\"]?\s*\w+\s*['\"]?\s*=\s*['\"]?\s*\w+\s*['\"]?", re.I),
    re.compile(r"\band\b\s*['\"]?\s*\w+\s*['\"]?\s*=\s*['\"]?\s*\w+\s*['\"]?\s*--", re.I),
    re.compile(r"\bor\s+1\s*=\s*1\b", re.I),
    re.compile(r"--\s*(-)*\s*$"),
    re.compile(r";\s*(drop|delete|update|insert)\b", re.I),
    re.compile(r"\bxp_cmdshell\b", re.I),
    re.compile(r"\bsleep\(\s*\d+\s*\)", re.I),
    re.compile(r"\bbenchmark\(\s*\d+", re.I),
    re.compile(r"\bwaitfor\s+delay\b", re.I),
    re.compile(r"\binformation_schema\b", re.I),
    re.compile(r"1\s*=\s*1\s*(--|#|/\*)"),
    re.compile(r"'\s*;\s*--"),
]


def detect_sql_injection(text: str) -> bool:
    if not text:
        return False
    return any(p.search(text) for p in _SQLI_PATTERNS)


# --- XSS imzolari (turi bilan) ----------------------------------------------

_XSS_PATTERNS: list[tuple[str, "re.Pattern[str]"]] = [
    ("Script teg", re.compile(r"<\s*script\b", re.I)),
    ("Hodisa-ishlovchi (onerror/onload)", re.compile(r"on(error|load|click|mouseover|focus|input)\s*=", re.I)),
    ("JavaScript URI", re.compile(r"javascript\s*:", re.I)),
    ("Iframe in'ektsiyasi", re.compile(r"<\s*iframe\b", re.I)),
    ("SVG in'ektsiyasi", re.compile(r"<\s*svg\b.{0,80}on\w+\s*=", re.I | re.S)),
    ("Data URI (HTML)", re.compile(r"data\s*:\s*text/html", re.I)),
    ("CSS expression", re.compile(r"expression\s*\(", re.I)),
    ("Img teg orqali", re.compile(r"<\s*img\b.{0,80}on\w+\s*=", re.I | re.S)),
    ("HTML teg in'ektsiyasi", re.compile(r"<\s*(body|input|object|embed)\b.{0,80}on\w+\s*=", re.I | re.S)),
]


def detect_xss(text: str) -> Optional[str]:
    if not text:
        return None
    for label, pattern in _XSS_PATTERNS:
        if pattern.search(text):
            return label
    return None


# Bu yo'llarga tegilmaydi: fayl yuklash (rasm, binary) va statik fayllar.
SKIP_BODY_SCAN_PREFIXES = ("/uploads",)


def render_honeypot_page(message: str) -> str:
    """Brauzerda to'g'ridan-to'g'ri ochilganda ko'rinadigan, glitch/CRT
    uslubidagi "You Joke me ?" honeypot sahifasi (bosh suyagi rasmi bilan).

    Xavfsizlik eslatmasi: bu yerga uzatiladigan `message` faqat bizning
    tayyor, oldindan belgilangan kinoyali matnlarimiz (masalan "XSS ...
    qo'llash uchun ..."), hech qachon foydalanuvchi kiritgan xom matn emas.
    Shunga qaramay ehtiyot chorasi sifatida html.escape() bilan chiqishdan
    oldin har doim escape qilinadi -- shu tufayli hujumchi honeypot
    sahifasining o'ziga qarshi ikkilamchi in'ektsiya (reflected XSS)
    qila olmaydi."""
    safe_message = html.escape(message)
    skull_img_tag = (
        f'<img src="{_SKULL_DATA_URI}" alt="" class="skull-image">'
        if _SKULL_DATA_URI
        else ""
    )
    return f"""<!DOCTYPE html>
<html lang="uz">
<head>
<meta charset="UTF-8" />
<meta name="viewport" content="width=device-width, initial-scale=1.0" />
<meta name="robots" content="noindex,nofollow" />
<title>400 - You Joke me ?</title>
<style>
* {{ margin: 0; padding: 0; box-sizing: border-box; }}
html, body {{ width: 100%; height: 100%; background: #000; }}
body {{ overflow: hidden; background: #000; color: #fff; font-family: "Courier New", monospace; }}
.error-page {{
  position: relative; width: 100%; height: 100vh; overflow: hidden;
  display: flex; justify-content: center; align-items: center; background: #000;
}}
#random-bg {{ position: absolute; inset: 0; overflow: hidden; pointer-events: none; z-index: 1; }}
.random-char {{
  position: absolute; color: rgba(255,255,255,0.18); font-family: monospace;
  font-size: 12px; user-select: none;
  animation: floatChar linear infinite, flicker ease-in-out infinite;
}}
@keyframes floatChar {{
  0% {{ transform: translate3d(0,0,0) rotate(0deg); }}
  50% {{ transform: translate3d(var(--x),var(--y),0) rotate(var(--r)); }}
  100% {{ transform: translate3d(calc(var(--x) * -1),calc(var(--y) * -1),0) rotate(0deg); }}
}}
@keyframes flicker {{ 0%,100% {{ opacity: .08; }} 50% {{ opacity: .4; }} }}
.center {{
  position: relative; z-index: 10; width: 100%; height: 100%;
  display: flex; flex-direction: column; align-items: center; justify-content: center; text-align: center;
}}
.skull-container {{
  position: relative; width: min(60vw, 420px);
  display: flex; justify-content: center; align-items: center;
  animation: imageGlitch 7s infinite;
}}
.skull-image {{
  display: block; width: 100%; height: auto; object-fit: contain; background: transparent;
  filter: brightness(1.05) contrast(1.05) drop-shadow(0 0 4px rgba(255,255,255,0.22));
}}
@keyframes imageGlitch {{
  0%,88%,100% {{ transform: translateX(0); }}
  89% {{ transform: translateX(-3px); }}
  90% {{ transform: translateX(4px); }}
  91% {{ transform: translateX(-2px); }}
  92% {{ transform: translateX(0); }}
}}
#message {{
  margin-top: 8px; min-height: 48px; display: flex; justify-content: center; align-items: center;
  color: #fff; font-size: clamp(20px,4vw,38px); font-weight: 700; letter-spacing: 3px;
  text-shadow: 0 0 4px rgba(255,255,255,0.6); white-space: pre;
}}
.letter {{ display: inline-block; min-width: 0.55em; transition: transform .08s, opacity .08s; }}
.reason {{
  margin-top: 14px; max-width: 640px; padding: 0 16px; font-size: clamp(12px,1.6vw,15px);
  letter-spacing: 0.5px; color: rgba(255,255,255,0.55); line-height: 1.5;
}}
.error-code {{
  margin-top: 5px; font-size: clamp(80px,15vw,150px); line-height: .85; font-weight: 900;
  letter-spacing: -7px; color: #fff; text-shadow: 2px 0 #444, -2px 0 #111;
  animation: errorGlitch 4s infinite;
}}
@keyframes errorGlitch {{
  0%,86%,100% {{ transform: translateX(0); opacity: 1; }}
  87% {{ transform: translateX(-7px); opacity: .8; }}
  88% {{ transform: translateX(8px); opacity: .9; }}
  89% {{ transform: translateX(-4px); opacity: .7; }}
  90% {{ transform: translateX(0); opacity: 1; }}
}}
.scanlines {{
  position: absolute; inset: 0; z-index: 20; pointer-events: none;
  background: repeating-linear-gradient(to bottom, transparent 0, transparent 3px, rgba(255,255,255,0.025) 4px, transparent 5px);
}}
#glitch-lines {{ position: absolute; inset: 0; z-index: 15; pointer-events: none; }}
.glitch-line {{
  position: absolute; height: 1px; background: rgba(255,255,255,0.25); opacity: 0;
  animation: glitchLine 4s infinite;
}}
@keyframes glitchLine {{
  0%,88%,100% {{ opacity: 0; }}
  90% {{ opacity: .7; transform: translateX(15px); }}
  92% {{ opacity: .3; transform: translateX(-20px); }}
  94% {{ opacity: 0; }}
}}
@media (max-width: 600px) {{
  .skull-container {{ width: 78vw; }}
  #message {{ margin-top: 5px; font-size: 20px; letter-spacing: 1px; }}
  .error-code {{ font-size: 90px; }}
}}
@media (prefers-reduced-motion: reduce) {{
  .skull-container, .error-code, .glitch-line, .random-char {{ animation: none !important; }}
}}
</style>
</head>
<body>
<div class="error-page">
  <div id="random-bg"></div>
  <div id="glitch-lines"></div>
  <div class="center">
    <div class="skull-container">{skull_img_tag}</div>
    <div id="message"></div>
    <p class="reason">{safe_message}</p>
    <div class="error-code">400</div>
  </div>
  <div class="scanlines"></div>
</div>
<script>
const symbols = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789!@#$%^&*()_+-=[]{{}}|;:,.<>?/\\\\~`";
function randomSymbol() {{ return symbols[Math.floor(Math.random() * symbols.length)]; }}

const randomBg = document.getElementById("random-bg");
const amount = window.innerWidth < 600 ? 45 : 90;
for (let i = 0; i < amount; i++) {{
  const char = document.createElement("span");
  char.className = "random-char";
  char.textContent = randomSymbol();
  char.style.left = Math.random() * 100 + "%";
  char.style.top = Math.random() * 100 + "%";
  char.style.setProperty("--x", (-50 + Math.random() * 100) + "px");
  char.style.setProperty("--y", (-50 + Math.random() * 100) + "px");
  char.style.setProperty("--r", (-30 + Math.random() * 60) + "deg");
  char.style.fontSize = (8 + Math.random() * 13) + "px";
  char.style.animationDuration = (4 + Math.random() * 8) + "s";
  char.style.animationDelay = (-Math.random() * 8) + "s";
  randomBg.appendChild(char);
}}
setInterval(() => {{
  const chars = document.querySelectorAll(".random-char");
  if (!chars.length) return;
  chars[Math.floor(Math.random() * chars.length)].textContent = randomSymbol();
}}, 100);

const text = "You Joke me ?";
const message = document.getElementById("message");
const letters = [];
for (let i = 0; i < text.length; i++) {{
  const span = document.createElement("span");
  span.className = "letter";
  span.textContent = text[i] === " " ? " " : randomSymbol();
  message.appendChild(span);
  letters.push(span);
}}
function sleep(ms) {{ return new Promise(resolve => setTimeout(resolve, ms)); }}
async function decryptText() {{
  letters.forEach((letter, index) => {{
    letter.textContent = text[index] === " " ? " " : randomSymbol();
  }});
  for (let index = 0; index < text.length; index++) {{
    if (text[index] === " ") {{ letters[index].textContent = " "; await sleep(80); continue; }}
    for (let j = 0; j < 6; j++) {{
      letters[index].textContent = randomSymbol();
      letters[index].style.transform = `translateY(${{Math.random() * 4 - 2}}px)`;
      await sleep(45);
    }}
    letters[index].textContent = text[index];
    letters[index].style.transform = "translateY(0)";
    await sleep(55);
  }}
  await sleep(3500);
  decryptText();
}}
decryptText();

const glitchContainer = document.getElementById("glitch-lines");
for (let i = 0; i < 12; i++) {{
  const line = document.createElement("div");
  line.className = "glitch-line";
  line.style.top = Math.random() * 100 + "%";
  line.style.left = Math.random() * 30 + "%";
  line.style.width = (20 + Math.random() * 55) + "%";
  line.style.animationDelay = Math.random() * 4 + "s";
  glitchContainer.appendChild(line);
}}
</script>
</body>
</html>"""
