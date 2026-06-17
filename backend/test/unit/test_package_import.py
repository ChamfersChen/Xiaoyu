import sys


def test_import_xiaoyu_does_not_eagerly_import_knowledge(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    sys.modules.pop("xiaoyu", None)
    sys.modules.pop("xiaoyu.knowledge", None)

    import xiaoyu

    assert xiaoyu.get_version() == xiaoyu.__version__
    assert "xiaoyu.knowledge" not in sys.modules
