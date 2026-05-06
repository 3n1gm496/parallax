import json
import time
from datetime import datetime, timezone

def generate_mock_replay(filename, count=1000):
    with open(filename, 'w') as f:
        for i in range(count):
            snapshot = {
                "id": f"snap_{i}",
                "platform": "polymarket",
                "market_id": "M1",
                "outcome": "YES",
                "captured_at": datetime.now(timezone.utc).isoformat(),
                "bids": {"levels": [{"price": 0.5, "size": 100}]},
                "asks": {"levels": [{"price": 0.51, "size": 100}]},
                "mid_price": 0.505,
                "spread_bps": 100
            }
            f.write(json.dumps(snapshot) + "\n")

if __name__ == "__main__":
    generate_mock_replay("mock_replay.jsonl", 10000)
    print("Generated mock_replay.jsonl with 10,000 snapshots.")
