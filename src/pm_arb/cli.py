"""CLI for PM Arbitrage pilot."""

import asyncio
import os
import signal
import time
from datetime import datetime

import click
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from pm_arb.db import close_pool, get_pool, init_db
from pm_arb.db.repository import PaperTradeRepository
from pm_arb.pilot import get_pid_file

console = Console()


@click.group()
def cli() -> None:
    """PM Arbitrage CLI."""
    pass


@cli.command()
@click.option("--days", default=1, help="Number of days to include in report")
@click.option("--json", "as_json", is_flag=True, help="Output as JSON")
def report(days: int, as_json: bool) -> None:
    """Generate daily summary report."""
    asyncio.run(_report(days, as_json))


async def _report(days: int, as_json: bool) -> None:
    """Async report generation."""
    pool = None
    try:
        await init_db()
        pool = await get_pool()
        repo = PaperTradeRepository(pool)

        summary = await repo.get_daily_summary(days)

        if as_json:
            import json

            click.echo(json.dumps(summary, indent=2, default=str))
            return

        # Header
        console.print(
            Panel(
                f"[bold]PM Arbitrage - Daily Summary[/bold]\n"
                f"[dim]{datetime.now().strftime('%Y-%m-%d')} | Last {days} day(s)[/dim]",
                style="blue",
            )
        )

        # Trades summary
        trades_table = Table(title="TRADES", show_header=False, box=None)
        trades_table.add_column("Metric", style="dim")
        trades_table.add_column("Value", style="bold")
        trades_table.add_row("Total trades", str(summary["total_trades"]))
        trades_table.add_row("Open positions", str(summary["open_trades"]))
        trades_table.add_row("Closed", str(summary["closed_trades"]))
        console.print(trades_table)
        console.print()

        # P&L summary
        pnl = summary["realized_pnl"]
        pnl_color = "green" if pnl >= 0 else "red"
        win_rate = summary["win_rate"] * 100
        wins = summary["wins"]
        losses = summary["losses"]

        pnl_table = Table(title="P&L (Paper)", show_header=False, box=None)
        pnl_table.add_column("Metric", style="dim")
        pnl_table.add_column("Value")
        pnl_table.add_row("Realized P&L", f"[{pnl_color}]${pnl:+,.2f}[/{pnl_color}]")
        pnl_table.add_row("Win rate", f"{win_rate:.0f}% ({wins}/{wins + losses})")
        console.print(pnl_table)
        console.print()

        # By opportunity type
        if summary["by_opportunity_type"]:
            type_table = Table(title="BY OPPORTUNITY TYPE")
            type_table.add_column("Type")
            type_table.add_column("Trades", justify="right")
            type_table.add_column("P&L", justify="right")
            for row in summary["by_opportunity_type"]:
                pnl_val = row["pnl"]
                pnl_str = (
                    f"[green]${pnl_val:+,.2f}[/green]"
                    if pnl_val >= 0
                    else f"[red]${pnl_val:+,.2f}[/red]"
                )
                type_table.add_row(row["type"], str(row["trades"]), pnl_str)
            console.print(type_table)
            console.print()

        # Risk rejections
        if summary["risk_rejections"]:
            reject_table = Table(title="RISK EVENTS")
            reject_table.add_column("Reason")
            reject_table.add_column("Count", justify="right")
            for row in summary["risk_rejections"]:
                reject_table.add_row(row["reason"] or "unknown", str(row["count"]))
            console.print(reject_table)

    finally:
        if pool:
            await close_pool()


@cli.command()
def pilot() -> None:
    """Start the pilot orchestrator."""
    from pm_arb.pilot import main

    asyncio.run(main())


@cli.command()
def version() -> None:
    """Show version."""
    click.echo("pm-arbitrage 0.1.0")


@cli.command()
@click.option("--force", is_flag=True, help="Force kill with SIGKILL if graceful stop fails")
@click.option("--timeout", default=10, help="Seconds to wait for graceful shutdown")
def stop(force: bool, timeout: int) -> None:
    """Stop the running pilot gracefully."""
    pid_file = get_pid_file()

    if not pid_file.exists():
        console.print("[yellow]No running pilot found (pid file missing)[/yellow]")
        return

    try:
        pid = int(pid_file.read_text().strip())
    except ValueError:
        console.print("[red]Invalid PID file contents[/red]")
        pid_file.unlink(missing_ok=True)
        return

    # Check if process is actually running
    try:
        os.kill(pid, 0)  # Signal 0 just checks if process exists
    except ProcessLookupError:
        console.print(f"[yellow]Process {pid} not running, cleaning up stale pid file[/yellow]")
        pid_file.unlink(missing_ok=True)
        return
    except PermissionError:
        console.print(f"[red]No permission to signal process {pid}[/red]")
        return

    # Send SIGTERM for graceful shutdown
    console.print(f"[blue]Sending SIGTERM to pilot (PID {pid})...[/blue]")
    try:
        os.kill(pid, signal.SIGTERM)
    except ProcessLookupError:
        console.print("[green]Pilot already stopped[/green]")
        pid_file.unlink(missing_ok=True)
        return

    # Wait for graceful shutdown
    start = time.time()
    while time.time() - start < timeout:
        try:
            os.kill(pid, 0)
            time.sleep(0.5)
        except ProcessLookupError:
            console.print("[green]Pilot stopped gracefully[/green]")
            pid_file.unlink(missing_ok=True)
            return

    # Process still running after timeout
    if force:
        console.print("[yellow]Graceful shutdown timed out, sending SIGKILL...[/yellow]")
        try:
            os.kill(pid, signal.SIGKILL)
            time.sleep(0.5)
            console.print("[green]Pilot force-killed[/green]")
        except ProcessLookupError:
            console.print("[green]Pilot stopped[/green]")
        pid_file.unlink(missing_ok=True)
    else:
        console.print(
            f"[red]Pilot did not stop within {timeout}s. Use --force to kill.[/red]"
        )


@cli.command()
def status() -> None:
    """Check if the pilot is running."""
    pid_file = get_pid_file()

    if not pid_file.exists():
        console.print("[dim]Pilot is not running[/dim]")
        return

    try:
        pid = int(pid_file.read_text().strip())
    except ValueError:
        console.print("[yellow]Invalid PID file[/yellow]")
        return

    # Check if process is actually running
    try:
        os.kill(pid, 0)
        console.print(f"[green]Pilot is running[/green] (PID {pid})")
    except ProcessLookupError:
        console.print("[yellow]Pilot not running (stale pid file)[/yellow]")
    except PermissionError:
        console.print(f"[yellow]Pilot may be running as different user[/yellow] (PID {pid})")


if __name__ == "__main__":
    cli()
