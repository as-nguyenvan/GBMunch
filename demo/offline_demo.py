#!/usr/bin/env python3
import json
from pathlib import Path

from gatorgrub.demo import run_demo

if __name__ == "__main__":
    fixture = Path(__file__).with_name("sample_events.json")
    print(json.dumps(run_demo(fixture), indent=2))
