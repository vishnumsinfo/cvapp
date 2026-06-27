"""CV ingestion from external channels.

Channels:
  1. public_apply  -> a candidate (and their CV) submitted via your own careers
                      page / Meta-ad landing page. Fully built, no third party.
  2. url_download  -> pull a CV file from a direct URL (e.g. a link captured in a
                      Meta lead, an applicant tracking export, an email link).
  3. meta_ads      -> pull lead rows from a Meta lead-gen form. Meta leads give you
                      applicant *fields*; the CV file itself is usually a URL the
                      applicant uploaded, which we then fetch via url_download.
  4. portal        -> official employer APIs (Naukri RMS, Indeed, LinkedIn Talent).
                      These require a paid employer account + API key. We expose a
                      single adapter interface; plug your key in to activate.

IMPORTANT (read before enabling portals):
  Scraping job portals violates their terms of service and risks account bans.
  This module only uses official, authorized APIs. The portal adapter is a stub
  that you point at your real employer-API credentials.
"""
import os
import uuid
import urllib.request

UPLOAD_DIR = os.getenv("UPLOAD_DIR", "uploads")
ALLOWED_EXT = (".pdf", ".docx", ".doc")
MAX_BYTES = 10 * 1024 * 1024  # 10 MB cap per CV


class IngestError(Exception):
    pass


def _save_bytes(data: bytes, suggested_name: str) -> tuple[str, str]:
    """Persist raw bytes to the uploads dir. Returns (file_name, file_path)."""
    ext = os.path.splitext(suggested_name)[1].lower()
    if ext not in ALLOWED_EXT:
        raise IngestError(f"Unsupported CV type: {ext or 'unknown'}")
    if len(data) > MAX_BYTES:
        raise IngestError("CV exceeds 10 MB limit")
    safe = f"{uuid.uuid4().hex}{ext}"
    path = os.path.join(UPLOAD_DIR, safe)
    with open(path, "wb") as f:
        f.write(data)
    return suggested_name, path


def fetch_cv_from_url(url: str, suggested_name: str | None = None) -> tuple[str, str]:
    """Download a CV from a direct file URL (https only)."""
    if not url.lower().startswith("https://"):
        raise IngestError("CV URL must be https")
    name = suggested_name or os.path.basename(url.split("?")[0]) or "resume.pdf"
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "cv-screener/1.0"})
        with urllib.request.urlopen(req, timeout=30) as resp:  # noqa: S310 (https enforced)
            data = resp.read(MAX_BYTES + 1)
    except Exception as e:  # noqa: BLE001
        raise IngestError(f"Download failed: {e}") from e
    return _save_bytes(data, name)


# ---------------- Meta lead-gen ads ----------------
def pull_meta_leads(form_id: str, access_token: str) -> list[dict]:
    """Pull lead rows from a Meta lead-gen form via the Graph API.

    Returns a list of normalized dicts:
      {"full_name","email","phone","cv_url"(optional)}

    Note: Meta lead ads capture form fields. If your form has a file/URL field for
    the CV, it arrives as a link we then download. If applicants upload on your
    landing page instead, use the public_apply endpoint and skip this.
    """
    if not access_token:
        raise IngestError("META_ACCESS_TOKEN not set")
    import json
    url = (
        f"https://graph.facebook.com/v21.0/{form_id}/leads"
        f"?access_token={access_token}"
    )
    try:
        with urllib.request.urlopen(url, timeout=30) as resp:  # noqa: S310
            payload = json.loads(resp.read())
    except Exception as e:  # noqa: BLE001
        raise IngestError(f"Meta API error: {e}") from e

    leads = []
    for row in payload.get("data", []):
        fields = {f["name"]: (f.get("values") or [""])[0]
                  for f in row.get("field_data", [])}
        leads.append({
            "full_name": fields.get("full_name") or fields.get("name", ""),
            "email": fields.get("email", ""),
            "phone": fields.get("phone_number") or fields.get("phone", ""),
            "cv_url": fields.get("cv") or fields.get("resume") or fields.get("resume_url"),
        })
    return leads


# ---------------- Portal adapter (official APIs only) ----------------
def pull_portal_applicants(provider: str, job_ref: str) -> list[dict]:
    """Adapter for official employer ATS/portal APIs.

    provider: "naukri" | "indeed" | "linkedin"
    Returns normalized dicts like pull_meta_leads.

    This is intentionally a stub: each provider needs your paid employer account
    and API credentials. Wire the real call where indicated. We do NOT scrape.
    """
    key = os.getenv(f"{provider.upper()}_API_KEY")
    if not key:
        raise IngestError(
            f"{provider} not configured. Set {provider.upper()}_API_KEY and "
            f"implement the official API call. Scraping is not supported."
        )
    # --- Plug official provider API call here, return normalized rows. ---
    raise IngestError(f"{provider} adapter not yet implemented for this account")
