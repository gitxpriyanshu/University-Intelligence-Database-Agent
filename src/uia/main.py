"""Main entry point for the University Intelligence Database Agent (UIA).

Exposes CLI commands via Typer, loading university configurations,
running the pipeline, and saving structured outputs to JSON and CSV formats.
"""
import asyncio
import json
import logging
import os
from datetime import datetime, timezone
from typing import Optional

import pandas as pd
import typer
import yaml
from dotenv import load_dotenv
from rich.console import Console

from uia.agent.orchestrator import run_for_university, _get_default_for_type, TYPE_MAP
from uia.agent.planner import UniversityConfig
from uia.agent.validator import validate as validate_record
from uia.models.schema import ScrapedRecord, UniversityRecord, ValidationFlag
from uia.utils.llm_client import LLMClient, StubLLMClient

app = typer.Typer(help="University Intelligence Database Agent (UIA) CLI")
console = Console()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)


def _build_stub_record(config: UniversityConfig) -> ScrapedRecord:
    """Builds a fully-structured ScrapedRecord with all 10 fields populated via defaults.

    Used in --stub mode, bypassing all network and LLM calls. Every field defaults to
    its typed placeholder (empty lists, or single-field objects with 'Unknown' values)
    so the output JSON/CSV matches the ScrapedRecord schema exactly.
    """
    data: dict = {}
    for category, target_type in TYPE_MAP.items():
        data[category] = _get_default_for_type(target_type, config)

    record = UniversityRecord(**data)
    confidence, flags = validate_record(record, config.country)

    return ScrapedRecord(
        university_name=config.name,
        scraped_at=datetime.now(timezone.utc),
        data=record,
        field_confidence=confidence,
        validation_flags=flags,
    )


def _write_outputs(records: list[ScrapedRecord], output_dir: str) -> None:
    """Writes records to JSON array and flattened CSV in output_dir."""
    os.makedirs(output_dir, exist_ok=True)
    json_path = os.path.join(output_dir, "universities.json")
    csv_path = os.path.join(output_dir, "universities.csv")

    # Load existing records for incremental upsert
    all_records_dict: dict[str, ScrapedRecord] = {}
    if os.path.exists(json_path):
        try:
            with open(json_path, "r") as f:
                for entry in json.load(f):
                    try:
                        parsed = ScrapedRecord(**entry)
                        all_records_dict[parsed.university_name] = parsed
                    except Exception:
                        pass
        except Exception as e:
            console.print(f"[yellow]Warning: could not read existing JSON ({e}). Starting fresh.[/yellow]")

    for r in records:
        all_records_dict[r.university_name] = r

    final_records = list(all_records_dict.values())

    # JSON output
    try:
        with open(json_path, "w") as f:
            json.dump([r.model_dump(mode="json") for r in final_records], f, indent=2)
        console.print(f"[green]✔ JSON written → {json_path}[/green]")
    except Exception as e:
        console.print(f"[red]Error writing JSON: {e}[/red]")

    # CSV output — one row per (university, field)
    csv_rows = []
    for record in final_records:
        for field_name in record.data.__class__.model_fields:
            val = getattr(record.data, field_name)
            if isinstance(val, list):
                field_json = json.dumps([item.model_dump(mode="json") for item in val])
            elif hasattr(val, "model_dump"):
                field_json = val.model_dump_json()
            else:
                field_json = json.dumps(val)

            field_flags = [
                flag.model_dump(mode="json")
                for flag in record.validation_flags
                if flag.field == field_name
            ]
            csv_rows.append({
                "university_name": record.university_name,
                "field_name": field_name,
                "field_json": field_json,
                "confidence": record.field_confidence.get(field_name, 0.0),
                "flags_json": json.dumps(field_flags),
            })

    try:
        df = pd.DataFrame(csv_rows)
        df.to_csv(csv_path, index=False)
        console.print(f"[green]✔ CSV written  → {csv_path}[/green]")
    except Exception as e:
        console.print(f"[red]Error writing CSV: {e}[/red]")


