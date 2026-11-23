"""Configuration settings for AI Intelligence Ingestion Pipeline."""

from pathlib import Path
import sys
import os

# Ensure local venv site-packages is on sys.path if running with base python
_venv_site = Path(__file__).resolve().parent.parent / "venv" / "Lib" / "site-packages"
if _venv_site.exists() and str(_venv_site) not in sys.path:
    sys.path.insert(0, str(_venv_site))

from dotenv import load_dotenv

# Base paths
BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"
RAW_DATA_DIR = DATA_DIR / "raw"
PROCESSED_DATA_DIR = DATA_DIR / "processed"

# Automatically create data directories if they do not exist
RAW_DATA_DIR.mkdir(parents=True, exist_ok=True)
PROCESSED_DATA_DIR.mkdir(parents=True, exist_ok=True)

# Load environment variables from .env
load_dotenv(dotenv_path=BASE_DIR / ".env")

# GitHub API token (optional, increases rate limit from 60 to 5000 req/hr)
GITHUB_TOKEN = os.getenv("GITHUB_TOKEN", "").strip()

# LLM Provider API Keys
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "").strip()
GROQ_API_KEY = os.getenv("GROQ_API_KEY", "").strip()
DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY", "").strip()

# LLM Provider Configuration
GEMINI_API_BASE_URL = "https://generativelanguage.googleapis.com/v1beta/models"
GEMINI_MODEL = "gemini-3.1-flash-lite"

GROQ_API_URL = "https://api.groq.com/openai/v1/chat/completions"
GROQ_MODEL = "llama-3.3-70b-versatile"

DEEPSEEK_API_URL = "https://api.deepseek.com/chat/completions"
DEEPSEEK_MODEL = "deepseek-chat"

# LLM Safeguards & Limits
MAX_PAYLOAD_CHARS = 8000
LLM_TIMEOUT_SECONDS = 30
LLM_MAX_RETRIES = 2

# General crawler settings
REQUEST_TIMEOUT_SECONDS = 30
MAX_RETRIES = 3

# ==============================================================================
# arXiv Crawler Configuration
# ==============================================================================
ARXIV_API_BASE_URL = "https://export.arxiv.org/api/query"
ARXIV_DEFAULT_QUERY = "cat:cs.AI OR cat:cs.LG OR cat:cs.CL OR cat:cs.CV OR cat:stat.ML"
DEFAULT_TARGET_PAPERS = 1000
DEFAULT_PAGE_SIZE = 100
ARXIV_REQUEST_DELAY = 3.5  # seconds between arXiv requests to respect rate limits

# ==============================================================================
# Startup Crawler Configuration
# ==============================================================================
YC_STARTUP_API_URL = "https://yc-oss.github.io/api/tags/artificial-intelligence.json"
YC_STARTUP_BACKUP_URL = "https://yc-oss.github.io/api/tags/ai.json"
YC_GENAI_URL = "https://yc-oss.github.io/api/tags/generative-ai.json"
YC_ML_URL = "https://yc-oss.github.io/api/tags/machine-learning.json"
DEFAULT_TARGET_STARTUPS = 1000

# ==============================================================================
# Product Crawler Configuration
# ==============================================================================
OPENROUTER_MODELS_API_URL = "https://openrouter.ai/api/v1/models"
HUGGINGFACE_MODELS_API_URL = "https://huggingface.co/api/models?sort=downloads&direction=-1&limit=600"
FREE_AI_APIS_DIRECTORY_URL = "https://raw.githubusercontent.com/OuterSpacee/free-ai-apis/main/README.md"
FREE_AI_TOOLS_DIRECTORY_URL = "https://raw.githubusercontent.com/ShaikhWarsi/free-ai-tools/main/README.md"
DEFAULT_TARGET_PRODUCTS = 1000

# ==============================================================================
# News Crawler Configuration (5 Legitimate Sources)
# ==============================================================================
DEFAULT_NEWS_FEEDS = [
    {
        "name": "Google News AI",
        "url": "https://news.google.com/rss/search?q=Artificial+Intelligence&hl=en-US&gl=US&ceid=US:en",
    },
    {
        "name": "The Verge AI",
        "url": "https://www.theverge.com/rss/ai-artificial-intelligence/index.xml",
    },
    {
        "name": "Wired AI",
        "url": "https://www.wired.com/feed/tag/ai/latest/rss",
    },
    {
        "name": "BBC Technology",
        "url": "https://feeds.bbci.co.uk/news/technology/rss.xml",
    },
    {
        "name": "Ars Technica",
        "url": "https://feeds.arstechnica.com/arstechnica/technology-lab",
    },
]

# ==============================================================================
# Jobs Crawler Configuration (5 Legitimate Sources)
# ==============================================================================
DEFAULT_JOB_SOURCES = [
    {
        "name": "Jobicy",
        "type": "api",
        "url": "https://jobicy.com/api/v2/remote-jobs",
    },
    {
        "name": "Arbeitnow",
        "type": "api",
        "url": "https://www.arbeitnow.com/api/job-board-api",
    },
    {
        "name": "Himalayas",
        "type": "api",
        "url": "https://himalayas.app/jobs/api",
    },
    {
        "name": "Hacker News Jobs",
        "type": "hn",
        "url": "https://hacker-news.firebaseio.com/v0/jobstories.json",
    },
    {
        "name": "Remotive",
        "type": "api",
        "url": "https://remotive.com/api/remote-jobs?search=ai",
    },
]
