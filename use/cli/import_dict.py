"""
import_dict — bulk import dict entries from CSV.

Usage::

    uv run python -m use.cli.import_dict --file data/dict_seed.csv --domain general

CSV format (header row required):
    canonical_id,term,entry_type,aliases,domain,definition

The ``aliases`` column is pipe-separated: ``alias1|alias2|alias3``.
All imported entries are set to ``source='imported'``, ``confidence=1.0``,
``review_status='approved'``.
"""
from __future__ import annotations

import asyncio
import csv
import json
import uuid
from pathlib import Path
from typing import Annotated

import typer
from sqlalchemy import text

from use.db.postgres import AsyncSessionLocal

app = typer.Typer(add_completion=False)


@app.command()
def run(
    file: Annotated[Path, typer.Option("--file", "-f", help="Path to CSV file")] = Path(
        "data/dict_seed.csv"
    ),
    domain: Annotated[
        str | None, typer.Option("--domain", "-d", help="Override domain for all rows")
    ] = None,
) -> None:
    """Bulk-import dict entries from a CSV file."""
    asyncio.run(_import(file, domain))


async def _import(file: Path, domain_override: str | None) -> None:
    if not file.exists():
        typer.echo(f"ERROR: file not found: {file}", err=True)
        raise typer.Exit(1)

    imported = 0
    skipped = 0

    async with AsyncSessionLocal() as db:
        with file.open(newline="", encoding="utf-8") as fh:
            reader = csv.DictReader(fh)
            required = {"canonical_id", "term", "entry_type"}
            if not required.issubset(set(reader.fieldnames or [])):
                typer.echo(
                    f"ERROR: CSV must have columns: {', '.join(sorted(required))}",
                    err=True,
                )
                raise typer.Exit(1)

            for row in reader:
                canonical_id = row["canonical_id"].strip()
                term = row["term"].strip()
                entry_type = row["entry_type"].strip()

                # Parse aliases (pipe-separated)
                aliases_raw = row.get("aliases", "").strip()
                aliases = (
                    [a.strip() for a in aliases_raw.split("|") if a.strip()]
                    if aliases_raw
                    else []
                )

                row_domain = domain_override or row.get("domain", "").strip() or None
                definition = row.get("definition", "").strip() or None

                # ON CONFLICT DO NOTHING based on canonical_id uniqueness
                result = await db.execute(
                    text("""
                        INSERT INTO dict_entries
                            (id, canonical_id, term, entry_type, aliases, domain, definition,
                             source, confidence, review_status, version, created_at, updated_at)
                        VALUES
                            (:id, :canonical_id, :term, :entry_type, :aliases, :domain, :definition,
                             'imported', 1.0, 'approved', 1, NOW(), NOW())
                        ON CONFLICT (canonical_id) DO NOTHING
                    """),
                    {
                        "id": str(uuid.uuid4()),
                        "canonical_id": canonical_id,
                        "term": term,
                        "entry_type": entry_type,
                        "aliases": json.dumps(aliases),
                        "domain": row_domain,
                        "definition": definition,
                    },
                )
                # rowcount=0 → conflict (skipped), rowcount=1 → inserted
                if result.rowcount == 0:
                    skipped += 1
                else:
                    imported += 1

        await db.commit()

    typer.echo(f"Imported {imported} entries, skipped {skipped} duplicates.")


def main() -> None:
    app()


if __name__ == "__main__":
    main()
