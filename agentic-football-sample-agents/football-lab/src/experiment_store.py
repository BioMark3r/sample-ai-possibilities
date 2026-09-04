"""SQLite schema and persistence for reproducible football experiments."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS benchmarks (
 benchmark_id TEXT PRIMARY KEY, created_at TEXT NOT NULL, team TEXT NOT NULL, role TEXT NOT NULL,
 runs INTEGER NOT NULL, corpus_path TEXT, corpus_sha256 TEXT NOT NULL, configuration_json TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS scenarios (
 scenario_id TEXT PRIMARY KEY, metadata_json TEXT NOT NULL, payload_json TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS decisions (
 id INTEGER PRIMARY KEY AUTOINCREMENT, benchmark_id TEXT NOT NULL REFERENCES benchmarks(benchmark_id),
 scenario_id TEXT NOT NULL REFERENCES scenarios(scenario_id), run_index INTEGER NOT NULL,
 result_json TEXT NOT NULL, UNIQUE(benchmark_id, scenario_id, run_index));
CREATE INDEX IF NOT EXISTS decisions_benchmark_idx ON decisions(benchmark_id);
"""


class ExperimentStore:
    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.connection = sqlite3.connect(self.path)
        self.connection.executescript(SCHEMA)
        self.connection.commit()

    def save(self, benchmark: dict, scenarios: list[dict], decisions: list[dict]) -> None:
        with self.connection:
            self.connection.execute("INSERT INTO benchmarks VALUES (?,?,?,?,?,?,?,?)",
                (benchmark["benchmark_id"], benchmark["created_at"], benchmark["team"], benchmark["role"],
                 benchmark["runs"], benchmark.get("corpus_path"), benchmark["corpus_sha256"],
                 json.dumps(benchmark, sort_keys=True)))
            self.connection.executemany("INSERT OR IGNORE INTO scenarios VALUES (?,?,?)", [
                (row["metadata"]["scenario_id"], json.dumps(row["metadata"], sort_keys=True),
                 json.dumps(row["payload"], sort_keys=True)) for row in scenarios])
            self.connection.executemany(
                "INSERT INTO decisions(benchmark_id, scenario_id, run_index, result_json) VALUES (?,?,?,?)",
                [(row["benchmark_id"], row["scenario_id"], row["run_index"], json.dumps(row, sort_keys=True))
                 for row in decisions])

    def benchmark(self, benchmark_id: str) -> dict:
        row = self.connection.execute("SELECT configuration_json FROM benchmarks WHERE benchmark_id=?", (benchmark_id,)).fetchone()
        if not row:
            raise KeyError(f"Unknown benchmark {benchmark_id}")
        benchmark = json.loads(row[0])
        benchmark["decisions"] = [json.loads(item[0]) for item in self.connection.execute(
            "SELECT result_json FROM decisions WHERE benchmark_id=? ORDER BY id", (benchmark_id,))]
        return benchmark

    def close(self):
        self.connection.close()
