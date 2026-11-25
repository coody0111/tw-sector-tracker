from scripts.check_pages_site import broken_refs, disallowed_files, main, relative_refs


def _site(tmp_path, files: dict[str, str]):
    for name, text in files.items():
        p = tmp_path / name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding="utf-8")
    return tmp_path


def test_allowlist_passes_pages_json_and_nojekyll(tmp_path):
    site = _site(tmp_path, {"index.html": "", ".nojekyll": "", "weekly/index.json": "[]"})
    assert disallowed_files(site) == []


def test_allowlist_flags_internal_docs(tmp_path):
    site = _site(tmp_path, {"index.html": "", "CONTEXT.md": "", "superpowers/specs/a.md": ""})
    assert disallowed_files(site) == ["CONTEXT.md", "superpowers/specs/a.md"]


def test_relative_refs_skips_external_anchor_and_template():
    html = """<a href="https://x.com">x</a><a href="#heat">h</a><a href="mailto:a@b">m</a>
    <script src="//cdn.x/y.js"></script><a href="/abs.html">a</a><a href="${u}.html">t</a>"""
    assert relative_refs(html) == []


def test_relative_refs_strips_query_and_hash():
    assert relative_refs('<a href="index.html#heat">h</a><a href="chips.html?x=1">c</a>') == \
        ["index.html", "chips.html"]


def test_relative_refs_catches_fetch_and_location_prefix():
    html = "fetch('weekly/index.json'); location.href='weekly/'+sel.value+'.html'"
    assert relative_refs(html) == ["weekly/index.json", "weekly/"]


def test_relative_refs_does_not_treat_js_property_as_attribute():
    # location.href 只被第三條抓一次；img.src= 是 JS 屬性，不當 HTML 屬性
    assert relative_refs("location.href='x.html'; img.src='y.png'") == ["x.html"]


def test_broken_refs_flags_missing_history_folder(tmp_path):
    # 11/25 改走 Actions 時漏複製 weekly/ 的情況
    site = _site(tmp_path, {"weekly.html": "fetch('weekly/index.json'); location.href='weekly/'+v"})
    assert broken_refs(site) == ["weekly.html → weekly/", "weekly.html → weekly/index.json"]


def test_broken_refs_passes_when_folder_copied_and_parent_link(tmp_path):
    site = _site(tmp_path, {
        "weekly.html": "fetch('weekly/index.json'); location.href='weekly/'+v",
        "weekly/index.json": "[]",
        "weekly/2026-11-20.html": '<a href="../">home</a><a href="../weekly.html">w</a>',
    })
    assert broken_refs(site) == []


def test_broken_refs_resolves_from_base_href(tmp_path):
    # 歷史頁用 <base href="../">，導覽列的 chips.html 指的是根目錄那頁，不是 reports/chips.html
    site = _site(tmp_path, {
        "chips.html": "",
        "reports/2026-11-02.html": '<base href="../"><a href="chips.html">c</a>',
        "weekly/2026-11-20.html": '<base href="../"><a href="nope.html">n</a>',
    })
    assert broken_refs(site) == ["weekly/2026-11-20.html → nope.html"]


def test_broken_refs_flags_escape_outside_site(tmp_path):
    site = _site(tmp_path, {"index.html": '<a href="../secret.html">x</a>'})
    assert broken_refs(site) == ["index.html → ../secret.html（跑到 _site 外面）"]


def test_main_exit_codes(tmp_path, capsys):
    good = _site(tmp_path / "good", {"index.html": '<a href="index.html">i</a>'})
    bad = _site(tmp_path / "bad", {"index.html": '<a href="nope.html">n</a>', "a.md": ""})
    assert main(["x", str(good)]) == 0
    assert main(["x", str(bad)]) == 1
    out = capsys.readouterr().out
    assert "a.md" in out and "nope.html" in out and "pages.yml" in out
    assert main(["x", str(tmp_path / "missing")]) == 2
