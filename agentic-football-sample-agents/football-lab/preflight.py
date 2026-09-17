#!/usr/bin/env python3
import json, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent / "src"))
from preflight import check_preflight
result=check_preflight(); print(result["status"]); print(json.dumps(result, indent=2))
raise SystemExit(0 if result["status"] != "BLOCKED" else 1)
