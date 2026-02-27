import os
import sys
import json
import importlib

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))


class DummyCol:
    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def metric(self, *a, **k):
        return None

    def subheader(self, *a, **k):
        return None

    def dataframe(self, *a, **k):
        return None


class FakeSidebar:
    def header(self, *a, **k):
        return None

    def button(self, *a, **k):
        return False


class FakeStreamlit:
    def set_page_config(self, *a, **k):
        return None

    def title(self, *a, **k):
        return None

    def markdown(self, *a, **k):
        return None

    @property
    def sidebar(self):
        return FakeSidebar()

    def columns(self, n):
        if isinstance(n, int):
            return tuple(DummyCol() for _ in range(n))
        # allow passing a list like [2,1]
        return tuple(DummyCol() for _ in n)

    def warning(self, *a, **k):
        return None

    def info(self, *a, **k):
        return None

    def metric(self, *a, **k):
        return None

    def subheader(self, *a, **k):
        return None

    def plotly_chart(self, *a, **k):
        return None

    def dataframe(self, *a, **k):
        return None

    def expander(self, *a, **k):
        class _E:
            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, tb):
                return False

        return _E()

    def write(self, *a, **k):
        return None


def test_load_data_from_log(tmp_path, monkeypatch):
    # prepare fake streamlit before importing dashboard
    import types

    fake_st = FakeStreamlit()
    monkeypatch.setitem(sys.modules, "streamlit", fake_st)

    # create a log file expected by dashboard
    monkeypatch.chdir(tmp_path)
    data = [{"symbol": "A", "action": "BUY", "price": 10.0, "timestamp": "2026-01-01 00:00:00"}]
    (tmp_path / "trade_logs.json").write_text(json.dumps(data))

    # import dashboard and call load_data
    dashboard = importlib.import_module("dashboard")
    df = dashboard.load_data()
    assert not df.empty
    assert "symbol" in df.columns
    assert df.iloc[0]["symbol"] == "A"
