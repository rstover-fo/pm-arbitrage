#!/usr/bin/env python3
"""Script to run the PM Arbitrage dashboard."""

import subprocess
import sys
from pathlib import Path


def main() -> None:
    """Run the Streamlit dashboard."""
    # Get the path to app.py
    project_root = Path(__file__).parent.parent
    app_path = project_root / "src" / "pm_arb" / "dashboard" / "app.py"

    if not app_path.exists():
        print(f"Error: Dashboard app not found at {app_path}")
        sys.exit(1)

    print("🚀 Starting PM Arbitrage Dashboard...")
    print(f"   App: {app_path}")
    print("   URL: http://localhost:8501")
    print()

    # Run streamlit
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
