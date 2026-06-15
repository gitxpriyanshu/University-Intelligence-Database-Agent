"""Main entry point for the University Intelligence Database Agent.

Exposes CLI commands via Typer and runs the FastAPI application.
"""
import typer

app = typer.Typer(help="University Intelligence Database Agent (UIA) CLI")

@app.command()
def run():
    """Run the university scraping and intel collection agent."""
    print("Running University Intelligence Database Agent...")

if __name__ == "__main__":
    app()
