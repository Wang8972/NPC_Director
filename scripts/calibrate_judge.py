import json
from pathlib import Path

from eval.judge import calibrate, load_calibration


def main() -> None:
    report = calibrate(load_calibration(Path("eval/judge/calibration.jsonl")))
    output = Path("eval/reports/judge_calibration.json")
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(report.model_dump(mode="json"), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(output)


if __name__ == "__main__":
    main()
