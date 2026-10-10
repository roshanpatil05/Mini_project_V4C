from __future__ import annotations

import argparse
import sys
from pathlib import Path

# Ensure the root project directory is in the Python path
project_root = Path(__file__).resolve().parent.parent
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

from src.ETL.loader import DataWarehouseLoader


DEFAULT_DATA_DIR = Path(__file__).resolve().parent / "data"


def main() -> None:
    parser = argparse.ArgumentParser(description="Load employee and review CSVs into MySQL OLTP and warehouse schemas")
    parser.add_argument("--employees", type=Path, default=DEFAULT_DATA_DIR / "synthetic_employees.csv")
    parser.add_argument("--history", type=Path, default=DEFAULT_DATA_DIR / "employee_scd2_history.csv")
    parser.add_argument("--reviews", type=Path, default=DEFAULT_DATA_DIR / "synthetic_performance_reviews.csv")
    parser.add_argument("--projects", type=Path, default=DEFAULT_DATA_DIR / "synthetic_projects.csv")
    parser.add_argument("--assignments", type=Path, default=DEFAULT_DATA_DIR / "synthetic_project_assignments.csv")
    args = parser.parse_args()
    loader = DataWarehouseLoader()
    try:
        loader.load_synthesized_data(args.employees, args.history, args.reviews, args.projects, args.assignments)
        print("Employee versions, projects, assignments and performance review facts loaded successfully.")
    finally:
        loader.close()


if __name__ == "__main__":
    main()
