"""Pages 上線前檢查 _site（2026-11-25）。

pages.yml 打包完、上傳前跑。兩條規則，任一條不過就讓部署失敗：
1. 白名單：_site 裡只能有 .html／.json 和 .nojekyll。內部文件（superpowers/、adr/、*.md）
   不能上線——8/28 定了這條，但 Pages 設定一直是 legacy、整個 docs/ 都被公開到 11/25 才發現。
2. 相對連結：頁面裡 href／src／fetch('…')／location.href='…' 指到的檔案或資料夾都要在 _site 裡。
   11/25 改走 Actions 時漏了 reports/、weekly/，歷史切換 404。

只用標準庫（runner 上沒裝 requirements）。用法：
    python scripts/check_pages_site.py _site
"""
import re
import sys
from pathlib import Path

ALLOWED_SUFFIXES = {".html", ".json"}
ALLOWED_NAMES = {".nojekyll"}

_REF_PATTERNS = [
    re.compile(r"""\b(?:href|src)\s*=\s*["']([^"']*)["']"""),
    re.compile(r"""\bfetch\(\s*["']([^"']*)["']"""),
    re.compile(r"""\blocation\.href\s*=\s*["']([^"']*)["']"""),
]
_SCHEME = re.compile(r"^[a-zA-Z][a-zA-Z0-9+.-]*:")
# 歷史頁（reports/、weekly/）用 <base href="../"> 讓導覽列連回根目錄；連結要從 base 解析
_BASE = re.compile(r"""<base\b[^>]*\bhref\s*=\s*["']([^"']*)["'][^>]*>""", re.IGNORECASE)


def disallowed_files(site: Path) -> list[str]:
    bad = []
    for p in sorted(site.rglob("*")):
        if p.is_file() and p.suffix not in ALLOWED_SUFFIXES and p.name not in ALLOWED_NAMES:
            bad.append(p.relative_to(site).as_posix())
    return bad


def relative_refs(html: str) -> list[str]:
    refs = []
    for pat in _REF_PATTERNS:
        for ref in pat.findall(html):
            if not ref or ref.startswith(("#", "/")) or _SCHEME.match(ref) or "${" in ref:
                continue
            ref = ref.split("#", 1)[0].split("?", 1)[0]
            if ref:
                refs.append(ref)
    return refs


def broken_refs(site: Path) -> list[str]:
    root = site.resolve()
    bad = []
    for page in sorted(site.rglob("*.html")):
        text = page.read_text(encoding="utf-8", errors="replace")
        base_dir = page.parent
        m = _BASE.search(text)
        if m:
            base_dir = page.parent / m.group(1)
            text = _BASE.sub("", text)
        for ref in sorted(set(relative_refs(text))):
            target = (base_dir / ref).resolve()
            if root != target and root not in target.parents:
                bad.append(f"{page.relative_to(site).as_posix()} → {ref}（跑到 _site 外面）")
            elif not target.exists():
                bad.append(f"{page.relative_to(site).as_posix()} → {ref}")
    return bad


def main(argv: list[str]) -> int:
    if len(argv) != 2 or not Path(argv[1]).is_dir():
        print("用法：python scripts/check_pages_site.py <_site 資料夾>")
        return 2
    site = Path(argv[1])
    files = disallowed_files(site)
    refs = broken_refs(site)
    if files:
        print("❌ _site 有不該公開的檔案（只允許 .html／.json／.nojekyll）：")
        print("\n".join(f"   {f}" for f in files))
        print("   → 內部文件留在 docs/ 就好；檢查 pages.yml 的 Prepare 步驟是不是複製了整個資料夾。")
        print("   → 真的要上線新檔案類型（例如 .css），把副檔名加進 ALLOWED_SUFFIXES。")
    if refs:
        print("❌ 頁面連到 _site 裡沒有的檔案或資料夾：")
        print("\n".join(f"   {r}" for r in refs))
        print("   → 在 pages.yml 的 Prepare 步驟把缺的檔案／資料夾 cp 進 _site。")
    if files or refs:
        return 1
    print(f"✅ _site 檢查通過：{sum(1 for p in site.rglob('*') if p.is_file())} 個檔案")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
