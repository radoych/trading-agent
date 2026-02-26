import json
import os
from datetime import datetime

LOG_FILE = "trade_logs.json"

def log_trade(data):
    logs = []
    if os.path.exists(LOG_FILE):
        with open(LOG_FILE, "r") as f:
            logs = json.load(f)
    
    data["timestamp"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    logs.append(data)
    
    with open(LOG_FILE, "w") as f:
        json.dump(logs, f, indent=4)