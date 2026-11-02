"""舊網址 docs/heat.html（2026-11-02 Cody：族群熱度整合進族群績效）：只剩轉址到 index.html#heat，
Telegram 舊訊息、書籤點進來不會 404。熱度內容見 export/heat_section.py。"""
from pathlib import Path

REDIRECT = (
    '<!doctype html><html lang="zh-Hant"><head><meta charset="utf-8">'
    '<meta name="viewport" content="width=device-width,initial-scale=1">'
    '<meta http-equiv="refresh" content="0; url=index.html#heat"><link rel="canonical" href="index.html#heat">'
    '<title>族群熱度已移到族群績效</title><style>body{margin:0;padding:24px;background:#080B12;color:#DADFE8;'
    'font-family:"Public Sans",sans-serif}a{color:#F0BB55}</style></head><body>'
    '<p>族群熱度已經整合到<a href="index.html#heat">族群績效</a>最上方，正在幫你轉過去。</p>'
    '<script>location.replace("index.html#heat")</script></body></html>'
)


def render(heat: dict | None = None) -> str:
    return REDIRECT


def generate(heat: dict | None = None, output_path: str = "docs/heat.html") -> None:
    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    Path(output_path).write_text(REDIRECT, encoding="utf-8")
