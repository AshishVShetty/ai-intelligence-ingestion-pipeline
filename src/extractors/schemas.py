"""Data models and schemas for crawled intelligence entities."""

from pathlib import Path
import sys
from typing import List, Literal, Optional

# Ensure local venv site-packages is on sys.path if running with base python
_venv_site = Path(__file__).resolve().parent.parent.parent / "venv" / "Lib" / "site-packages"
if _venv_site.exists() and str(_venv_site) not in sys.path:
    sys.path.insert(0, str(_venv_site))

from pydantic import BaseModel, Field


class ResearchPaperSchema(BaseModel):
    """Schema for arXiv research paper intelligence records."""

    schemaVersion: str = "1.0"
    recordType: Literal["RESEARCH_PAPER"] = "RESEARCH_PAPER"
    title: str
    authors: List[str] = Field(default_factory=list)
    paper_url: str
    github_url: Optional[str] = None
    github_stars: Optional[int] = None
    published_date: str
    source_name: str = "arXiv"
    collectedAt: str


class StartupSchema(BaseModel):
    """Schema for AI startup intelligence records."""

    schemaVersion: str = "1.0"
    recordType: Literal["STARTUP"] = "STARTUP"
    company_name: str
    website: Optional[str] = None
    description: Optional[str] = None
    employee_count: Optional[int] = None
    source_name: str
    source_url: str
    collectedAt: str


class ProductSchema(BaseModel):
    """Schema for AI product and model intelligence records."""

    schemaVersion: str = "1.0"
    recordType: Literal["PRODUCT"] = "PRODUCT"
    product_name: str
    company_name: Optional[str] = None
    website: Optional[str] = None
    description: Optional[str] = None
    pricing_model: Optional[Literal["FREE", "FREEMIUM", "PAID", "ENTERPRISE"]] = None
    source_name: str
    source_url: str
    collectedAt: str


class NewsSchema(BaseModel):
    """Schema for AI news intelligence records."""

    schemaVersion: str = "1.0"
    recordType: Literal["NEWS"] = "NEWS"
    title: str
    source_name: str
    url: str
    published_date: str
    description: Optional[str] = None
    collectedAt: str


class JobSchema(BaseModel):
    """Schema for AI and tech job intelligence records."""

    schemaVersion: str = "1.0"
    recordType: Literal["JOB"] = "JOB"
    job_title: str
    company: str
    url: str
    published_date: str
    remote_status: str
    role_family: str
    source_name: str
    collectedAt: str


class ExtractedNewsSchema(BaseModel):
    """Schema for LLM-extracted structured intelligence from news articles."""

    schemaVersion: str = "1.0"
    recordType: Literal["EXTRACTED_NEWS"] = "EXTRACTED_NEWS"
    title: str
    summary: str
    companies_mentioned: List[str] = Field(default_factory=list)
    technologies_mentioned: List[str] = Field(default_factory=list)
    category: str
    url: str
    collectedAt: str


class ExtractedJobSchema(BaseModel):
    """Schema for LLM-extracted structured intelligence from job postings."""

    schemaVersion: str = "1.0"
    recordType: Literal["EXTRACTED_JOB"] = "EXTRACTED_JOB"
    job_title: str
    company: str
    required_skills: List[str] = Field(default_factory=list)
    role_family: str
    remote_status: str
    url: str
    collectedAt: str
