#!/usr/bin/env python3
"""Check enrichment run errors from the database."""

import sys
import os

# Add backend to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'backend'))

from app.database import SessionLocal
from app.models.enrichment_run import EnrichmentRun, EnrichmentRunItem
from sqlalchemy import desc

db = SessionLocal()

try:
    # Get the most recent run
    recent_run = db.query(EnrichmentRun).order_by(desc(EnrichmentRun.created_at)).first()

    if not recent_run:
        print("No enrichment runs found")
        sys.exit(0)

    print(f"Most Recent Run: {recent_run.id}")
    print(f"Status: {recent_run.status}")
    print(f"Total Items: {recent_run.total_items}")
    print(f"Completed: {recent_run.completed_items}")
    print(f"Failed: {recent_run.failed_items}")
    print(f"Run Error: {recent_run.error_message}")
    print("\n" + "="*80 + "\n")

    # Get failed items
    failed_items = db.query(EnrichmentRunItem).filter(
        EnrichmentRunItem.run_id == recent_run.id,
        EnrichmentRunItem.status == 'failed'
    ).limit(5).all()

    print(f"Failed Items (showing first 5):\n")
    for i, item in enumerate(failed_items, 1):
        print(f"{i}. Job ID: {item.job_id}")
        print(f"   Error: {item.error_message[:500] if item.error_message else 'No error message'}")
        print()

finally:
    db.close()
