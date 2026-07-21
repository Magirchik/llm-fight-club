import argparse

from .server import DashboardServer


def main() -> None:
    parser = argparse.ArgumentParser(description="LLM Fight Club Dashboard")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--config-dir", default="config")
    parser.add_argument("--experiments-dir", default="experiments")
    args = parser.parse_args()
    server = DashboardServer(
        config_dir=args.config_dir,
        experiments_dir=args.experiments_dir,
        host=args.host,
        port=args.port,
    )
    server.serve()


if __name__ == "__main__":
    main()
