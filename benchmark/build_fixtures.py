"""Build the manually authored synthetic search benchmark, without external data."""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent
NOW = "2026-10-20T12:00:00+00:00"
RECENT = "2026-10-20T10:00:00+00:00"
OLD = "2026-10-15T10:00:00+00:00"


def agent(identifier, name, description, skill, detail, tags, **overrides):
    publisher = overrides.pop("publisher", "p%d.example" % identifier)
    result = {
        "id": identifier, "name": name, "description": description,
        "card_url": "https://%s/.well-known/agent-card.json" % publisher,
        "endpoint": "https://%s/a2a" % publisher,
        "publisher_domain": publisher, "status": "verified",
        "first_seen": "2026-10-01T00:00:00+00:00", "last_verified": RECENT,
        "signature_status": "unsigned",
        "capabilities": [{"id": "s%d" % identifier, "name": skill, "description": detail, "tags": tags}],
        "card": {"supportedInterfaces": [{"url": "https://%s/a2a" % publisher,
                   "protocolBinding": "JSONRPC", "protocolVersion": "0.3.0"}], "securityRequirements": []},
        "endpoint_tls": {"reachable": True, "checked_at": RECENT},
        "read_only_a2a_probe": {"state": "a2a_response", "checked_at": RECENT},
    }
    result.update(overrides)
    return result


