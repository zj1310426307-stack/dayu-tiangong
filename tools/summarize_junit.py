"""Convert pytest JUnit XML into a small CI artifact summary."""

from __future__ import annotations

import argparse
import json
import xml.etree.ElementTree as ET
from pathlib import Path


def summarize_junit(path: Path) -> dict[str, int | float | str]:
    """Return stable aggregate counters from one pytest JUnit document."""

    root = ET.parse(path).getroot()
    suites = [root] if root.tag == "testsuite" else list(root.findall("testsuite"))
    return {
        "junit": path.as_posix(),
        "tests": sum(int(suite.attrib.get("tests", 0)) for suite in suites),
        "failures": sum(int(suite.attrib.get("failures", 0)) for suite in suites),
        "errors": sum(int(suite.attrib.get("errors", 0)) for suite in suites),
        "skipped": sum(int(suite.attrib.get("skipped", 0)) for suite in suites),
        "time_seconds": sum(float(suite.attrib.get("time", 0.0)) for suite in suites),
    }


def main() -> int:
    """Read JUnit XML and write UTF-8 JSON with LF newlines."""

    parser = argparse.ArgumentParser()
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    arguments = parser.parse_args()
    summary = summarize_junit(arguments.input)
    arguments.output.parent.mkdir(parents=True, exist_ok=True)
    serialized = json.dumps(summary, indent=2, sort_keys=True, allow_nan=False)
    arguments.output.write_text(serialized + "\n", encoding="utf-8", newline="\n")
    print(serialized)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
