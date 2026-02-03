"""CLI for PM Arbitrage pilot."""

import asyncio
from datetime import datetime

import click
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from pm_arb.db import close_pool, get_pool, init_db
from pm_arb.db.repository import PaperTradeRepository

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
def version() -> None:
    """Show version."""
    click.echo("pm-arbitrage 0.1.0")


if __name__ == "__main__":
    cli()
