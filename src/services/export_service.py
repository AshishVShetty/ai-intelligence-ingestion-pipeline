"""Centralized Export Service.

Handles standardized export of intelligence records across JSON and CSV formats:
- Preserves traceable provenance and source URLs.
- Safely handles nested lists and dictionaries with flattening.
- Normalizes nulls and timestamps across schemas.
- Writes to consistent RAW_DATA_DIR and PROCESSED_DATA_DIR locations.
"""

from datetime import date, datetime
import json
import os
from pathlib import Path
import sys
from typing import Any, Dict, List, Optional, Tuple, Union

# Ensure local venv site-packages is on sys.path if running with base python
_venv_site = Path(__file__).resolve().parent.parent.parent / "venv" / "Lib" / "site-packages"
if _venv_site.exists() and str(_venv_site) not in sys.path:
    sys.path.insert(0, str(_venv_site))

import pandas as pd

from src.config import PROCESSED_DATA_DIR, RAW_DATA_DIR
from src.utils.logger import get_logger

logger = get_logger("export_service")


def json_default_serializer(obj: Any) -> Any:
    """JSON serialization helper for dates, datetimes, and complex objects."""
    if isinstance(obj, (datetime, date)):
        return obj.isoformat()
    if hasattr(obj, "model_dump"):
        return obj.model_dump()
    if hasattr(obj, "dict"):
        return obj.dict()
    return str(obj)


def flatten_record_for_csv(record: Dict[str, Any]) -> Dict[str, Any]:
    """Flatten nested structures (lists, dicts) for consistent CSV tabular representation."""
    flat: Dict[str, Any] = {}
    for key, val in record.items():
        if val is None:
            flat[key] = ""
        elif isinstance(val, (datetime, date)):
            flat[key] = val.isoformat()
        elif isinstance(val, list):
            # If list of primitive strings/numbers, join with semicolon
            if all(isinstance(x, (str, int, float, bool)) for x in val):
                flat[key] = "; ".join(str(x) for x in val)
            else:
                flat[key] = json.dumps(val, default=json_default_serializer, ensure_ascii=False)
        elif isinstance(val, dict):
            flat[key] = json.dumps(val, default=json_default_serializer, ensure_ascii=False)
        else:
            flat[key] = val
    return flat


class ExportService:
    """Centralized service for writing pipeline intelligence artifacts."""

    def __init__(
        self,
        raw_dir: Optional[Path] = None,
        processed_dir: Optional[Path] = None,
    ):
        self.raw_dir = raw_dir or RAW_DATA_DIR
        self.processed_dir = processed_dir or PROCESSED_DATA_DIR

        self.raw_dir.mkdir(parents=True, exist_ok=True)
        self.processed_dir.mkdir(parents=True, exist_ok=True)

    def export_json(
        self,
        records: List[Dict[str, Any]],
        output_path: Union[str, Path],
        indent: int = 2,
    ) -> Path:
        """Export records as a clean UTF-8 JSON file."""
        target_path = Path(output_path)
        target_path.parent.mkdir(parents=True, exist_ok=True)

        try:
            with open(target_path, "w", encoding="utf-8") as f:
                json.dump(records, f, indent=indent, default=json_default_serializer, ensure_ascii=False)
            logger.info("Exported %d records to JSON: %s", len(records), target_path)
            return target_path
        except Exception as exc:
            logger.error("Failed to export JSON to %s: %s", target_path, exc)
            raise exc

    def export_csv(
        self,
        records: List[Dict[str, Any]],
        output_path: Union[str, Path],
    ) -> Path:
        """Export records as a flattened UTF-8 CSV file with consistent columns."""
        target_path = Path(output_path)
        target_path.parent.mkdir(parents=True, exist_ok=True)

        if not records:
            # Create empty CSV with headers if empty
            df = pd.DataFrame()
            df.to_csv(target_path, index=False, encoding="utf-8")
            logger.warning("Exported empty CSV to %s", target_path)
            return target_path

        try:
            # Flatten records for consistent tabular representation
            flattened = [flatten_record_for_csv(r) for r in records]

            # Preserve predictable column ordering across all records
            all_keys: Dict[str, None] = {}
            for r in flattened:
                for k in r.keys():
                    all_keys[k] = None
            columns = list(all_keys.keys())

            df = pd.DataFrame(flattened, columns=columns)
            df.to_csv(target_path, index=False, encoding="utf-8")
            logger.info("Exported %d records to CSV: %s", len(df), target_path)
            return target_path
        except Exception as exc:
            logger.error("Failed to export CSV to %s: %s", target_path, exc)
            raise exc

    def export_dataset(
        self,
        records: List[Dict[str, Any]],
        dataset_name: str,
        export_raw: bool = True,
        export_processed: bool = True,
    ) -> Tuple[Optional[Path], Optional[Path]]:
        """Convenience method to export both data/raw/<dataset_name>.json and data/processed/<dataset_name>.csv."""
        raw_path: Optional[Path] = None
        csv_path: Optional[Path] = None

        if export_raw:
            raw_path = self.export_json(records, self.raw_dir / f"{dataset_name}.json")

        if export_processed:
            csv_path = self.export_csv(records, self.processed_dir / f"{dataset_name}.csv")

        return raw_path, csv_path


# Global singleton instance
export_service = ExportService()
