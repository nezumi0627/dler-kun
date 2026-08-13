#!/usr/bin/env python3
"""README 用バナーの生成テンプレート。

使い方:
    python scripts/make_banner.py \
      --title "dler-kun" \
      --subtitle "複数サイトのメディアを、ひとつの CLI でダウンロード" \
      --emoji 1f4e5 \
      --c1 24,58,153 --c2 137,58,214 \
      -o .github/assets/banner.png

依存: Pillow（pip install Pillow）
"""
from __future__ import annotations

import argparse
import io
import math
import urllib.request
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont

TWEMOJI = "https://cdn.jsdelivr.net/gh/twitter/twemoji@14.0.2/assets/512x512/{cp}.png"
FONT_TITLE = "C:/Windows/Fonts/meiryo.ttc"
FONT_SUB = "C:/Windows/Fonts/meiryo.ttc"


def parse_color(raw: str) -> tuple[int, int, int]:
    return tuple(int(x) for x in raw.split(","))


def diagonal_gradient(w: int, h: int, c1, c2) -> Image.Image:
    img = Image.new("RGB", (w, h))
    d = ImageDraw.Draw(img)
    for y in range(h):
        for x in range(w):
            t = (x / max(w - 1, 1) + y / max(h - 1, 1)) / 2
            d.point((x, y), fill=tuple(int(a + (b - a) * t) for a, b in zip(c1, c2)))
    return img


def radial_glow(size: int, color: tuple[int, int, int], alpha_max: int = 200) -> Image.Image:
    glow = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(glow)
    cx = cy = size / 2
    max_r = size / 2
    for r in range(int(max_r), 0, -1):
        t = r / max_r
        a = int(alpha_max * (1 - t) ** 2)
        d.ellipse((cx - r, cy - r, cx + r, cy + r), fill=color + (a,))
    return glow


def title_with_shadow(img, pos, text, font, fill=(255, 255, 255),
                      shadow=(12, 16, 48), blur=8, offset=6):
    """タイトル文字にドロップシャドウを付けて描画する。"""
    layer = Image.new("RGBA", (font.getbbox(text)[2] + 120, font.size + 120), (0, 0, 0, 0))
    ld = ImageDraw.Draw(layer)
    ld.text((60, 60), text, font=font, fill=shadow + (210,))
    layer = layer.filter(ImageFilter.GaussianBlur(blur))
    img.alpha_composite(layer, (pos[0] - 60 + offset, pos[1] - 60 + offset))
    ImageDraw.Draw(img).text(pos, text, font=font, fill=fill)


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--title", default="dler-kun")
    p.add_argument("--subtitle", default="複数サイトのメディアを、ひとつの CLI でダウンロード")
    p.add_argument("--emoji", default="1f4e5", help="Twemoji code point (hex)")
    p.add_argument("--c1", default="18,42,120", help="gradient start RGB")
    p.add_argument("--c2", default="140,52,210", help="gradient end RGB")
    p.add_argument("--accent", default="255,205,80", help="accent RGB")
    p.add_argument("-o", "--out", default=".github/assets/banner.png")
    p.add_argument("--width", type=int, default=1280)
    p.add_argument("--height", type=int, default=640)
    a = p.parse_args()

    W, H = a.width, a.height
    c1, c2 = parse_color(a.c1), parse_color(a.c2)
    accent = parse_color(a.accent)

    # ── 背景：対角グラデーション ─────────────────────────────
    img = diagonal_gradient(W, H, c1, c2)

    # 左下の大きな放射光（深み）
    glow_r = int(H * 0.9)
    corner = radial_glow(glow_r, c2, alpha_max=70)
    img.alpha_composite(corner, (0, H - glow_r))

    # 右上のハイライト
    hi_r = int(H * 0.7)
    hi = radial_glow(hi_r, (255, 255, 255), alpha_max=26)
    img.alpha_composite(hi, (W - hi_r, 0))

    draw = ImageDraw.Draw(img)

    # ── 装飾：半透明のドット列（右上） ────────────────────────
    dot_r = 4
    for i in range(6):
        dx = W - 70 - i * 34
        dy = 54 + (i % 2) * 20
        draw.ellipse((dx - dot_r, dy - dot_r, dx + dot_r, dy + dot_r),
                     fill=(255, 255, 255, 60))

    # ── 絵文字タイル（フロストグラス風） ───────────────────────
    tile = 360
    pad = 26
    tx, ty = 70, (H - tile) // 2
    tile_img = Image.new("RGBA", (tile, tile), (0, 0, 0, 0))
    td = ImageDraw.Draw(tile_img)
    td.rounded_rectangle((0, 0, tile, tile), radius=72, fill=(255, 255, 255, 40),
                         outline=(255, 255, 255, 120), width=3)
    # タイル内の放射光
    inner = radial_glow(tile, (255, 255, 255), alpha_max=60)
    tile_img.alpha_composite(inner, (0, 0))
    # 高解像度絵文字
    with urllib.request.urlopen(TWEMOJI.format(cp=a.emoji), timeout=20) as r:
        emoji = Image.open(io.BytesIO(r.read())).convert("RGBA")
    emoji = emoji.resize((tile - pad * 2, tile - pad * 2), Image.LANCZOS)
    tile_img.alpha_composite(emoji, (pad, pad))
    img.alpha_composite(tile_img, (tx, ty))

    # ── テキストブロック ─────────────────────────────────────
    title_font = ImageFont.truetype(FONT_TITLE, 96)
    sub_font = ImageFont.truetype(FONT_SUB, 34)
    tag_font = ImageFont.truetype(FONT_SUB, 26)

    text_x = tx + tile + 60
    baseline_y = (H // 2) - 10

    # アクセント線（タイトル上）
    draw.rounded_rectangle((text_x, baseline_y - 96, text_x + 74, baseline_y - 90),
                           radius=3, fill=accent + (255,))

    # タイトル（ドロップシャドウ付き）
    title_with_shadow(img, (text_x, baseline_y - 100), a.title, title_font)

    # サブタイトル
    draw.text((text_x + 2, baseline_y + 34), a.subtitle, font=sub_font,
              fill=(225, 230, 255))

    # 下部バッジ（タグライン）
    badge = "media downloader CLI"
    draw.rounded_rectangle((text_x, baseline_y + 96, text_x + 210, baseline_y + 132),
                           radius=18, fill=(255, 255, 255, 26),
                           outline=(255, 255, 255, 90))
    draw.text((text_x + 18, baseline_y + 98), badge, font=tag_font, fill=(235, 238, 255))

    # ── 底部のアクセントバー ─────────────────────────────────
    bar_h = 8
    bar = Image.new("RGBA", (W, bar_h), (0, 0, 0, 0))
    bd = ImageDraw.Draw(bar)
    for x in range(W):
        t = x / max(W - 1, 1)
        col = tuple(int(x1 + (x2 - x1) * t) for x1, x2 in zip(accent, (255, 255, 255)))
        bd.line((x, 0, x, bar_h), fill=col + (255,))
    img.alpha_composite(bar, (0, H - bar_h))

    out = Path(a.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    img.convert("RGB").save(out)
    print(f"saved: {out} ({out.stat().st_size} bytes)")


if __name__ == "__main__":
    main()
