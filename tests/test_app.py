

def test_static_build_writes_one_page(tmp_path, monkeypatch):
    import importlib.util
    from pathlib import Path
    from src import data as data_mod
    spec = importlib.util.spec_from_file_location(
        "build_static", Path(__file__).resolve().parent.parent / "scripts" / "build_static.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    monkeypatch.setattr(mod, "OUT", tmp_path / "site")
    monkeypatch.setattr(mod, "build", lambda use_live=True: data_mod.build(use_live=False))
    mod.main()
    html = (tmp_path / "site" / "index.html").read_text()
    assert "Australia: macro drivers of credit risk" in html and "Credit risk scorecard" in html
    assert html.count('class="card" id="c-') == 9
