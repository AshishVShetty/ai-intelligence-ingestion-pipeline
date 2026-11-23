"""Generate the final Excel workbook deliverable containing all six pipeline tabs."""

import json
from pathlib import Path
import sys

# Ensure local venv is accessible
_venv_site = Path(__file__).resolve().parent.parent / "venv" / "Lib" / "site-packages"
if _venv_site.exists() and str(_venv_site) not in sys.path:
    sys.path.insert(0, str(_venv_site))

import openpyxl
from openpyxl.cell.cell import ILLEGAL_CHARACTERS_RE
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter
import pandas as pd

BASE_DIR = Path(__file__).resolve().parent.parent
PROCESSED_DIR = BASE_DIR / "data" / "processed"
DELIVERABLES_DIR = BASE_DIR / "deliverables"
DELIVERABLES_DIR.mkdir(parents=True, exist_ok=True)
OUTPUT_FILE = DELIVERABLES_DIR / "AI_Intelligence_Pipeline_Data.xlsx"


def sanitize_val(val):
    """Sanitize string values by stripping Excel illegal XML control characters."""
    if isinstance(val, str):
        return ILLEGAL_CHARACTERS_RE.sub("", val)
    if pd.isna(val):
        return None
    return val


def build_workbook():
    wb = openpyxl.Workbook()
    # Remove default sheet
    default_sheet = wb.active
    wb.remove(default_sheet)

    # Styling definitions
    header_fill = PatternFill(start_color="1E3A8A", end_color="1E3A8A", fill_type="solid")  # Dark Navy
    header_font = Font(name="Calibri", size=11, bold=True, color="FFFFFF")
    data_font = Font(name="Calibri", size=10)
    zebra_fill = PatternFill(start_color="F8FAFC", end_color="F8FAFC", fill_type="solid")  # Slate 50
    thin_border = Border(
        left=Side(style="thin", color="E2E8F0"),
        right=Side(style="thin", color="E2E8F0"),
        top=Side(style="thin", color="E2E8F0"),
        bottom=Side(style="thin", color="E2E8F0"),
    )

    # 1. Load Entity Mapping Log for canonical ID enrichment
    mapping_df = pd.read_csv(PROCESSED_DIR / "entity_mapping_log.csv")
    startup_map = {}
    product_map = {}
    paper_map = {}

    for _, row in mapping_df.iterrows():
        key = (str(row["original_entity_name"]).strip(), str(row["source_url"]).strip())
        cid = row["canonical_entity_id"]
        cname = row["canonical_entity_name"]
        startup_map[key] = (cid, cname)
        product_map[key] = (cid, cname)
        paper_map[key] = (cid, cname)

    # Define sheet specifications
    sheets_config = [
        {
            "title": "Startups",
            "csv_path": PROCESSED_DIR / "startups.csv",
            "mapping_key": lambda r: (str(r["company_name"]).strip(), str(r["source_url"]).strip()),
            "mapping_dict": startup_map,
            "id_col_name": "canonical_entity_id",
            "name_col_name": "canonical_company_name",
        },
        {
            "title": "Products",
            "csv_path": PROCESSED_DIR / "products.csv",
            "mapping_key": lambda r: (str(r["product_name"]).strip(), str(r["source_url"]).strip()),
            "mapping_dict": product_map,
            "id_col_name": "canonical_entity_id",
            "name_col_name": "canonical_product_name",
        },
        {
            "title": "Research Papers",
            "csv_path": PROCESSED_DIR / "research_papers.csv",
            "mapping_key": lambda r: (str(r["title"]).strip(), str(r["paper_url"]).strip()),
            "mapping_dict": paper_map,
            "id_col_name": "canonical_entity_id",
            "name_col_name": "canonical_paper_title",
        },
        {
            "title": "Jobs",
            "csv_path": PROCESSED_DIR / "jobs.csv",
            "mapping_key": None,
            "mapping_dict": None,
            "id_col_name": None,
            "name_col_name": None,
        },
        {
            "title": "News",
            "csv_path": PROCESSED_DIR / "news.csv",
            "mapping_key": None,
            "mapping_dict": None,
            "id_col_name": None,
            "name_col_name": None,
        },
        {
            "title": "Entity Mapping Log",
            "csv_path": PROCESSED_DIR / "entity_mapping_log.csv",
            "mapping_key": None,
            "mapping_dict": None,
            "id_col_name": None,
            "name_col_name": None,
        },
    ]

    for cfg in sheets_config:
        title = cfg["title"]
        df = pd.read_csv(cfg["csv_path"])
        ws = wb.create_sheet(title=title)

        # Enrich with canonical IDs if configured
        if cfg["mapping_key"] and cfg["mapping_dict"]:
            canonical_ids = []
            canonical_names = []
            for _, row in df.iterrows():
                k = cfg["mapping_key"](row)
                res = cfg["mapping_dict"].get(k, (None, None))
                canonical_ids.append(res[0])
                canonical_names.append(res[1])
            # Insert canonical columns near front
            df.insert(0, cfg["id_col_name"], canonical_ids)
            df.insert(1, cfg["name_col_name"], canonical_names)

        # Write Header
        headers = list(df.columns)
        ws.append(headers)
        for col_idx in range(1, len(headers) + 1):
            cell = ws.cell(row=1, column=col_idx)
            cell.fill = header_fill
            cell.font = header_font
            cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=False)
            cell.border = thin_border
        ws.row_dimensions[1].height = 26

        # Write Data
        for row_idx, row_values in enumerate(df.itertuples(index=False), start=2):
            sanitized_row = [sanitize_val(v) for v in row_values]
            ws.append(sanitized_row)
            is_zebra = (row_idx % 2 == 1)
            for col_idx in range(1, len(headers) + 1):
                cell = ws.cell(row=row_idx, column=col_idx)
                cell.font = data_font
                cell.border = thin_border
                if is_zebra:
                    cell.fill = zebra_fill
                val = cell.value
                # Alignment logic
                if isinstance(val, (int, float)):
                    cell.alignment = Alignment(horizontal="right", vertical="top")
                elif str(val).startswith("http"):
                    cell.alignment = Alignment(horizontal="left", vertical="top")
                else:
                    cell.alignment = Alignment(horizontal="left", vertical="top", wrap_text=True)

        # Enable Auto-Filter on header row
        ws.auto_filter.ref = ws.dimensions

        # Freeze Header Row
        ws.freeze_panes = "A2"

        # Auto-fit Column Widths with bounds
        for col_idx, col_name in enumerate(headers, start=1):
            col_letter = get_column_letter(col_idx)
            max_len = len(str(col_name))
            sample_rows = df[col_name].dropna().head(100)
            for val in sample_rows:
                s_len = len(str(val))
                if s_len > max_len:
                    max_len = s_len
            # Clamp width between 14 and 45 (or 60 for URLs/descriptions)
            if "description" in str(col_name).lower() or "title" in str(col_name).lower():
                width = min(max(max_len + 3, 20), 55)
            elif "url" in str(col_name).lower() or "website" in str(col_name).lower():
                width = min(max(max_len + 3, 20), 45)
            else:
                width = min(max(max_len + 3, 14), 35)
            ws.column_dimensions[col_letter].width = width

        print(f"Sheet '{title}' built: {len(df)} rows, {len(headers)} columns.")

    wb.save(OUTPUT_FILE)
    print(f"\nSuccessfully generated deliverable workbook at: {OUTPUT_FILE}")


if __name__ == "__main__":
    build_workbook()
