"""Main entry point for the University Intelligence Database Agent (UIA).

Exposes CLI commands via Typer, loading university configurations,
running the pipeline, and saving structured outputs to JSON and CSV formats.
"""
import asyncio
import json
import os
from typing import Optional

import pandas as pd
import typer
import yaml
from rich.console import Console

from uia.agent.orchestrator import run_for_university
from uia.agent.planner import UniversityConfig
from uia.models.schema import ScrapedRecord
from uia.utils.llm_client import LLMClient

app = typer.Typer(help="University Intelligence Database Agent (UIA) CLI")
console = Console()


@app.command()
def run(
    config_path: str = typer.Option(
        "config/universities.yaml",
        "--config",
        "-c",
        help="Path to the university configuration YAML file.",
    ),
    university: Optional[str] = typer.Option(
        None,
        "--university",
        "-u",
        help="Specific university name to scrape. If not provided, runs all configured universities.",
    ),
):
    """Run the university scraping, extraction, and validation pipeline.

    Loads configurations, plans discovery, executes headless crawling,
    performs LLM-based structured extraction, self-validates results,
    and exports data/output/universities.json and data/output/universities.csv.
    """
    if not os.path.exists(config_path):
        console.print(f"[red]Error: Config file not found at {config_path}[/red]")
        raise typer.Exit(code=1)

    try:
        with open(config_path, "r") as f:
            config_data = yaml.safe_load(f)
    except Exception as e:
        console.print(f"[red]Error reading configuration file: {e}[/red]")
        raise typer.Exit(code=1)

    if not config_data or "universities" not in config_data:
        console.print(f"[red]Error: Invalid config format in {config_path} (missing 'universities' root key)[/red]")
        raise typer.Exit(code=1)

    configs = []
    for entry in config_data["universities"]:
        try:
            configs.append(UniversityConfig(**entry))
        except Exception as e:
            console.print(f"[red]Error parsing configuration entry for '{entry.get('name', 'Unknown')}': {e}[/red]")
            raise typer.Exit(code=1)

    if university:
        filtered_configs = [c for c in configs if c.name.lower() == university.lower()]
        if not filtered_configs:
            console.print(f"[red]Error: University '{university}' not found in configuration.[/red]")
            raise typer.Exit(code=1)
        configs_to_run = filtered_configs
    else:
        configs_to_run = configs

    # Initialize LLM Client
    llm_client = LLMClient()

    # Async run runner helper
    async def run_pipeline():
        scraped_records = []
        for config in configs_to_run:
            console.print(f"[bold green]Starting scraping pipeline for {config.name}...[/bold green]")
            record = await run_for_university(config, llm_client)
            scraped_records.append(record)
            console.print(f"[green]Finished pipeline for {config.name}.[/green]")
        return scraped_records

    # Execute async pipeline
    try:
        new_records = asyncio.run(run_pipeline())
    except Exception as e:
        console.print(f"[red]Fatal pipeline execution error: {e}[/red]")
        raise typer.Exit(code=1)
    finally:
        # Ensure HTTP connection of the LLM client is closed
        async def close_llm():
            await llm_client.close()
        asyncio.run(close_llm())

    # output directories setup
    output_dir = "data/output"
    os.makedirs(output_dir, exist_ok=True)
    json_path = os.path.join(output_dir, "universities.json")
    csv_path = os.path.join(output_dir, "universities.csv")

    # Load existing JSON records to support incremental updating / upserting
    all_records_dict = {}
    if os.path.exists(json_path):
        try:
            with open(json_path, "r") as f:
                existing_data = json.load(f)
                for entry in existing_data:
                    try:
                        parsed = ScrapedRecord(**entry)
                        all_records_dict[parsed.university_name] = parsed
                    except Exception:
                        # Skip malformed existing records
                        pass
        except Exception as e:
            console.print(f"[yellow]Warning: Could not read existing JSON file: {e}. Starting fresh.[/yellow]")

    # Merge new records (overwriting existing ones with the same name)
    for record in new_records:
        all_records_dict[record.university_name] = record

    final_records = list(all_records_dict.values())

    # Write JSON array output
    try:
        with open(json_path, "w") as f:
            json.dump([r.model_dump(mode="json") for r in final_records], f, indent=2)
        console.print(f"[green]Scraped JSON records written to {json_path}[/green]")
    except Exception as e:
        console.print(f"[red]Error writing JSON file: {e}[/red]")

    # Generate/write flattened CSV using pandas
    csv_rows = []
    for record in final_records:
        university_name = record.university_name
        for field_name in record.data.__class__.model_fields:
            val = getattr(record.data, field_name)
            # Serialize field value to stringified JSON representation
            if isinstance(val, list):
                field_json = json.dumps([item.model_dump(mode="json") for item in val])
            elif hasattr(val, "model_dump"):
                field_json = val.model_dump_json()
            else:
                field_json = json.dumps(val)

            confidence = record.field_confidence.get(field_name, 0.0)
            
            # Serialize validation flags for this field
            field_flags = [flag.model_dump(mode="json") for flag in record.validation_flags if flag.field == field_name]
            flags_json = json.dumps(field_flags)

            csv_rows.append({
                "university_name": university_name,
                "field_name": field_name,
                "field_json": field_json,
                "confidence": confidence,
                "flags_json": flags_json,
            })

    try:
        df = pd.DataFrame(csv_rows)
        df.to_csv(csv_path, index=False)
        console.print(f"[green]Flattened CSV records written to {csv_path}[/green]")
    except Exception as e:
        console.print(f"[red]Error writing CSV file: {e}[/red]")


if __name__ == "__main__":
    app()