@app.command()
def run(
    config_path: str = typer.Option(
        "config/universities.yaml",
        "--config", "-c",
        help="Path to the university configuration YAML file.",
    ),
    university: Optional[str] = typer.Option(
        None,
        "--university", "-u",
        help="Specific university name to scrape. If omitted, all configured universities are run.",
    ),
    stub: bool = typer.Option(
        False,
        "--stub",
        help=(
            "Skip all network I/O and LLM calls; emit structurally valid placeholder records. "
            "Useful for schema/pipeline validation without live credentials. "
            "To use live extraction, set GROQ_API_KEY in .env and omit this flag."
        ),
    ),
):
    """Run the university scraping, extraction, and validation pipeline.

    Loads configurations, plans discovery, executes headless crawling,
    performs LLM-based structured extraction, self-validates results,
    and exports data/output/universities.json and data/output/universities.csv.

    If GROQ_API_KEY is not set the LLM extraction stage is automatically
    replaced with StubLLMClient (returns empty dicts); all 10 fields still
    appear in the output with confidence 0.3 and medium-severity flags.
    Pass --stub to additionally skip HTTP scraping entirely.
    """
    load_dotenv()

    # Load YAML
    if not os.path.exists(config_path):
        console.print(f"[red]Error: config file not found at {config_path}[/red]")
        raise typer.Exit(code=1)

    try:
        with open(config_path, "r") as f:
            config_data = yaml.safe_load(f)
    except Exception as e:
        console.print(f"[red]Error reading config: {e}[/red]")
        raise typer.Exit(code=1)

    if not config_data or "universities" not in config_data:
        console.print("[red]Error: config must have a 'universities' root key.[/red]")
        raise typer.Exit(code=1)

    try:
        configs = [UniversityConfig(**entry) for entry in config_data["universities"]]
    except Exception as e:
        console.print(f"[red]Error parsing university config entries: {e}[/red]")
        raise typer.Exit(code=1)

    if university:
        configs = [c for c in configs if c.name.lower() == university.lower()]
        if not configs:
            console.print(f"[red]Error: '{university}' not found in config.[/red]")
            raise typer.Exit(code=1)

    # ------------------------------------------------------------------ #
    # STUB MODE — no network, no LLM, instant placeholder records
    # ------------------------------------------------------------------ #
    if stub:
        console.print(
            "[bold yellow]⚠  Running in STUB mode — no HTTP/LLM calls made.[/bold yellow]\n"
            "   To enable live extraction: set GROQ_API_KEY in .env and re-run without --stub."
        )
        records = [_build_stub_record(c) for c in configs]
        _write_outputs(records, "data/output")
        return

    # ------------------------------------------------------------------ #
    # LIVE MODE — real HTTP scraping + LLM extraction
    # ------------------------------------------------------------------ #
    api_key = os.getenv("GROQ_API_KEY", "")
    if not api_key:
        console.print(
            "[bold yellow]⚠  GROQ_API_KEY not set — using StubLLMClient (no LLM extraction).[/bold yellow]\n"
            "   HTTP scraping will still run; all fields will be empty (confidence 0.3).\n"
            "   To enable extraction: copy .env.example → .env and fill in GROQ_API_KEY."
        )
        llm_client = StubLLMClient()
    else:
        console.print("[green]✔ GROQ_API_KEY detected — using live LLMClient.[/green]")
        llm_client = LLMClient()

    async def run_pipeline():
        scraped = []
        for config in configs:
            console.print(f"[bold green]▶ Scraping {config.name}...[/bold green]")
            record = await run_for_university(config, llm_client)
            scraped.append(record)
            console.print(f"[green]✔ Finished {config.name}.[/green]")
        return scraped

    try:
        new_records = asyncio.run(run_pipeline())
    except Exception as e:
        console.print(f"[red]Fatal pipeline error: {e}[/red]")
        raise typer.Exit(code=1)
    finally:
        async def _close():
            await llm_client.close()
        asyncio.run(_close())

    _write_outputs(new_records, "data/output")


@app.command()
def version():
    """Print the version of the UIA CLI."""
    console.print("UIA CLI v0.1.0")


if __name__ == "__main__":
    app()
