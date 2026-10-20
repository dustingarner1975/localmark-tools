"""Deterministic capability recommendations over stored public-card evidence.

No network requests, task execution, embeddings, or language-model calls occur here.
The small, published vocabulary improves retrieval without treating a publisher's
description as an instruction. Scores describe relevance, never safety or trust.

``interpret_query(q)`` exposes the controlled concepts and the few supported
natural-language evidence constraints. ``rank_agents(agents, q, requirements)``
accepts ordinary agent dictionaries and returns *all* matching items in order;
the caller is responsible for candidate loading, price filters and pagination.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from functools import lru_cache
import re
import unicodedata
from urllib.parse import urlsplit


RANKING_VERSION = "capability-1.0"
SCOPE = ("Recommendations match publisher-declared capabilities to a controlled vocabulary "
         "and stored LocalMark observations. Relevance is not a safety rating. "
         "No task is executed and successful task results are not established.")

# topic groups distinguish an explicit operation from another operation on the
# same object. Aliases are normalized at import time and matched as whole words.
# Keep these editorial and reviewable; do not add fixture names to the vocabulary.
_VOCABULARY = [
    ("pdf_extraction", "PDF text and data extraction", "pdf", "extract", [
        "pdf extraction", "extract pdf", "extract text from pdf", "extract data from pdf",
        "extract text from a pdf", "pdf to text", "pdf to json", "pdf parsing", "parse pdf",
        "pdf parser", "read pdf", "pdf ocr", "ocr", "invoice extraction", "parse invoices",
        "document extraction", "extract invoices", "extract invoice data"]),
    ("pdf_filling", "PDF form filling", "pdf", "fill", [
        "pdf form filling", "pdf form filler", "fill pdf", "fill a pdf", "fill in pdf",
        "populate pdf", "complete pdf", "pdf autofill"]),
    ("pdf_generation", "PDF document generation", "pdf", "generate", [
        "generate pdf", "create pdf", "make pdf", "produce pdf", "render pdf", "pdf generation",
        "pdf generator", "pdf creation", "html to pdf", "markdown to pdf", "generate a pdf", "create a pdf"]),
    ("pdf", "PDF documents", "pdf", "", ["pdf", "portable document format"]),
    ("weather", "Weather and forecasts", "weather", "", [
        "weather", "forecast", "forecasts", "meteorological", "rainfall", "temperature forecast"]),
    ("weather_forecast", "Future weather forecasts", "weather", "forecast", [
        "weather forecast", "future weather", "forecast tomorrow", "weather tomorrow", "forecast for tomorrow",
        "weather for tomorrow", "tomorrow weather", "weather prediction"]),
    ("weather_history", "Historical weather observations", "weather", "history", [
        "historical weather", "past weather", "weather history", "historical observations", "historical climate"]),
    ("web_search", "Web search", "web_search", "search", [
        "web search", "search the web", "internet search", "search engine", "search internet",
        "browse the web", "online search", "web research", "search online", "find websites"]),
    ("payment_verification", "Payment verification", "payments", "verify", [
        "verify payment", "payment verification", "confirm payment", "verify transaction",
        "transaction verification", "payment proof", "validate payment", "check payment",
        "payment receipt verification", "verify a payment", "confirm a payment"]),
    ("payments", "Payment processing", "payments", "", [
        "payments", "payment processing", "accept payments", "x402", "payment", "settlement"]),
    ("geocoding", "Address and coordinate geocoding", "geocoding", "", [
        "geocoding", "geocode", "reverse geocoding", "address to coordinates", "address to latitude",
        "coordinates to address", "latitude and longitude", "postal address lookup"]),
    ("translation", "Language translation", "translation", "", [
        "translation", "translate", "translator", "language conversion", "translate text",
        "multilingual translation"]),
    ("email_verification", "Email address verification", "email", "verify", [
        "email verification", "verify email", "validate email", "email validation",
        "email address verification", "check email address", "email deliverability", "verify an email",
        "validate an email", "email verifier"]),
    ("email_sending", "Sending email", "email", "send", [
        "send email", "email sending", "send an email", "transactional email", "email delivery",
        "send emails", "email notifications"]),
    ("company_data", "Company and business data", "company_data", "", [
        "company data", "company lookup", "business data", "company information", "business information",
        "company enrichment", "business enrichment", "company registry", "corporate data",
        "company research", "business lookup", "firmographic", "firmographics"]),
    ("image_generation", "Image generation", "image", "generate", [
        "image generation", "generate images", "generate image", "create images", "create image",
        "text to image", "image generator", "ai artwork", "generate pictures", "create pictures",
        "make images", "illustration generation"]),
    ("image_analysis", "Image analysis", "image", "analyze", [
        "image analysis", "analyze images", "analyse images", "image recognition", "computer vision",
        "object detection", "describe images", "image classification"]),
    ("coding", "Code generation and development", "coding", "", [
        "coding", "code generation", "generate code", "write code", "software development",
        "programming", "coding assistant", "code assistant", "developer assistant"]),
    ("code_review", "Code review and analysis", "code_review", "", [
        "code review", "review code", "static analysis", "code analysis", "code security review"]),
    ("legal_documents", "Legal documents and contracts", "legal_documents", "", [
        "legal document", "legal documents", "legal contract", "legal contracts", "contract review",
        "review contracts", "contract analysis", "legal drafting", "draft contracts", "legal research"]),
    ("speech_to_text", "Speech transcription", "audio", "transcribe", [
        "speech to text", "transcription", "transcribe", "audio to text", "transcribe audio",
        "speech recognition"]),
    ("text_to_speech", "Speech generation", "audio", "generate", [
        "text to speech", "speech generation", "generate speech", "voice synthesis", "speech synthesis"]),
    ("web_scraping", "Web data extraction", "web_scraping", "", [
        "web scraping", "web scraper", "scrape websites", "scrape web", "web extraction",
        "extract web data", "website scraping", "website extraction"]),
    ("financial_data", "Financial market data", "financial_data", "", [
        "financial data", "market data", "stock prices", "stock price", "equity data",
        "exchange rates", "currency rates", "financial research"]),
    ("summarization", "Text summarization", "summarization", "", [
        "summarize", "summarise", "summarization", "summarisation", "text summary", "document summary"]),
    ("travel", "Travel and accommodation search", "travel", "", [
        "flight search", "find flights", "hotel search", "find hotels", "travel planning", "travel agent"]),
    ("documentation", "Documentation assistance", "documentation", "", [
        "documentation assistant", "documentation search", "search documentation", "docs assistant",
        "documentation help"]),
]

_WORD_MAP = {
    "generates": "generate", "generating": "generate", "generated": "generate",
    "creates": "create", "creating": "create", "created": "create",
    "extracts": "extract", "extracting": "extract", "extracted": "extract",
    "fills": "fill", "filling": "fill", "filler": "fill",
    "parses": "parse", "parsing": "parse", "parser": "parse",
    "verifies": "verify", "verifying": "verify", "verified": "verify",
    "validates": "validate", "validating": "validate", "validated": "validate",
    "sends": "send", "sending": "send", "sent": "send",
    "translates": "translate", "translating": "translate",
    "summarizes": "summarize", "summarises": "summarize", "summarise": "summarize",
    "documents": "document", "invoices": "invoice", "forms": "form",
    "images": "image", "pictures": "picture", "contracts": "contract",
    "emails": "email", "payments": "payment", "transactions": "transaction",
    "coordinates": "coordinate", "forecasts": "forecast", "websites": "website",
    "companies": "company", "businesses": "business", "addresses": "address",
    "analyses": "analysis", "analyzes": "analyze", "analyse": "analyze",
    "pdfs": "pdf",
}
_STOP = set("a an the and or for from to of in on with without that which who is are be can "
            "could should would i we me my us you your they it its this these those need want "
            "looking look find give show get use using agent agents service services tool tools "
            "capability capabilities available best good better please public live trusted "
            "help helps supports support provide provides providing powered ai a2a api bot bots "
            "does do works work run running task tasks request requests text data".split())


def _normalize(value):
    value = unicodedata.normalize("NFKC", str(value or "")).casefold()
    value = re.sub(r"\b(?:json[\s_-]*rpc)\b", "jsonrpc", value)
    value = re.sub(r"\b(?:e[\s-]*mail)\b", "email", value)
    words = re.findall(r"[^\W_]+", value, flags=re.UNICODE)
    return " ".join(_WORD_MAP.get(word, word) for word in words)


def _normalize_evidence(value):
    # A later sentence is not an object of a preceding verb (or vice versa).
    # Preserve that boundary inside evidence features; the public query plan
    # continues to expose ordinary normalized text.
    parts = re.split(r"[.!?](?=\s)|;|[\r\n]+", str(value or ""))
    return " | ".join(normalized for part in parts if (normalized := _normalize(part)))


CONCEPTS = tuple({"id": key, "label": label, "topic": topic, "operation": operation,
                  "aliases": tuple(dict.fromkeys(_normalize(alias) for alias in aliases))}
                 for key, label, topic, operation, aliases in _VOCABULARY)
_BY_ID = {concept["id"]: concept for concept in CONCEPTS}
_ALIAS_TRIE = {}
for _concept in CONCEPTS:
    for _alias in _concept["aliases"]:
        _node = _ALIAS_TRIE
        for _word in _alias.split():
            _node = _node.setdefault(_word, {})
        _node.setdefault(None, set()).add(_concept["id"])


def _contains(text, phrase):
    return bool(phrase and (" " + phrase + " ") in (" " + text + " "))


@lru_cache(maxsize=32768)
def _concepts(text):
    words = text.split()
    found = set()
    # Walk only aliases beginning at words present in the text. This avoids
    # scanning a large declaration once for every vocabulary phrase.
    for start, word in enumerate(words):
        node = _ALIAS_TRIE.get(word)
        position = start + 1
        while node is not None:
            found.update(node.get(None, ()))
            node = node.get(words[position]) if position < len(words) else None
            position += 1
    # Preserve operation intent in phrases with intervening adjectives: e.g.
    # "generate structured PDF invoices". Another output object in between
    # ("generate images from PDF") stops that inference.
    pdf_positions = [i for i, word in enumerate(words) if word == "pdf"]
    operation_words = {
        "pdf_extraction": {"extract", "parse", "ocr", "read", "extraction", "parser"},
        "pdf_filling": {"fill", "populate", "complete", "autofill"},
        "pdf_generation": {"generate", "create", "make", "produce", "render", "generation", "generator"},
    }
    for position in pdf_positions:
        for cid, verbs in operation_words.items():
            for offset in range(max(0, position - 6), min(len(words), position + 3)):
                if words[offset] not in verbs:
                    continue
                between = words[min(offset, position) + 1:max(offset, position)]
                if not set(between) & {"|", "image", "picture", "speech", "email", "code", "weather"}:
                    found.add(cid)
    for position, word in enumerate(words):
        if word != "payment":
            continue
        for offset in range(max(0, position - 5), position):
            if words[offset] in {"verify", "confirm", "validate", "check"}:
                between = words[offset + 1:position]
                if not set(between) & {"|", "email", "identity", "signature", "domain", "code"}:
                    found.add("payment_verification")
    if re.search(r"\b(?:html|markdown) (?:in)?to (?:a )?pdf\b", text):
        found.add("pdf_generation")
    # A generic PDF/payment topic is redundant when a particular operation is
    # explicitly recognized. This prevents a wrong operation gaining a full hit.
    if found & {"pdf_extraction", "pdf_filling", "pdf_generation"}:
        found.discard("pdf")
    if "payment_verification" in found:
        found.discard("payments")
    if found & {"weather_forecast", "weather_history"}:
        found.discard("weather")
    return frozenset(found)


@lru_cache(maxsize=32768)
def _negated_concepts(text):
    """Suppress explicit negative claims, without interpreting instructions.

    Card text such as "does not generate PDF" must not become positive evidence.
    This intentionally small rule only examines a short negative clause.
    """
    negated = set()
    if not re.search(r"\b(?:not|cannot|never|no)\s+", text, flags=re.IGNORECASE):
        return frozenset()
    normalized = _normalize(text)
    for match in re.finditer(r"\b(?:not|cannot|never|no)\s+([^.;!?\n]{1,160})", text.casefold()):
        clause = _normalize(re.split(r"\b(?:but|however|instead)\b", match.group(1), maxsplit=1)[0])
        negated |= _concepts(clause)
        # PDF viewers commonly say "does not extract, fill or generate" after
        # naming PDF once. Preserve that explicit operation-level exclusion.
        if _contains(normalized, "pdf"):
            for word, cid in (("extract", "pdf_extraction"), ("fill", "pdf_filling"), ("generate", "pdf_generation")):
                if _contains(clause, word):
                    negated.add(cid)
        if _contains(normalized, "payment") and re.search(r"\b(?:verify|verification|validate)\b", clause):
            negated.add("payment_verification")
        if _contains(normalized, "email") and re.search(r"\b(?:verify|verification|validate)\b", clause):
            negated.add("email_verification")
        if re.search(r"\b(?:perform|execute|run|provide) (?:it|them|these|those)\b", clause):
            negated |= _concepts(_normalize(text[:match.start()]))
    return frozenset(negated)


def _put_requirement(requirements, key, value, conflicts):
    if key in requirements and requirements[key] != value:
        conflicts.append({"requirement": key, "values": [requirements[key], value],
                          "message": "The query contains conflicting requirements."})
    else:
        requirements[key] = value


def interpret_query(q):
    """Return a transparent query plan; unrecognized text remains search text.

    Only authentication declaration, signature verification, card/probe recency
    and TLS are interpreted as natural-language constraints. Unsupported price,
    geography, legal compliance and task-performance requests are disclosed.
    An absent authentication declaration never establishes account-free access.
    """
    original = str(q or "").strip()
    text = original.casefold()
    requirements, conflicts, unsupported, excluded = {}, [], [], []
    removed = []

    patterns = [
        (r"\b(?:no|without|does(?:n't| not) require|do(?:n't| not) require)\s+(?:an?\s+)?(?:auth(?:entication)?|api[ -]?keys?|accounts?|sign[ -]?ups?|login)\b", "auth", "none"),
        (r"\b(?:no[ -]auth|unauthenticated|account[ -]free)\b", "auth", "none"),
        (r"\b(?:requires?|with)\s+(?:an?\s+)?(?:authentication|api[ -]?keys?)\b", "auth", "declared"),
        (r"\b(?:verified\s+signature|signature[ -]verified|signed(?:\s+cards?|\s+agents?)?)\b", "signature", "verified"),
        (r"\b(?:reachable\s+tls|valid\s+tls|tls\s+(?:passed|reachable|connection)|https\s+reachable)\b", "tls_reachable", True),
    ]
    for pattern, key, value in patterns:
        for match in re.finditer(pattern, text):
            _put_requirement(requirements, key, value, conflicts)
            removed.append(match.span())

    # Restrict units and the range instead of silently converting "last month".
    recency = [
        (r"\b(?:card(?:s)?\s+)?(?:checked|verified|rechecked)(?:\s+(?:within|in|during)(?:\s+the)?(?:\s+last)?)?\s+(\d+)\s*(hours?|hrs?|h|days?)\b", "checked_within_hours"),
        (r"\b(?:a2a\s+)?(?:responded|responding|answered|response\s+confirmed)(?:\s+(?:within|in|during)(?:\s+the)?(?:\s+last)?)?\s+(\d+)\s*(hours?|hrs?|h|days?)\b", "a2a_response_within_hours"),
    ]
    for pattern, key in recency:
        for match in re.finditer(pattern, text):
            hours = int(match.group(1)) * (24 if match.group(2).startswith("day") else 1)
            if 1 <= hours <= 168:
                _put_requirement(requirements, key, hours, conflicts)
            else:
                unsupported.append({"constraint": match.group(0), "reason": "Supported recency is 1 to 168 hours."})
            removed.append(match.span())

    # A negated operation must not become a requested capability. This selects
    # validation instead of delivery; it does not establish runtime side effects.
    for match in re.finditer(r"\bwithout\s+(?:send(?:ing)?|deliver(?:ing)?)\s+(?:an?\s+)?emails?\b", text):
        excluded.append({"id": "email_sending", "label": "Sending email", "scope": "requested_operation"})
        removed.append(match.span())

    # Price constraints are implemented by the caller only when explicit filters
    # are supplied. Do not infer free services from a publisher's marketing copy.
    unsupported_patterns = [
        (r"\b(?:free|free of charge|no cost|no payment|without payment|cheapest|under\s+\$?\d+(?:\.\d+)?|less than\s+\$?\d+(?:\.\d+)?)\b", "Price requests need explicit price filters and stored price observations."),
        (r"\b(?:(?:eu|european|us|usa|uk)[ -](?:hosted|only)|hosted in (?:the )?(?:eu|europe|us|usa|uk))\b", "Hosting location is not established by stored card checks."),
        (r"\b(?:gdpr compliant|hipaa compliant|soc[ -]?2|guaranteed|proven safe|no hallucinations?)\b", "Legal compliance, safety and task accuracy are not established by these checks."),
        (r"\b(?:(?:answered|responded|checked|verified) recently|recently (?:answered|responded|checked|verified))\b", "Choose an explicit card-check or A2A-response interval of 1 to 168 hours."),
        (r"\b(?:accept(?:s|ing)?|pay(?:ing)? (?:with|in))\s+(?:payments?\s+(?:in|on)\s+)?(?:usdc|usdt|bitcoin|btc|nano|xno|solana|base|ethereum)\b", "Price requests need explicit asset or network filters and stored price observations."),
        (r"\b(?:never sends?(?:\s+an?)?\s+emails?|guaranteed (?:no|not to send)(?:\s+outbound)?\s+emails?|without ever sending emails?)\b", "Stored declarations do not establish a guarantee that an operation never sends email."),
    ]
    for pattern, reason in unsupported_patterns:
        for match in re.finditer(pattern, text):
            unsupported.append({"constraint": match.group(0), "reason": reason})
            removed.append(match.span())
    chars = list(original)
    for start, end in removed:
        chars[start:end] = " " * (end - start)
    capability_query = " ".join("".join(chars).split()).strip(" ,;.")
    normalized = _normalize(capability_query)
    concepts = _concepts(normalized)
    meaningful = list(dict.fromkeys(word for word in normalized.split() if word not in _STOP and len(word) > 1))
    return {
        "original": original, "normalized": normalized, "capability_query": capability_query,
        "concepts": [{key: concept[key] for key in ("id", "label", "operation")}
                     for concept in CONCEPTS if concept["id"] in concepts],
        "meaningful_terms": meaningful, "requirements": requirements,
        "unsupported_constraints": unsupported, "conflicts": conflicts, "excluded_concepts": excluded,
    }


def _datetime(value):
    if isinstance(value, datetime):
        return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)
    if isinstance(value, str):
        try:
            return _datetime(datetime.fromisoformat(value.replace("Z", "+00:00")))
        except ValueError:
            pass
    return None


def _recent(value, hours, now):
    value = _datetime(value)
    # Future clock errors must not qualify as fresh evidence.
    return bool(value and now - timedelta(hours=hours) <= value <= now + timedelta(minutes=5))


def _card(agent):
    return agent.get("card") if isinstance(agent.get("card"), dict) else {}


def _nonempty_security(value):
    if isinstance(value, list):
        # An explicit anonymous alternative means authentication is optional.
        if any(entry == {} for entry in value):
            return False
        return any(_nonempty_security(entry) for entry in value)
    if isinstance(value, dict):
        # In A2A/OpenAPI {"apiKey": []} requires apiKey; the empty list is
        # an empty scope set, not an absence of authentication.
        security_keys = [k for k in value if k not in {"description", "credentials", "schemes"}]
        if security_keys:
            return True
        return _nonempty_security(value.get("schemes"))
    return str(value or "").casefold() not in {"", "none", "anonymous", "noauth", "no auth"}


def authentication_state(agent):
    """Return 'required' or 'not_declared'; absence never verifies no account."""
    card = _card(agent)
    probe = agent.get("read_only_a2a_probe") or {}
    if isinstance(probe, dict) and probe.get("state") in {"auth_required", "authentication_required"}:
        return "required"
    if any(_nonempty_security(card.get(key)) for key in ("securityRequirements", "security", "authentication")):
        return "required"
    return "not_declared"


def _protocols(agent):
    card = _card(agent)
    interfaces = card.get("supportedInterfaces") or []
    protocols = set()
    aliases = {"JSONRPC": "JSONRPC", "JSON-RPC": "JSONRPC", "JSON_RPC": "JSONRPC",
               "HTTP+JSON": "HTTP+JSON", "HTTP/JSON": "HTTP+JSON", "REST": "HTTP+JSON", "GRPC": "GRPC"}
    for interface in interfaces:
        if isinstance(interface, dict):
            binding = interface.get("protocolBinding") or interface.get("transport")
            if binding:
                protocols.add(aliases.get(str(binding).upper(), str(binding).upper()))
    legacy = card.get("preferredTransport")
    if legacy:
        protocols.add(aliases.get(str(legacy).upper(), str(legacy).upper()))
    # A 0.2/0.3 legacy card with a URL and no transport defaults to JSON-RPC.
    version = str(card.get("protocolVersion") or agent.get("protocol_version") or "")
    if not protocols and version.startswith(("0.2", "0.3")) and (card.get("url") or agent.get("endpoint")):
        protocols.add("JSONRPC")
    return protocols


def _effective_requirements(interpreted, requirements):
    allowed = {"auth", "signature", "protocol", "checked_within_hours", "a2a_response_within_hours", "tls_reachable"}
    effective = dict(interpreted["requirements"])
    conflicts = list(interpreted["conflicts"])
    for key, value in (requirements or {}).items():
        if key not in allowed:
            # The caller may carry price metadata; it must apply those filters.
            continue
        if value in (None, "") or (key == "tls_reachable" and value is False):
            continue
        if key in {"checked_within_hours", "a2a_response_within_hours"}:
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not (1 <= value <= 168):
                raise ValueError(key + " must be between 1 and 168 hours")
        if key == "auth" and value not in {"none", "declared"}:
            raise ValueError("auth must be none or declared")
        if key == "signature" and value != "verified":
            raise ValueError("signature must be verified")
        if key == "protocol" and value not in {"JSONRPC", "HTTP+JSON", "GRPC"}:
            raise ValueError("protocol must be JSONRPC, HTTP+JSON or GRPC")
        if key == "tls_reachable" and not isinstance(value, bool):
            raise ValueError("tls_reachable must be a boolean")
        if key in effective and effective[key] != value:
            conflicts.append({"requirement": key, "query_value": effective[key], "explicit_value": value,
                              "message": "The explicit filter overrides the requirement in the query."})
        effective[key] = value
    return effective, conflicts


def _meets(agent, requirements, now):
    auth = authentication_state(agent)
    if requirements.get("auth") == "none" and auth == "required":
        return False
    if requirements.get("auth") == "declared" and auth != "required":
        return False
    signature = agent.get("signature_status") or (agent.get("signature") or {}).get("status")
    if requirements.get("signature") and signature != "verified":
        return False
    if requirements.get("protocol") and requirements["protocol"] not in _protocols(agent):
        return False
    if requirements.get("checked_within_hours") and not _recent(agent.get("last_verified"), requirements["checked_within_hours"], now):
        return False
    probe = agent.get("read_only_a2a_probe") or {}
    if requirements.get("a2a_response_within_hours"):
        if not isinstance(probe, dict) or probe.get("state") != "a2a_response" or not _recent(probe.get("checked_at"), requirements["a2a_response_within_hours"], now):
            return False
    tls = agent.get("endpoint_tls") or {}
    if requirements.get("tls_reachable") and not (isinstance(tls, dict) and tls.get("reachable", tls.get("success")) is True):
        return False
    return True


def _unit_key(agent):
    """Hashable raw content; evidence is deliberately absent from this key."""
    units = [(None, "Agent declaration", ((str(agent.get("name") or ""), 16), (str(agent.get("description") or ""), 10)))]
    skills = agent.get("capabilities") or agent.get("skills") or _card(agent).get("skills") or []
    for index, skill in enumerate(skills):
        if not isinstance(skill, dict):
            continue
        tags = skill.get("tags") or []
        if not isinstance(tags, list):
            tags = [tags]
        identifier = skill.get("id", skill.get("skill_id", index))
        if not isinstance(identifier, (str, int, float, type(None))):
            identifier = str(identifier)
        units.append((identifier, str(skill.get("name") or "Declared capability")[:160],
                      ((str(skill.get("name") or ""), 22), (" ".join(str(tag) for tag in tags), 16),
                       (str(skill.get("description") or ""), 12))))
    return tuple(units)


@lru_cache(maxsize=4096)
def _features(key):
    """Cache immutable per-card semantic features across queries and refreshes."""
    units, all_words = [], set()
    for identifier, name, raw_fields in key:
        fields = tuple((_normalize_evidence(text), weight) for text, weight in raw_fields)
        normalized = " | ".join(text for text, _ in fields)
        concepts = _concepts(normalized)
        negatives = _negated_concepts(". ".join(text for text, _ in raw_fields))
        field_features = tuple((text, weight, _concepts(text), frozenset(text.split())) for text, weight in fields)
        all_words.update(normalized.split())
        units.append((identifier, name, field_features, concepts, negatives))
    global_negatives = units[0][4]
    positive_concepts = frozenset(c for _, _, _, concepts, negatives in units for c in concepts
                                  if c not in negatives and c not in global_negatives)
    return (tuple(units), positive_concepts, global_negatives, frozenset(all_words),
            frozenset(_BY_ID[c]["topic"] for c in positive_concepts))


def prepare_agents(agents):
    """Warm bounded content features while loading a caller's candidate cache.

    Returns the same collection without altering any row. Evidence is still
    evaluated on each search, so a stale semantic cache cannot bypass filters.
    """
    for agent in agents:
        if isinstance(agent, dict):
            _features(_unit_key(agent))
    return agents


def _relevance(agent, plan):
    query_concepts = {c["id"] for c in plan["concepts"]}
    terms = set(plan["meaningful_terms"])
    if not query_concepts and not terms:
        return None
    units, all_concepts, global_negatives, all_words, topics = _features(_unit_key(agent))
    if query_concepts and not any(_BY_ID[c]["topic"] in topics for c in query_concepts):
        return None
    if not query_concepts and len(terms & all_words) / max(len(terms), 1) < .4:
        return None
    direct, related, matched_capabilities = {}, {}, []
    term_weights = {}
    for identifier, name, fields, combined, negatives in units:
        unit_concepts = set()
        for text, weight, detected, words in fields:
            unit_concepts |= detected
            for concept_id in query_concepts:
                if concept_id in negatives or concept_id in global_negatives:
                    continue
                concept = _BY_ID[concept_id]
                if concept_id in detected:
                    direct[concept_id] = max(direct.get(concept_id, 0), weight)
                elif any(_BY_ID[c]["topic"] == concept["topic"] for c in detected):
                    target = direct if not concept["operation"] else related
                    target[concept_id] = max(target.get(concept_id, 0), weight)
            for term in terms:
                if term in words:
                    term_weights[term] = max(term_weights.get(term, 0), weight)
        relevant_ids = unit_concepts & query_concepts - negatives - global_negatives
        if relevant_ids or (not query_concepts and any(terms & words for _, _, _, words in fields)):
            matched_capabilities.append({"id": identifier, "name": name, "concepts": sorted(relevant_ids),
                                         "source": "agent_declaration" if identifier is None else "declared_skill"})

    # The combined-field concepts can detect aliases split between a skill's
    # name and its tags; credit them at description weight, never whole-card max.
    for identifier, name, fields, combined, negatives in units:
        for concept_id in query_concepts & combined:
            if concept_id in negatives or concept_id in global_negatives:
                continue
            direct[concept_id] = max(direct.get(concept_id, 0), 9)

    if query_concepts:
        # Same object with another explicit operation is not an adequate answer.
        # Generic topic declarations can be related matches, labelled as such.
        for cid in list(related):
            concept = _BY_ID[cid]
            if concept["operation"]:
                competitors = [c for c in all_concepts if _BY_ID[c]["topic"] == concept["topic"] and _BY_ID[c]["operation"]]
                if competitors and cid not in direct:
                    related.pop(cid, None)
        if not direct and not related:
            return None
        # Do not allow one generic overlapping word to rescue wrong intent.
        direct_count = len(direct)
        concept_coverage = (direct_count + .3 * len(set(related) - set(direct))) / len(query_concepts)
        score = 60 * concept_coverage + sum(direct.values()) / len(query_concepts)
        score += min(10, sum(term_weights.values()) / max(len(terms), 1) / 2)
        kind = "direct" if direct_count == len(query_concepts) else "related"
    else:
        # Unknown capabilities still work by meaningful whole words, with a
        # coverage floor; generic agent/service vocabulary cannot retrieve all.
        if not term_weights:
            return None
        coverage = len(term_weights) / max(len(terms), 1)
        if coverage < .4:
            return None
        score = 40 * coverage + sum(term_weights.values()) / len(terms)
        kind = "text"
    if plan["normalized"] and _normalize(agent.get("name")) == plan["normalized"]:
        score += 12
    reasons = []
    for cid in sorted(direct):
        reasons.append("Declared capability matches " + _BY_ID[cid]["label"] + ".")
    for cid in sorted(set(related) - set(direct)):
        reasons.append("Related " + _BY_ID[cid]["label"] + " declaration; the requested operation is not explicit.")
    if not query_concepts:
        reasons.append("Declared text matches: " + ", ".join(sorted(term_weights)) + ".")
    missing = query_concepts - set(direct) - set(related)
    caveats = ["No publisher task was executed; matching a declaration does not establish task quality."]
    if any(c["id"] == "email_sending" for c in plan.get("excluded_concepts", [])):
        caveats.append("Matches the declared validation operation; absence of outbound email was not tested.")
    if missing:
        caveats.append("Not all requested capabilities are declared: " + ", ".join(_BY_ID[c]["label"] for c in sorted(missing)) + ".")
    if authentication_state(agent) == "not_declared":
        caveats.append("Authentication is not declared; account-free access has not been verified.")
    if not (agent.get("price_offers") or agent.get("prices") or agent.get("price_summary")):
        caveats.append("No price evidence is included in this recommendation.")
    return {"score": round(score, 2), "capability_match": kind, "matched_capabilities": matched_capabilities[:8],
            "reasons": reasons, "caveats": caveats}


def _evidence_reasons(agent, requirements):
    reasons = []
    if requirements.get("auth") == "none":
        reasons.append("No authentication requirement is declared and the stored probe does not report authentication required.")
    if requirements.get("auth") == "declared":
        reasons.append("An authentication requirement is declared or was reported by the stored probe.")
    if requirements.get("signature"):
        reasons.append("Stored card signature verification passed.")
    if requirements.get("protocol"):
        reasons.append("Card declares " + requirements["protocol"] + " transport.")
    if requirements.get("checked_within_hours"):
        reasons.append("Card successfully checked within " + str(requirements["checked_within_hours"]) + " hours.")
    if requirements.get("a2a_response_within_hours"):
        reasons.append("Stored read-only A2A response confirmed within " + str(requirements["a2a_response_within_hours"]) + " hours.")
    if requirements.get("tls_reachable"):
        reasons.append("The latest stored endpoint TLS connection check passed.")
    return reasons


def rank_agents(agents, q, requirements=None, now=None):
    """Rank agent dictionaries using declarations, then evidence and diversity.

    Explicit nonempty filters override query constraints, with conflicts exposed.
    Every result passes those effective filters. Within 10-point relevance bands,
    a publisher gets two leading positions before its remaining results rotate
    behind other publishers. All matching results remain available to paginate.
    """
    now = _datetime(now) or datetime.now(timezone.utc)
    plan = interpret_query(q)
    effective, conflicts = _effective_requirements(plan, requirements)
    plan["conflicts"] = conflicts
    # A genuinely contradictory query needs correction rather than an arbitrary
    # selection. An explicit filter can resolve a conflict for that field.
    unresolved = [c for c in conflicts if "values" in c and not (requirements or {}).get(c["requirement"])]
    ranked = []
    if not unresolved:
        for agent in agents:
            if not isinstance(agent, dict) or not _meets(agent, effective, now):
                continue
            recommendation = _relevance(agent, plan)
            if recommendation is None:
                continue
            recommendation["reasons"].extend(_evidence_reasons(agent, effective))
            ranked.append(dict(agent, recommendation=recommendation))

    def evidence_key(item):
        signature = (item.get("signature_status") or (item.get("signature") or {}).get("status")) == "verified"
        recent = _datetime(item.get("last_verified"))
        age = max(0.0, (now - recent).total_seconds()) if recent else float("inf")
        identifier = item.get("id", "")
        stable_id = (0, int(identifier)) if str(identifier).isdigit() else (1, str(identifier))
        return (-item["recommendation"]["score"], -int(signature), age, stable_id)

    ranked.sort(key=evidence_key)
    # A round of at most two per publisher within a relevance band prevents a
    # bulk publisher filling a shortlist, while preserving stronger matches.
    bands = defaultdict(list)
    for item in ranked:
        bands[int(item["recommendation"]["score"] // 10)].append(item)
    result = []
    for band in sorted(bands, reverse=True):
        seen = Counter()
        staged = []
        for item in bands[band]:
            publisher = item.get("publisher_domain")
            if not publisher:
                publisher = urlsplit(str(item.get("card_url") or item.get("endpoint") or "")).hostname or str(item.get("id"))
            group_round = seen[publisher] // 2
            seen[publisher] += 1
            staged.append((group_round, item))
        staged.sort(key=lambda pair: pair[0])  # stable within each round
        result.extend(item for _, item in staged)
    return {"items": result, "total_matches": len(result), "interpreted_query": plan,
            "requirements": effective, "ranking_version": RANKING_VERSION, "scope": SCOPE}