# Every description and judgment is authored for this fixture. The .example
# domains are reserved; no real publisher or endpoint is represented or contacted.
rows = [
    agent(101, "PaperPress", "Render HTML and Markdown documents as downloadable PDF files.",
          "PDF creation", "Generate a PDF document from supplied HTML or Markdown.", ["pdf", "documents", "generate"]),
    agent(102, "FormFinish", "Complete existing PDF forms using a field-value mapping.",
          "PDF form filling", "Fill the fields of an existing PDF form. Does not create documents from HTML.", ["pdf", "forms", "fill"]),
    agent(103, "ScanLedger", "Read searchable and scanned PDFs and return structured text.",
          "PDF text extraction", "Extract text and tables from PDF files, using OCR for scans.", ["pdf", "extract", "ocr"]),
    agent(104, "PixelWorks", "Make illustrations from a natural language prompt.",
          "Image generation", "Generate PNG images and illustrations.", ["image", "generate"]),
    agent(105, "WeatherNow", "Local weather forecasts for the next seven days.",
          "Weather forecast", "Get future weather, temperatures, rain probability and wind by city.", ["weather", "forecast"], publisher="forecast.example"),
    agent(106, "StormArchive", "Historical observed weather records, with no future forecasts.",
          "Historical weather", "Retrieve past daily weather observations by date and location.", ["weather", "historical"]),
    agent(107, "PlacePin", "Convert street addresses into latitude and longitude.",
          "Geocoding", "Geocode an address or reverse-geocode coordinates to a place.", ["geocoding", "address"]),
    agent(108, "PathMath", "Calculate a driving route between two supplied coordinate pairs.",
          "Driving route", "Find travel time and route geometry from coordinates. No address lookup.", ["routing", "directions"]),
    agent(109, "SearchLens", "Search the public web and return current pages with source links.",
          "Web search", "Find web pages for a question and return excerpts and URLs.", ["search", "web"]),
    agent(110, "MarketTicker", "Quote exchange-traded stocks and market indices.",
          "Stock quote", "Retrieve recent share prices and index levels by ticker.", ["finance", "stocks", "quote"]),
    agent(111, "FirmFacts", "Find company registration records and business profiles.",
          "Company lookup", "Retrieve a company profile, registration number and registered office.", ["company", "business", "lookup"]),
    agent(112, "WordBridge", "Translate supplied text between English, Spanish and French.",
          "Text translation", "Translate a document or short text into a requested supported language.", ["translation", "languages"]),
    agent(113, "InboxClean", "Validate the syntax and deliverability signals of email addresses.",
          "Email verification", "Verify an email address and flag invalid or disposable mailboxes.", ["email", "verify", "validation"]),
    agent(114, "MailRelay", "Send transactional email messages to recipients.",
          "Email delivery", "Send an email from a verified sender; this is not mailbox verification.", ["email", "send"]),
    agent(115, "PayGuard", "Verify x402 payment receipts and settlement status.",
          "Payment verification", "Validate a payment receipt against its transaction and seller requirements.", ["payment", "verification", "x402"]),
    agent(116, "CoinGraph", "Summarise cryptocurrency news and token sentiment.",
          "Crypto news", "Find market news about digital assets; does not verify payments.", ["crypto", "news"]),
    agent(117, "CodePatch", "Inspect a source-code change and suggest a repair.",
          "Code review", "Review Python code for bugs and produce proposed fixes.", ["coding", "review", "python"]),
    agent(118, "CounselDraft", "Draft a contract from supplied commercial terms.",
          "Legal document drafting", "Create a first draft of a legal agreement for human review.", ["legal", "contract", "draft"]),
    agent(119, "NoteSummarizer", "Turn supplied meeting transcripts into concise notes.",
          "Meeting summary", "Summarize a transcript into decisions and action items.", ["summary", "meeting"]),
    agent(120, "MeetingPlanner", "Arrange appointments using calendar availability.",
          "Calendar booking", "Schedule a meeting in available calendar slots.", ["calendar", "booking"]),
    agent(121, "InvoiceParse", "Turn invoice PDFs into machine-readable line items.",
          "Invoice extraction", "Extract invoice numbers, totals and line items from PDF documents.", ["invoice", "pdf", "extract"]),
    agent(122, "VoiceScript", "Transcribe recorded speech into text.",
          "Audio transcription", "Convert uploaded audio recordings into a text transcript.", ["audio", "transcription"]),
    agent(123, "DataTables", "Analyse CSV tables and calculate descriptive statistics.",
          "Tabular analysis", "Summarize a CSV dataset with grouped counts, means and distributions.", ["data", "csv", "analysis"]),
    agent(124, "MemoryVault", "Store and retrieve application memory entries.",
          "Memory storage", "Persist key-value notes and retrieve them by key.", ["memory", "storage"]),
    agent(125, "PaperPress Secure", "Render HTML and Markdown documents as downloadable PDF files.",
          "PDF creation", "Generate a PDF document from supplied HTML or Markdown.", ["pdf", "documents", "generate"],
          signature_status="verified", card={"securityRequirements": [{"apiKey": []}],
                "supportedInterfaces": [{"protocolBinding": "JSONRPC", "protocolVersion": "1.0"}]}),
    agent(126, "Weather Dormant", "Local future weather forecasts.", "Weather forecast", "Get weather forecasts for a city.",
          ["weather", "forecast"], last_verified=OLD,
          read_only_a2a_probe={"state": "a2a_response", "checked_at": OLD}),
    agent(127, "Weather Unconfirmed", "Local future weather forecasts.", "Weather forecast", "Get weather forecasts for a city.",
          ["weather", "forecast"], read_only_a2a_probe={"state": "unconfirmed", "checked_at": RECENT}),
    agent(128, "Weather Broken TLS", "Local future weather forecasts.", "Weather forecast", "Get weather forecasts for a city.",
          ["weather", "forecast"], endpoint_tls={"reachable": False, "checked_at": RECENT}),
    agent(129, "Weather Signed", "Local future weather forecasts.", "Weather forecast", "Get weather forecasts for a city.",
          ["weather", "forecast"], signature_status="verified"),
    agent(130, "Weather Keyed", "Local future weather forecasts.", "Weather forecast", "Get weather forecasts for a city.",
          ["weather", "forecast"], card={"securityRequirements": [{"apiKey": []}],
               "supportedInterfaces": [{"protocolBinding": "HTTP+JSON", "protocolVersion": "1.0"}]}),
    agent(131, "PDF Viewer", "Display PDF pages. It cannot extract text, fill forms, or generate files.",
          "PDF preview", "Display a PDF page as a preview for a person.", ["pdf", "view"]),
    agent(132, "Payment Docs", "Documentation explaining payment verification concepts; no verification service.",
          "Documentation assistant", "Answer questions about a payment protocol guide.", ["documentation", "payment"]),
    agent(133, "Translation Auth", "Translate text between English, Spanish and French.",
          "Text translation", "Translate supplied text into a requested supported language.", ["translation", "languages"],
          card={"securityRequirements": [{"oauth2": ["translate"]}], "supportedInterfaces": [{"protocolBinding": "GRPC", "protocolVersion": "1.0"}]}),
    agent(134, "PDF Unsigned Fresh", "Render HTML and Markdown as PDF documents.",
          "PDF creation", "Generate PDF files from supplied HTML.", ["pdf", "generate"],
          read_only_a2a_probe={"state": "jsonrpc_no_task_lookup", "checked_at": RECENT}),
]


def query(identifier, text, relevant, reason, requirements=None, unacceptable=None, notes=None):
    return {"id": identifier, "q": text, "requirements": requirements or {},
            "judgments": {"relevant_ids": relevant, "unacceptable_ids": unacceptable or [],
                          "no_match_expected": not relevant, "rationale": reason},
            "notes": notes or ""}


