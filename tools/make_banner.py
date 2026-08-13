#!/usr/bin/env python3
"""README バナー生成テンプレート。

高解像度の絵文字（Noto 512px、フォールバック Twemoji 72px）を使って
滑らかなバナー画像を生成する。

使い方:
    python make_banner.py "dler-kun" \
        --subtitle "複数サイトのメディアを、ひとつの CLI でダウンロード" \
        --emoji 1f4e5 --color1 "(40,90,200)" --color2 "(150,60,220)" \
        -o banner.png
"""
from __future__ import annotations

import argparse
import io
import urllib.request
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

NOTO = "https://cdn.jsdelivr.net/gh/googlefonts/noto-emoji@main/png/512/emoji_u{cp}.png"
TWEMOJI = "https://cdn.jsdelivr.net/gh/twitter/twemoji@14.0.2/assets/72x72/{cp}.png"


def parse_color(text: str) -> tuple[int, int, int]:
    return tuple(int(x) for x in text.strip("() ").split(","))


def fetch_emoji(cp: str, size: int) -> Image.Image:
    last = None
    for url in (NOTO, TWEMOJI):
        try:
            with urllib.request.urlopen(url.format(cp=cp), timeout=20) as r:
                data = r.read()
            img = Image.open(io.BytesIO(data)).convert("RGBA")
            return img.resize((size, size), Image.LANCZOS)
        except Exception as exc:  # noqa: BLE001
            last = exc
    raise RuntimeError(f"emoji {cp} not available: {last}")


def grad(w: int, h: int, c1: tuple[int, int, int], c2: tuple[int, int, int]) -> Image.Image:
    img = Image.new("RGB", (w, h))
    d = ImageDraw.Draw(img)
    for y in range(h):
        t = y / max(h - 1, 1)
        d.line([(0, y), (w, y)], fill=tuple(int(a + (b - a) * t) for a, b in zip(c1, c2)))
    return img


def load_font(size: int) -> ImageFont.FreeTypeFont:
    for path in ("C:/Windows/Fonts/meiryo.ttc", "C:/Windows/Fonts/YuGothB.ttc"):
        try:
            return ImageFont.truetype(path, size)
        except OSError:
            continue
    return ImageFont.load_default()


def main() -> None:
    p = argparse.ArgumentParser(description="README バナー生成テンプレート")
    p.add_argument("title", help="タイトル")
    p.add_argument("--subtitle", default="", help="サブタイトル")
    p.add_argument("--signature", default="", help="署名（右下に表示）")
    p.add_argument("--emoji", default="1f4e5", help="絵文字の Unicode codepoint（hex）")
    p.add_argument("--color1", default="(40,90,200)", help="グラデ開始色 (R,G,B)")
    p.add_argument("--color2", default="(150,60,220)", help="グラデ終了色 (R,G,B)")
    p.add_argument("-o", "--out", default="banner.png", type=Path)
    p.add_argument("--width", type=int, default=1280)
    p.add_argument("--height", type=int, default=640)
    a = p.parse_args()

    c1, c2 = parse_color(a.color1), parse_color(a.color2)
    img = grad(a.width, a.height, c1, c2)

    margin_x = 70
    strip_h = 210
    strip_top = a.height - strip_h

    # 絵文字: 下部帯より上に配置
    emoji_size = max(220, a.height // 2)
    emoji = fetch_emoji(a.emoji.lower(), emoji_size)
    img.paste(emoji, (margin_x, strip_top - emoji_size - 10), emoji)

    overlay = Image.new("RGBA", img.size, (0, 0, 0, 0))
    od = ImageDraw.Draw(overlay)
    od.rectangle((0, strip_top, a.width, a.height), fill=(0, 0, 0, 150))
    img = Image.alpha_composite(img.convert("RGBA"), overlay)

    d = ImageDraw.Draw(img)
    title_font = load_font(int(a.height * 0.17))
    sub_font = load_font(int(a.height * 0.055)) if a.subtitle else None
    sig_font = load_font(int(a.height * 0.05)) if a.signature else None

    # テキストの実寸を計測して、下部帯内に縦中央で配置（重なり防止）
    tb = d.textbbox((0, 0), a.title, font=title_font)
    title_h = tb[3] - tb[1]
    if a.subtitle and sub_font:
        sb = d.textbbox((0, 0), a.subtitle, font=sub_font)
        sub_h = sb[3] - sb[1]
        gap = 12
        total_h = title_h + gap + sub_h
    else:
        sb = None
        sub_h = gap = 0
        total_h = title_h

    text_top = strip_top + (strip_h - total_h) / 2
    d.text((margin_x, text_top - tb[1]), a.title, font=title_font, fill=(255, 255, 255))
    if a.subtitle and sub_font and sb is not None:
        sub_top = text_top + title_h + gap
        d.text((margin_x + 2, sub_top - sb[1]), a.subtitle, font=sub_font, fill=(230, 235, 255))

    # 署名: 下部帯の右下に配置（縦中央）
    if a.signature and sig_font:
        sig = d.textbbox((0, 0), a.signature, font=sig_font)
        sig_w = sig[2] - sig[0]
        sig_h = sig[3] - sig[1]
        sig_y = strip_top + (strip_h - sig_h) / 2 - sig[1]
        d.text((a.width - margin_x - sig_w, sig_y), a.signature, font=sig_font, fill=(200, 205, 225))

    a.out.parent.mkdir(parents=True, exist_ok=True)
    img.convert("RGB").save(a.out)
    print(f"saved: {a.out}")


if __name__ == "__main__":
    main()
