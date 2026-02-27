import os
import sys
import json

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import logger


def test_log_trade_writes_file(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(logger, "LOG_FILE", str(tmp_path / "logs.json"))

    data = {"symbol": "ABC", "action": "BUY", "price": 12.34}
    logger.log_trade(data)

    path = tmp_path / "logs.json"
    assert path.exists()
    content = json.loads(path.read_text())
    assert isinstance(content, list)
    assert content[0]["symbol"] == "ABC"
    assert "timestamp" in content[0]