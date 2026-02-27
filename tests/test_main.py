import os
import sys
import asyncio

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import main


def test_handle_heartbeat():
    resp = asyncio.run(main.handle_heartbeat(None))
    text = getattr(resp, "text", None)
    if text is None and hasattr(resp, "body"):
        text = resp.body.decode()
    assert text == "ping"
