import asyncio
import sys
from pathlib import Path

from .orchestrator import batch_run, load_config, run_experiment


def _usage() -> int:
    sys.stderr.write(
        "Usage:\n"
        "  python -m fightclub run <config.toml>\n"
        "  python -m fightclub batch <dir>\n"
    )
    return 2


def _print_result(result) -> None:
    winner = result.winner if result.winner is not None else "none"
    print(
        f"[{result.experiment_id}] finished: reason={result.reason}, "
        f"winner={winner}"
    )
    print(f"  events: {result.events_path}")
    print(f"  meta:   {result.meta_path}")


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if len(argv) < 2:
        return _usage()
    command = argv[0]
    target = argv[1]
    if command == "run":
        config = load_config(target)
        result = asyncio.run(run_experiment(config))
        _print_result(result)
        return 0
    if command == "batch":
        directory = Path(target)
        if not directory.is_dir():
            sys.stderr.write(f"Not a directory: {directory}\n")
            return 2
        configs = [load_config(p) for p in sorted(directory.glob("*.toml"))]
        if not configs:
            sys.stderr.write(f"No .toml files in {directory}\n")
            return 2
        results = asyncio.run(batch_run(configs))
        for result in results:
            _print_result(result)
        return 0
    return _usage()


if __name__ == "__main__":
    raise SystemExit(main())