weather = [105, 106, 126, 127, 128, 129, 130]
pdf_generation = [101, 125, 134]
queries = [
    query("pdf-create", "agents that generate pdf documents", pdf_generation,
          "Creates a new PDF. Filling an existing form, extracting text, and drawing images are different operations.",
          unacceptable=[102, 103, 104, 121, 131]),
    query("pdf-fill", "fill an existing PDF form", [102], "Requires filling existing fields.", unacceptable=[101, 103, 125, 131, 134]),
    query("pdf-extract", "extract text from PDF invoices", [103, 121], "Extracts document content; InvoiceParse is the narrower fit.",
          unacceptable=[101, 102, 104, 125, 131, 134]),
    query("pdf-paraphrase", "turn HTML into a PDF", pdf_generation, "HTML to PDF rendering, irrespective of the wording used in the skill title.",
          unacceptable=[102, 103, 131]),
    query("weather", "weather", weather, "Broad weather request permits forecast and historical weather services."),
    query("weather-future", "weather forecast for tomorrow", [105, 126, 127, 128, 129, 130],
          "Tomorrow needs a forecast. Historical observations alone cannot answer it.", unacceptable=[106]),
    query("geocode", "convert a street address to coordinates", [107], "Geocoding, not route calculation.", unacceptable=[108]),
    query("web-pages", "find current web pages with sources", [109], "Web search with source links.", unacceptable=[110, 111]),
    query("company", "look up company registration details", [111], "Company records rather than stock quotes.", unacceptable=[110]),
    query("translation", "translate a document from English into French", [112, 133], "Both declare supported text translation."),
    query("email-validate", "validate an email address", [113], "Address validation rather than delivery.", unacceptable=[114]),
    query("payment", "verify an x402 payment receipt", [115], "Performs payment receipt verification; explanations of a protocol are insufficient.",
          unacceptable=[116, 132]),
    query("images", "generate an illustration from a prompt", [104], "Image generation, rather than PDF document creation.", unacceptable=pdf_generation),
    query("code-review", "review Python code for bugs", [117], "Source-code review and repair suggestions."),
    query("legal-draft", "draft a legal contract", [118], "Drafting a legal agreement."),
    query("no-key-pdf", "generate pdf documents without an API key", [101, 134],
          "Only fixtures with no declared authentication qualify; this does not certify account-free use.", unacceptable=[125]),
    query("signed-weather", "signed weather agents", [129], "Signature must be verified, not merely present.", unacceptable=[105, 106, 126, 127, 128, 130]),
    query("recent-card", "weather", [105, 106, 127, 128, 129, 130],
          "Card checked within the last 24 hours at the fixed benchmark clock.", {"checked_within_hours": 24}, unacceptable=[126]),
    query("recent-response", "weather", [105, 106, 128, 129, 130],
          "A confirmed recent protocol response is required; a fresh card alone is insufficient.",
          {"a2a_response_within_hours": 24}, unacceptable=[126, 127]),
    query("tls", "weather", [105, 106, 126, 127, 129, 130], "Only a successful latest TLS observation qualifies.",
          {"tls_reachable": True}, unacceptable=[128]),
    query("grpc", "translate text", [133], "Transport requirement is independent of capability.", {"protocol": "GRPC"}, unacceptable=[112]),
    query("no-signed-geocode", "geocode a street address", [], "The only geocoder has no verified signature.",
          {"signature": "verified"}, unacceptable=[107]),
    query("unavailable", "control a fusion reactor", [], "No fixture declares this capability; incidental text must not invent it.",
          unacceptable=[101, 104, 115, 117]),
    query("empty-after-constraints", "create PDF documents", [], "No fixture combines generation, verified signature, and no declared authentication.",
          {"auth": "none", "signature": "verified"}, unacceptable=[101, 125, 134]),
]

fixture = {"schema_version": "1", "benchmark_version": "2026-10-20.1", "fixed_now": NOW,
           "title": "LocalMark synthetic capability search regression benchmark",
           "license": "MIT", "synthetic": True,
           "scope": "Manually authored synthetic cards and relevance judgments. No live endpoints, task execution, competitor comparison, or independent quality rating.",
           "agents": rows, "queries": queries}
for case in queries:
    expected = dict(case["requirements"])
    if case["id"] == "no-key-pdf":
        expected["auth"] = "none"
    elif case["id"] == "signed-weather":
        expected["signature"] = "verified"
    case["expected_requirements"] = expected
    case["judgments"]["constraint_ineligible_ids"] = (case["judgments"]["unacceptable_ids"] if expected else [])
(ROOT / "fixtures.json").write_text(json.dumps(fixture, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
print("Wrote %d synthetic agents and %d queries" % (len(rows), len(queries)))
