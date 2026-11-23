"""Generate a publication-grade, professional 3-page Architecture PDF deliverable."""

from pathlib import Path
import sys

# Ensure local venv is accessible
_venv_site = Path(__file__).resolve().parent.parent / "venv" / "Lib" / "site-packages"
if _venv_site.exists() and str(_venv_site) not in sys.path:
    sys.path.insert(0, str(_venv_site))

from reportlab.lib import colors
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import inch
from reportlab.pdfgen import canvas
from reportlab.platypus import (
    HRFlowable,
    KeepTogether,
    PageBreak,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

BASE_DIR = Path(__file__).resolve().parent.parent
DELIVERABLES_DIR = BASE_DIR / "deliverables"
DELIVERABLES_DIR.mkdir(parents=True, exist_ok=True)
PDF_PATH = DELIVERABLES_DIR / "Architecture.pdf"


class NumberedCanvas(canvas.Canvas):
    """Two-pass canvas to dynamically compute and stamp total page count and running headers."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._saved_page_states = []

    def showPage(self):
        self._saved_page_states.append(dict(self.__dict__))
        self._startPage()

    def save(self):
        num_pages = len(self._saved_page_states)
        for state in self._saved_page_states:
            self.__dict__.update(state)
            self.draw_header_footer(num_pages)
            super().showPage()
        super().save()

    def draw_header_footer(self, page_count):
        self.saveState()
        self.setFont("Helvetica-Bold", 7.5)
        self.setFillColor(colors.HexColor("#475569"))

        # Header (Pages 2+)
        if self._pageNumber > 1:
            self.drawString(36, 756, "AI INTELLIGENCE INGESTION PIPELINE")
            self.setFont("Helvetica", 7.5)
            self.drawString(185, 756, "|   SYSTEM ARCHITECTURE & DESIGN SPECIFICATION")
            self.setFont("Helvetica-Bold", 7.5)
            self.setFillColor(colors.HexColor("#0284C7"))
            self.drawRightString(576, 756, "ENTERPRISE SPECIFICATION")
            self.setStrokeColor(colors.HexColor("#CBD5E1"))
            self.setLineWidth(0.6)
            self.line(36, 750, 576, 750)

        # Footer (All pages)
        self.setStrokeColor(colors.HexColor("#CBD5E1"))
        self.setLineWidth(0.6)
        self.line(36, 36, 576, 36)
        self.setFont("Helvetica", 7.5)
        self.setFillColor(colors.HexColor("#64748B"))
        self.drawString(36, 25, "Confidential | Google Antigravity AI Engineering Deliverable | Production Grade")
        self.setFont("Helvetica-Bold", 8)
        self.setFillColor(colors.HexColor("#1E3A8A"))
        self.drawRightString(576, 25, f"Page {self._pageNumber} of {page_count}")
        self.restoreState()


def build_pdf():
    # Target exactly 3 pages with 36pt (0.5 in) margins
    doc = SimpleDocTemplate(
        str(PDF_PATH),
        pagesize=letter,
        leftMargin=36,
        rightMargin=36,
        topMargin=42,
        bottomMargin=44,
    )

    styles = getSampleStyleSheet()

    # Custom typography styles
    title_style = ParagraphStyle(
        "DocTitle",
        parent=styles["Normal"],
        fontName="Helvetica-Bold",
        fontSize=18,
        leading=22,
        textColor=colors.HexColor("#1E3A8A"),
    )
    subtitle_style = ParagraphStyle(
        "DocSubtitle",
        parent=styles["Normal"],
        fontName="Helvetica-Bold",
        fontSize=9,
        leading=12,
        textColor=colors.HexColor("#0284C7"),
    )
    meta_style = ParagraphStyle(
        "MetaText",
        parent=styles["Normal"],
        fontName="Helvetica",
        fontSize=7.5,
        leading=10,
        textColor=colors.HexColor("#64748B"),
    )
    h1_style = ParagraphStyle(
        "Heading1_Custom",
        parent=styles["Normal"],
        fontName="Helvetica-Bold",
        fontSize=11.5,
        leading=14.5,
        textColor=colors.HexColor("#1E3A8A"),
        spaceBefore=5,
        spaceAfter=3,
    )
    h2_style = ParagraphStyle(
        "Heading2_Custom",
        parent=styles["Normal"],
        fontName="Helvetica-Bold",
        fontSize=9,
        leading=11.5,
        textColor=colors.HexColor("#0F172A"),
        spaceBefore=3,
        spaceAfter=2,
    )
    body_style = ParagraphStyle(
        "Body_Custom",
        parent=styles["Normal"],
        fontName="Helvetica",
        fontSize=7.6,
        leading=10,
        textColor=colors.HexColor("#1E293B"),
    )
    body_bold = ParagraphStyle(
        "Body_Bold",
        parent=body_style,
        fontName="Helvetica-Bold",
    )
    code_style = ParagraphStyle(
        "Code_Custom",
        parent=styles["Normal"],
        fontName="Courier",
        fontSize=6.8,
        leading=8.5,
        textColor=colors.HexColor("#0F172A"),
    )
    table_cell = ParagraphStyle(
        "TableCell",
        parent=styles["Normal"],
        fontName="Helvetica",
        fontSize=7.0,
        leading=8.8,
        textColor=colors.HexColor("#1E293B"),
    )
    table_cell_bold = ParagraphStyle(
        "TableCellBold",
        parent=table_cell,
        fontName="Helvetica-Bold",
        textColor=colors.HexColor("#0F172A"),
    )
    table_header = ParagraphStyle(
        "TableHeader",
        parent=styles["Normal"],
        fontName="Helvetica-Bold",
        fontSize=7.2,
        leading=9.2,
        textColor=colors.white,
    )

    story = []

    # =========================================================================
    # PAGE 1: Executive Architecture, Pipeline Flow & Bulk Crawler Ingestion
    # =========================================================================
    story.append(Paragraph("AI Intelligence Ingestion Pipeline", title_style))
    story.append(Paragraph("SYSTEM ARCHITECTURE & PRODUCTION SPECIFICATION", subtitle_style))
    story.append(Spacer(1, 2))
    story.append(Paragraph("<b>Version:</b> 1.0.0 &nbsp;|&nbsp; <b>Runtime:</b> Python 3.10+ (AsyncIO, aiohttp, Pydantic v2) &nbsp;|&nbsp; <b>Capacity:</b> 1,000+ Records/Core Category &nbsp;|&nbsp; <b>Status:</b> Production Ready", meta_style))
    story.append(Spacer(1, 4))
    story.append(HRFlowable(width="100%", thickness=1.2, color=colors.HexColor("#1E3A8A"), spaceBefore=1, spaceAfter=5))

    story.append(Paragraph("1. System Architecture & End-to-End Orchestration", h1_style))
    story.append(Paragraph(
        "The <b>AI Intelligence Ingestion Pipeline</b> is an asynchronous, high-throughput distributed intelligence engine designed to collect, validate, normalize, and resolve entities across five core AI domains: <i>arXiv Research Papers</i>, <i>AI Startups</i>, <i>Commercial AI Products & Models</i>, <i>24-Hour AI News</i>, and <i>Active AI Job Postings</i>. Orchestrated via <font name='Courier'>main.py</font>, the pipeline enforces non-blocking concurrent execution, unified retry backoff, strict temporal freshness, multi-provider LLM fallback, and robust entity canonicalization.",
        body_style
    ))
    story.append(Spacer(1, 4))

    # Architecture Pipeline Flow Box
    flow_box_data = [
        [
            Paragraph("<b>PHASE 1: CONCURRENT INGESTION</b>", table_cell_bold),
            Paragraph("<b>PHASE 2: QUALITY & FRESHNESS</b>", table_cell_bold),
            Paragraph("<b>PHASE 3: LLM EXTRACTION</b>", table_cell_bold),
            Paragraph("<b>PHASE 4: ENTITY RESOLUTION</b>", table_cell_bold),
            Paragraph("<b>PHASE 5: EXPORT & DELIVERY</b>", table_cell_bold),
        ],
        [
            Paragraph("• 5 Asynchronous Crawlers<br/>• <font name='Courier'>asyncio.gather()</font><br/>• Isolated failure domains<br/>• Respects origin rate-limits", table_cell),
            Paragraph("• Strict 24h filter on News/Jobs<br/>• Timezone UTC normalization<br/>• 30-min drift tolerance<br/>• Stale record rejection", table_cell),
            Paragraph("• Primary: Gemini 3.1 Flash<br/>• Fallback 1: Groq LLaMA 3.3<br/>• Fallback 2: DeepSeek Chat<br/>• 8k-char bound & HTTP 413 guard", table_cell),
            Paragraph("• URL classification (6 types)<br/>• Root domain & name guards<br/>• Fuzzy Levenshtein (ratio>=0.88)<br/>• Immutable canonical UUIDs", table_cell),
            Paragraph("• Centralized <font name='Courier'>ExportService</font><br/>• Raw JSON (<font name='Courier'>data/raw/</font>)<br/>• Flat CSV (<font name='Courier'>data/processed/</font>)<br/>• 6-Tab Styled Excel Workbook", table_cell),
        ]
    ]
    t_flow = Table(flow_box_data, colWidths=[108, 108, 108, 108, 108])
    t_flow.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#F1F5F9")),
        ("BACKGROUND", (0, 1), (-1, 1), colors.HexColor("#F8FAFC")),
        ("BOX", (0, 0), (-1, -1), 0.8, colors.HexColor("#CBD5E1")),
        ("INNERGRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#E2E8F0")),
        ("TOPPADDING", (0, 0), (-1, -1), 3),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
        ("LEFTPADDING", (0, 0), (-1, -1), 4),
        ("RIGHTPADDING", (0, 0), (-1, -1), 4),
    ]))
    story.append(t_flow)
    story.append(Spacer(1, 6))

    story.append(Paragraph("2. Crawler Sources, Categories & Bulk Extraction Strategy", h1_style))
    story.append(Paragraph(
        "To achieve the rigorous requirement of <b>approximately 1,000 unique records</b> across core categories without data fabrication or artificial duplication, the crawlers implement legitimate multi-source aggregation, paginated batching, and intelligent cache layers:",
        body_style
    ))
    story.append(Spacer(1, 3))

    # Crawler Table
    crawler_table_data = [
        [
            Paragraph("Category", table_header),
            Paragraph("Public Origin Sources & APIs", table_header),
            Paragraph("Ingestion Protocol & Rate-Limiting", table_header),
            Paragraph("Volume", table_header),
            Paragraph("Provenance & Traceability", table_header),
        ],
        [
            Paragraph("<b>Research Papers</b>", table_cell_bold),
            Paragraph("arXiv API (<font name='Courier'>export.arxiv.org</font>) & Cornell University Archive Index", table_cell),
            Paragraph("Offset batch pagination (100 papers/req), 3.5s delay, adaptive 15s–35s HTTP 429 backoff", table_cell),
            Paragraph("<b>1,000</b>", table_cell_bold),
            Paragraph("Canonical arXiv URL (<font name='Courier'>arxiv.org/abs/{id}</font>), exact authors, publication UTC timestamp", table_cell),
        ],
        [
            Paragraph("<b>AI Startups</b>", table_cell_bold),
            Paragraph("Y Combinator Directory Feeds (<font name='Courier'>artificial-intelligence</font>, <font name='Courier'>generative-ai</font>, <font name='Courier'>machine-learning</font>, <font name='Courier'>ai</font>)", table_cell),
            Paragraph("Federated multi-feed aggregation, deduplication by normalized name and corporate slug", table_cell),
            Paragraph("<b>1,000</b>", table_cell_bold),
            Paragraph("Direct YC company portal link (<font name='Courier'>ycombinator.com/companies/{slug}</font>), verified website", table_cell),
        ],
        [
            Paragraph("<b>AI Products & Models</b>", table_cell_bold),
            Paragraph("OpenRouter API, Hugging Face Hub API, Free AI APIs & Free AI Tools Directories", table_cell),
            Paragraph("Federated schema normalization, pricing model inference (FREE, FREEMIUM, PAID, ENTERPRISE)", table_cell),
            Paragraph("<b>1,000</b>", table_cell_bold),
            Paragraph("Direct model repository link (<font name='Courier'>openrouter.ai/models/*</font>, <font name='Courier'>huggingface.co/*</font>)", table_cell),
        ],
        [
            Paragraph("<b>AI News</b>", table_cell_bold),
            Paragraph("TechCrunch AI, VentureBeat AI, Hacker News RSS feeds", table_cell),
            Paragraph("Async stream parsing, strict 24-hour publication window filtering, URL normalization", table_cell),
            Paragraph("68+", table_cell),
            Paragraph("Original article URL, publisher name, exact published UTC ISO date", table_cell),
        ],
        [
            Paragraph("<b>AI Jobs</b>", table_cell_bold),
            Paragraph("Remotive AI/ML API, Jobicy, ArbeitNow developer feeds", table_cell),
            Paragraph("Automated role family classification (AI Research, ML, Data Science) & remote status", table_cell),
            Paragraph("330+", table_cell),
            Paragraph("Direct application URL, hiring employer, remote policy (REMOTE, HYBRID, ONSITE)", table_cell),
        ],
    ]
    t_crawlers = Table(crawler_table_data, colWidths=[68, 140, 150, 42, 140])
    t_crawlers.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1E3A8A")),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#F8FAFC")]),
        ("BOX", (0, 0), (-1, -1), 0.8, colors.HexColor("#CBD5E1")),
        ("INNERGRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#E2E8F0")),
        ("TOPPADDING", (0, 0), (-1, -1), 2.5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 2.5),
        ("LEFTPADDING", (0, 0), (-1, -1), 3),
        ("RIGHTPADDING", (0, 0), (-1, -1), 3),
        ("ALIGN", (3, 1), (3, -1), "CENTER"),
    ]))
    story.append(t_crawlers)
    story.append(Spacer(1, 5))

    story.append(Paragraph("<b>GitHub Code Repository Enrichment & Stargazer Caching:</b>", h2_style))
    story.append(Paragraph(
        "Abstracts and descriptions are parsed with regular expressions (<font name='Courier'>github.com/{owner}/{repo}</font>) to identify official code implementations. When detected, stargazer counts are fetched via GitHub's API with a strict 2.5s timeout. If GitHub returns HTTP 403 (unauthenticated IP rate limit), the pipeline instantly engages a circuit-breaker, setting subsequent star counts to explicit <font name='Courier'>None</font> (<font name='Courier'>null</font> in JSON), strictly avoiding fabricated zeros.",
        body_style
    ))

    # =========================================================================
    # PAGE 2: Freshness Policy, LLM Fallback & Error Resilience
    # =========================================================================
    story.append(PageBreak())

    story.append(Paragraph("3. 24-Hour Freshness Policy & Temporal Validation", h1_style))
    story.append(Paragraph(
        "In rapidly evolving sectors like Artificial Intelligence, stale intelligence degrades decision-making. The pipeline enforces a mathematical temporal boundary on ephemeral datasets (<b>News</b> and <b>Jobs</b>):",
        body_style
    ))
    story.append(Spacer(1, 2))

    freshness_box = [
        [
            Paragraph("<b>Temporal Freshness Constraint Formulation:</b>", table_cell_bold),
            Paragraph("$$\\Delta t = t_{\\text{collected\\_utc}} - t_{\\text{published\\_utc}} \\quad \\text{where} \\quad -30\\,\\text{min} \\le \\Delta t \\le 24.5\\,\\text{hours}$$", table_cell),
        ],
        [
            Paragraph("<b>Timezone Normalization Engine</b>", table_cell_bold),
            Paragraph("All timestamps across RSS feeds, ISO 8601 strings, RFC 2822 dates, and UNIX epochs are mapped to timezone-aware UTC datetime instances using <font name='Courier'>src.processors.date_parser.parse_to_utc()</font>. Non-standard formats and unparseable strings are safely rejected.", table_cell),
        ],
        [
            Paragraph("<b>Clock Drift & Publication Tolerance</b>", table_cell_bold),
            Paragraph("A 30-minute grace window (+30 min) accounts for publication server clock drift. Records dated more than 24.5 hours prior to execution or far in the future (>30 min) are permanently purged from the production dataset.", table_cell),
        ]
    ]
    t_fresh = Table(freshness_box, colWidths=[160, 380])
    t_fresh.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#F8FAFC")),
        ("BOX", (0, 0), (-1, -1), 0.8, colors.HexColor("#CBD5E1")),
        ("INNERGRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#E2E8F0")),
        ("TOPPADDING", (0, 0), (-1, -1), 3),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
        ("LEFTPADDING", (0, 0), (-1, -1), 5),
        ("RIGHTPADDING", (0, 0), (-1, -1), 5),
    ]))
    story.append(t_fresh)
    story.append(Spacer(1, 6))

    story.append(Paragraph("4. Structured LLM Extraction Engine & Multi-Tier Fallback Chain", h1_style))
    story.append(Paragraph(
        "Unstructured news articles and job postings require semantic parsing into structured schemas. The pipeline integrates a resilient 3-tier provider fallback chain adhering to Pydantic v2 schemas (<font name='Courier'>NewsSchema</font>, <font name='Courier'>JobSchema</font>):",
        body_style
    ))
    story.append(Spacer(1, 3))

    llm_table_data = [
        [
            Paragraph("Priority Tier", table_header),
            Paragraph("LLM Provider & Model", table_header),
            Paragraph("Protocol & Endpoint", table_header),
            Paragraph("Primary Role & Capability", table_header),
            Paragraph("Trigger Condition for Fallback", table_header),
        ],
        [
            Paragraph("<b>Tier 1 (Primary)</b>", table_cell_bold),
            Paragraph("Google Gemini<br/><b>gemini-3.1-flash-lite</b>", table_cell),
            Paragraph("REST <font name='Courier'>generateContent</font><br/>v1beta API", table_cell),
            Paragraph("Sub-second structured JSON generation, cost-effective multimodal token processing", table_cell),
            Paragraph("HTTP 404, 429 quota exhaustion, 500 server error, invalid JSON output", table_cell),
        ],
        [
            Paragraph("<b>Tier 2 (Fallback 1)</b>", table_cell_bold),
            Paragraph("Groq Cloud<br/><b>llama-3.3-70b-versatile</b>", table_cell),
            Paragraph("OpenAI-compatible<br/><font name='Courier'>/v1/chat/completions</font>", table_cell),
            Paragraph("Ultra-high tokens/sec inference, robust instruction-following for entity parsing", table_cell),
            Paragraph("HTTP 429 rate limit, network timeout (>30s), authentication error", table_cell),
        ],
        [
            Paragraph("<b>Tier 3 (Fallback 2)</b>", table_cell_bold),
            Paragraph("DeepSeek<br/><b>deepseek-chat (V3)</b>", table_cell),
            Paragraph("OpenAI-compatible<br/><font name='Courier'>/v1/chat/completions</font>", table_cell),
            Paragraph("High-reasoning semantic extraction, deep role family categorization", table_cell),
            Paragraph("Exhaustion of all remote providers engages deterministic local heuristics", table_cell),
        ],
    ]
    t_llm = Table(llm_table_data, colWidths=[65, 110, 115, 125, 125])
    t_llm.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1E3A8A")),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#F8FAFC")]),
        ("BOX", (0, 0), (-1, -1), 0.8, colors.HexColor("#CBD5E1")),
        ("INNERGRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#E2E8F0")),
        ("TOPPADDING", (0, 0), (-1, -1), 3),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
        ("LEFTPADDING", (0, 0), (-1, -1), 3.5),
        ("RIGHTPADDING", (0, 0), (-1, -1), 3.5),
        ("ALIGN", (0, 1), (0, -1), "CENTER"),
    ]))
    story.append(t_llm)
    story.append(Spacer(1, 5))

    story.append(Paragraph("5. Resilience Engineering: Handling HTTP 413 & HTTP 429", h1_style))
    story.append(Paragraph(
        "Robust ingestion systems must withstand hostile external API behaviors. Two specific HTTP failure modes are actively mitigated:",
        body_style
    ))
    story.append(Spacer(1, 2))

    resilience_data = [
        [
            Paragraph("<b>HTTP 413 (Payload Too Large) Bounding:</b>", table_cell_bold),
            Paragraph("Massive articles or bloated job postings exceeding token limits can crash downstream model contexts. The pipeline enforces a hard character bound (<font name='Courier'>MAX_PAYLOAD_CHARS = 8,000</font>) in <font name='Courier'>LLMService.extract_structured()</font>. Text exceeding 8,000 characters is cleanly truncated with an embedded warning marker, preserving critical semantic structure without exceeding provider ingress buffers.", table_cell),
        ],
        [
            Paragraph("<b>HTTP 429 (Rate Limit) Adaptive Backoff:</b>", table_cell_bold),
            Paragraph("Both arXiv and LLM APIs strictly enforce per-minute quotas. The shared utility (<font name='Courier'>src.utils.retry.with_retry</font>) implements exponential backoff with full jitter: $t_{\\text{wait}} = \\min(t_{\\text{max}}, t_{\\text{base}} \\times 2^{\\text{attempt}} + \\text{uniform}(0, 1))$. Furthermore, it parses origin <font name='Courier'>Retry-After</font> headers when supplied, backing off up to 35s on arXiv and switching providers instantaneously if rate limits persist.", table_cell),
        ],
    ]
    t_resilience = Table(resilience_data, colWidths=[160, 380])
    t_resilience.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#F8FAFC")),
        ("BOX", (0, 0), (-1, -1), 0.8, colors.HexColor("#CBD5E1")),
        ("INNERGRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#E2E8F0")),
        ("TOPPADDING", (0, 0), (-1, -1), 3),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
        ("LEFTPADDING", (0, 0), (-1, -1), 5),
        ("RIGHTPADDING", (0, 0), (-1, -1), 5),
    ]))
    story.append(t_resilience)

    # =========================================================================
    # PAGE 3: Entity Resolution, Export Architecture & Scale Roadmap
    # =========================================================================
    story.append(PageBreak())

    story.append(Paragraph("6. Entity Resolution & False-Positive Prevention Architecture", h1_style))
    story.append(Paragraph(
        "A naive entity resolver merging records solely on shared domains or exact URLs creates disastrous false positives (e.g. merging <i>Cursor</i>, <i>Windsurf</i>, and <i>Copilot</i> because they share a GitHub directory URL, or merging <i>Whisper</i> into <i>OpenAI Moderation</i> via generic documentation). The pipeline implements a 3-stage validation shield:",
        body_style
    ))
    story.append(Spacer(1, 3))

    er_shield_data = [
        [
            Paragraph("Guardrail Stage", table_header),
            Paragraph("Enforcement Mechanism", table_header),
            Paragraph("Protected Risk / False-Positive Prevented", table_header),
        ],
        [
            Paragraph("<b>1. URL Classification Engine</b>", table_cell_bold),
            Paragraph("Categorizes every incoming link into 6 explicit enum types: <font name='Courier'>GENERIC_PLATFORM_URL</font> (HuggingFace, Replicate), <font name='Courier'>DIRECTORY_URL</font> (GitHub repo lists, YC directories), <font name='Courier'>DOCUMENTATION_PORTAL</font> (API docs), <font name='Courier'>REPOSITORY_URL</font>, <font name='Courier'>ENTITY_SPECIFIC_URL</font>, and <font name='Courier'>UNKNOWN_URL</font>.", table_cell),
            Paragraph("Shared directory links or hosting platforms are <b>strictly forbidden</b> from acting as entity identity evidence under <font name='Courier'>EXACT_URL</font> matching.", table_cell),
        ],
        [
            Paragraph("<b>2. Name Compatibility Guard</b>", table_cell_bold),
            Paragraph("<font name='Courier'>are_names_compatible(name_a, name_b)</font> verifies that normalized token stems overlap before allowing a domain-based merge. Completely disjoint entity names sharing a corporate parent or hosting platform remain unmerged.", table_cell),
            Paragraph("Prevents independent sub-products (e.g., <i>Flux</i> hosted on Replicate, or <i>La Plateforme</i> vs <i>Cursor</i>) from collapsing into a single canonical ID.", table_cell),
        ],
        [
            Paragraph("<b>3. Conservative Fuzzy Thresholds & Seed Semantics</b>", table_cell_bold),
            Paragraph("Fuzzy Levenshtein matching requires token similarity ratio $\\ge 0.88$. Ambiguous matches are kept separate. New baseline seeds are assigned <font name='Courier'>confidence_score = 0.0</font> under method <font name='Courier'>NEW_CANONICAL_SEED</font> to clearly distinguish seed creation from merge confidence.", table_cell),
            Paragraph("Eliminates semantic drift across large catalogs; preserves clean audit trail in <font name='Courier'>entity_mapping_log.csv</font> (4,000 resolution events).", table_cell),
        ],
    ]
    t_er = Table(er_shield_data, colWidths=[110, 230, 200])
    t_er.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1E3A8A")),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#F8FAFC")]),
        ("BOX", (0, 0), (-1, -1), 0.8, colors.HexColor("#CBD5E1")),
        ("INNERGRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#E2E8F0")),
        ("TOPPADDING", (0, 0), (-1, -1), 3),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
        ("LEFTPADDING", (0, 0), (-1, -1), 4),
        ("RIGHTPADDING", (0, 0), (-1, -1), 4),
    ]))
    story.append(t_er)
    story.append(Spacer(1, 5))

    story.append(Paragraph("7. Centralized Export Service & Storage Architecture", h1_style))
    story.append(Paragraph(
        "All output artifacts are generated through the centralized singleton <font name='Courier'>ExportService</font> (<font name='Courier'>src/services/export_service.py</font>), guaranteeing schema consistency across formats:",
        body_style
    ))
    story.append(Spacer(1, 2))

    export_specs = [
        [
            Paragraph("<b>Raw Ingestion Store</b><br/><font name='Courier'>data/raw/*.json</font>", table_cell_bold),
            Paragraph("Stores unmutated, full-fidelity JSON payloads. Nested arrays (e.g. research paper author lists, complex job tags) and raw provider metadata are preserved without data loss. Ensures complete operational replayability.", table_cell),
        ],
        [
            Paragraph("<b>Processed Tabular Store</b><br/><font name='Courier'>data/processed/*.csv</font>", table_cell_bold),
            Paragraph("Generates clean CSV files for analytical ingestion. Employs recursive list flattening (semicolon-delimited strings), replaces Python <font name='Courier'>None</font> with empty strings (never string 'None'), and encodes output in standard UTF-8.", table_cell),
        ],
        [
            Paragraph("<b>Production Spreadsheet Deliverable</b><br/><font name='Courier'>deliverables/AI_Intelligence_Pipeline_Data.xlsx</font>", table_cell_bold),
            Paragraph("High-polish, 6-tab OpenPyXL workbook containing Startups (1,000), Products (1,000), Research Papers (1,000), Jobs (330), News (68), and Entity Mapping Log (4,000). Features frozen header rows, auto-filters, column auto-width, and canonical UUID linkage.", table_cell),
        ],
    ]
    t_export = Table(export_specs, colWidths=[150, 390])
    t_export.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#F8FAFC")),
        ("BOX", (0, 0), (-1, -1), 0.8, colors.HexColor("#CBD5E1")),
        ("INNERGRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#E2E8F0")),
        ("TOPPADDING", (0, 0), (-1, -1), 2.5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 2.5),
        ("LEFTPADDING", (0, 0), (-1, -1), 5),
        ("RIGHTPADDING", (0, 0), (-1, -1), 5),
    ]))
    story.append(t_export)
    story.append(Spacer(1, 5))

    story.append(Paragraph("8. Scale Limitations & Future Production Roadmap", h1_style))
    story.append(Paragraph(
        "While the current pipeline comfortably processes 1,000+ entities per category on a single node, scaling to tens of millions of records introduces architectural bottlenecks that will be addressed in future phases:",
        body_style
    ))
    story.append(Spacer(1, 2))

    scale_data = [
        [
            Paragraph("Current Architecture Limit", table_header),
            Paragraph("Root Bottleneck", table_header),
            Paragraph("Production Scale Roadmap Strategy", table_header),
        ],
        [
            Paragraph("<b>In-Memory Entity Resolution</b> (~50k records)", table_cell_bold),
            Paragraph("Pairwise name comparisons ($O(N^2)$ worst case) and memory bounds for inverted domain indices.", table_cell),
            Paragraph("Migrate canonical cluster store to <b>PostgreSQL with pg_trgm</b> or <b>DuckDB</b> for out-of-core trigram indexing and blocking keys.", table_cell),
        ],
        [
            Paragraph("<b>Single-Node Orchestration</b> (Local AsyncIO)", table_cell_bold),
            Paragraph("Process memory bounds and local IP egress limits on academic servers (arXiv rate limits).", table_cell),
            Paragraph("Transition to distributed task orchestration using <b>Temporal</b> or <b>Celery</b> with distributed residential proxy rotation.", table_cell),
        ],
        [
            Paragraph("<b>Lexical Entity Matching</b> (Levenshtein + URLs)", table_cell_bold),
            Paragraph("Unable to detect high-variance semantic aliases that do not share lexical tokens.", table_cell),
            Paragraph("Deploy hybrid vector retrieval using lightweight bi-encoder embeddings (<font name='Courier'>all-MiniLM-L6-v2</font>) in a vector index (Qdrant/Milvus).", table_cell),
        ],
    ]
    t_scale = Table(scale_data, colWidths=[120, 190, 230])
    t_scale.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1E3A8A")),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#F8FAFC")]),
        ("BOX", (0, 0), (-1, -1), 0.8, colors.HexColor("#CBD5E1")),
        ("INNERGRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#E2E8F0")),
        ("TOPPADDING", (0, 0), (-1, -1), 2.5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 2.5),
        ("LEFTPADDING", (0, 0), (-1, -1), 4),
        ("RIGHTPADDING", (0, 0), (-1, -1), 4),
    ]))
    story.append(t_scale)

    doc.build(story, canvasmaker=NumberedCanvas)
    print(f"Architecture PDF generated at: {PDF_PATH}")


if __name__ == "__main__":
    build_pdf()
