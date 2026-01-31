#!/usr/bin/env python3
"""Script to run the PM Arbitrage dashboard."""

import subprocess
import sys
from pathlib import Path


def main() -> None:
    """Run the Streamlit dashboard."""
    project_root = Path(__file__).parent.parent

    # Parse mode argument
    mode = "mock"
    if len(sys.argv) > 1 and sys.argv[1] == "--live":
        mode = "live"

    if mode == "live":
        app_path = project_root / "src" / "pm_arb" / "dashboard" / "app_live.py"
        title = "PM Arbitrage Dashboard (Live)"
    else:
        app_path = project_root / "src" / "pm_arb" / "dashboard" / "app.py"
        title = "PM Arbitrage Dashboard (Mock)"

    if not app_path.exists():
        print(f"Error: Dashboard app not found at {app_path}")
        sys.exit(1)

    print(f"🚀 Starting {title}...")
    print(f"   App: {app_path}")
    print("   URL: http://localhost:8501")
    if mode == "live":
        print("   Note: Requires agents running (python scripts/run_agents.py)")
    print()

    subprocess.run(
        [
            sys.executable,
            "-m",
            "streamlit",
            "run",
            str(app_path),
            "--server.headless",
            "false",
            "--browser.gatherUsageStats",
            "false",
        ],
        check=True,
    )


if __name__ == "__main__":
    main()
