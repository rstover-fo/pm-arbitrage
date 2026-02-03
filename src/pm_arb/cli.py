"""CLI for PM Arbitrage pilot."""

import click


@click.group()
def cli() -> None:
    """PM Arbitrage CLI."""
    pass


@cli.command()
def version() -> None:
    """Show version."""
    click.echo("pm-arbitrage 0.1.0")


if __name__ == "__main__":
    cli()
