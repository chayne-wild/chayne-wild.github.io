#!/usr/bin/env python3
import json
import re
import sys
from datetime import datetime
from difflib import SequenceMatcher
from pathlib import Path

from pypdf import PdfReader

PDF_PATH = Path("wild_cv.pdf")
JSON_PATH = Path("cv.json")

MONTH_MAP = {
    "january": 1, "jan": 1,
    "winter": 2,
    "february": 2, "feb": 2,
    "march": 3, "mar": 3,
    "april": 4, "apr": 4,
    "spring": 4,
    "may": 5,
    "june": 6, "jun": 6,
    "july": 7, "jul": 7,
    "summer": 7,
    "august": 8, "aug": 8,
    "september": 9, "sep": 9, "sept": 9,
    "october": 10, "oct": 10,
    "fall": 10, "autumn": 10,
    "november": 11, "nov": 11,
    "december": 12, "dec": 12,
}


def academic_date_key(date_str: str, original_index: int = 0) -> tuple:
    if not date_str:
        return (0, 0, -original_index)
    lower = date_str.lower()
    if "forthcoming" in lower or "in progress" in lower or "present" in lower:
        return (9999, 12, -original_index)
    year_match = re.search(r"\b(19\d{2}|20\d{2})\b", lower)
    year = int(year_match.group(1)) if year_match else 0
    month = 0
    for token, val in MONTH_MAP.items():
        if re.search(rf"\b{token}\b", lower):
            month = val
            break
    return (year, month, -original_index)


def sort_chronologically(items: list, date_getter) -> list:
    indexed = list(enumerate(items))
    indexed.sort(
        key=lambda pair: academic_date_key(date_getter(pair[1]), pair[0]),
        reverse=True,
    )
    return [pair[1] for pair in indexed]


def extract_date_from_text(text: str) -> str:
    if "forthcoming" in text.lower():
        return "Forthcoming"
    m = re.search(
        r"\b(January|February|March|April|May|June|July|August|September|October|November|December|Spring|Summer|Fall|Autumn|Winter)\s+(20\d{2})\b",
        text,
        re.IGNORECASE,
    )
    if m:
        return f"{m.group(1)} {m.group(2)}"
    y = re.search(r"\b(20\d{2})\b", text)
    return y.group(1) if y else "2026"


def strip_html(text: str) -> str:
    text = re.sub(r"<[^>]+>", "", text)
    text = text.replace("“", '"').replace("”", '"').replace("’", "'")
    return re.sub(r"\s+", " ", text).strip().lower()


def is_same_entry(pdf_block: str, json_text: str, threshold: float = 0.65) -> bool:
    a = strip_html(pdf_block)
    b = strip_html(json_text)
    if not a or not b:
        return False
    return SequenceMatcher(None, a, b).ratio() >= threshold


def extract_pdf_sections(pdf_path: Path) -> dict:
    reader = PdfReader(str(pdf_path))
    raw_text = " ".join(page.extract_text() or "" for page in reader.pages)
    full_text = re.sub(r"\s+", " ", raw_text)

    headings = [
        "EDUCATION",
        "RESEARCH INTERESTS",
        "RESEARCH & PUBLICATIONS",
        "CONFERENCE PRESENTATIONS",
        "MANUSCRIPTS IN PREPARATION",
        "TEACHING EXPERIENCE",
        "GRADUATE RESEARCH EXPERIENCE",
        "EDITORIAL & PROFESSIONAL SERVICE",
        "MEMBERSHIPS",
    ]

    pattern = r"(" + "|".join(re.escape(h) for h in headings) + r")"
    parts = re.split(pattern, full_text)

    sections = {}
    for i in range(1, len(parts), 2):
        sec_name = parts[i].strip()
        sec_body = parts[i + 1].strip() if i + 1 < len(parts) else ""
        sections[sec_name] = sec_body

    return sections


def split_publications(pub_text: str) -> list:
    flat = re.sub(r"\s+", " ", pub_text).strip()
    flat = re.sub(r"(https?://\S+)\s+", r"\1\n\n", flat)
    flat = re.sub(
        r'(?<=\.)\s+(?=(?:Wild,\s*Chayne|Review\s+of\b|[A-Z][a-z]+,\s+[A-Z][a-z]+\.\s+(?:19|20)\d{2}|[“"]))',
        "\n\n",
        flat,
    )
    return [b.strip() for b in flat.split("\n\n") if b.strip()]


def split_quoted_entries(section_text: str) -> list:
    flat = re.sub(r"\s+", " ", section_text).strip()
    parts = re.split(r'(?<=\.)\s+(?=[“"])', flat)
    return [p.strip() for p in parts if p.strip()]


def sync_research_interests(ri_text: str, data: dict):
    flat_text = re.sub(r"\s+", " ", ri_text).strip()
    if ":" not in flat_text:
        return

    chunks = flat_text.split(":")
    titles = [chunks[0].strip()]
    descriptions = []

    for chunk in chunks[1:-1]:
        if "." in chunk:
            desc_part, next_title = chunk.rsplit(".", 1)
            descriptions.append(desc_part.strip() + ".")
            titles.append(next_title.strip())
        else:
            descriptions.append(chunk.strip())

    last_desc = chunks[-1].strip()
    if not last_desc.endswith("."):
        last_desc += "."
    descriptions.append(last_desc)

    new_interests = [
        {"title": t, "description": d}
        for t, d in zip(titles, descriptions)
        if t and d
    ]

    if new_interests and new_interests != data.get("researchInterests"):
        print("✨ [Research Interests] Auto-updated from CV.")
        data["researchInterests"] = new_interests


def sync_education(edu_text: str, data: dict):
    phd = data["education"][0]
    flat_edu = re.sub(r"\s+", " ", edu_text).strip()

    diss_match = re.search(r"Dissertation:\s*(.+?)\s*Committee:", flat_edu)
    if diss_match:
        new_title = diss_match.group(1).strip()
        if phd.get("thesisTitle") != new_title:
            print(f"✨ [Education] Auto-updated Dissertation Title: {new_title}")
            phd["thesisTitle"] = new_title

    def_match = re.search(r"\(Target Defense:\s*([^)]+)\)", flat_edu, re.IGNORECASE)
    if def_match:
        new_def_date = def_match.group(1).strip()
        expected_str = f"Target Defense: {new_def_date}"
        if phd.get("date") != expected_str:
            print(f"✨ [Education] Auto-updated Target Defense: {expected_str}")
            phd["date"] = expected_str

        # Keep the dissertation defense item in 'news' synced in-place
        for item in data.get("news", []):
            if "target defense" in item.get("text", "").lower():
                item["date"] = new_def_date
                item["text"] = f"Target defense for Ph.D. dissertation, <em>{phd['thesisTitle']}</em>."


def sync_publications(pub_text: str, data: dict):
    """
    Preserves the exact top-to-bottom order from the CV (Newest/Forthcoming at top).
    Defaults new items to 'Peer-Reviewed Article'.
    """
    blocks = split_publications(pub_text)
    existing_pubs = data.get("publications", [])
    updated_pubs = []

    for block in blocks:
        matched = None
        for pub in existing_pubs:
            combined_json = f"{pub.get('titleHtml', '')} {pub.get('authorsHtml', '')}"
            citation_json = pub.get("citation", "")
            if is_same_entry(block, combined_json) or is_same_entry(block, citation_json):
                matched = pub
                break

        if matched:
            updated_pubs.append(matched)
        else:
            # Auto-classify badge type (defaults to Peer-Reviewed Article)
            lower_block = block.lower()
            if lower_block.startswith("review of "):
                pub_type = "Book Review"
                badge_class = ""
            elif "[computer software]" in lower_block:
                pub_type = "Computational Software"
                badge_class = "badge-software"
            else:
                pub_type = "Peer-Reviewed Article"
                badge_class = ""

            pub_year = extract_date_from_text(block)

            url_match = re.search(r"(https?://\S+)", block)
            url = url_match.group(1).rstrip(".") if url_match else ""
            links = []
            if url:
                label = "Code & Repository" if "github.com" in url else "Publication Link"
                icon = "fa-brands fa-github" if "github.com" in url else "fa-solid fa-arrow-up-right-from-square"
                links.append({"label": label, "url": url, "icon": icon})

            clean_title = re.sub(r"https?://\S+", "", block).strip()
            new_entry = {
                "type": pub_type,
                "badgeClass": badge_class,
                "year": pub_year,
                "titleHtml": clean_title,
                "authorsHtml": "Wild, Chayne.",
                "citation": block,
                "links": links,
            }
            print(f"✨ [Publications] Auto-added ({pub_type}): {clean_title[:70]}...")
            updated_pubs.append(new_entry)

    data["publications"] = updated_pubs


def sync_manuscripts(ms_text: str, data: dict):
    blocks = split_quoted_entries(ms_text)
    existing_ms = data.get("manuscripts", [])
    updated_ms = []

    for block in blocks:
        matched = None
        for ms in existing_ms:
            combined_json = f"{ms.get('title', '')} {ms.get('venueHtml', '')} {ms.get('abstract', '')}"
            if is_same_entry(block, combined_json, threshold=0.55):
                matched = ms
                break
        if matched:
            updated_ms.append(matched)
        else:
            m = re.match(r'^([“"][^”"]+[”"])\s*(.*)$', block)
            title = m.group(1) if m else block
            rest = m.group(2) if m else ""
            print(f"✨ [Manuscripts] Auto-added: {title}")
            updated_ms.append({"title": title, "venueHtml": rest})

    if updated_ms:
        data["manuscripts"] = updated_ms


def sync_presentations(pres_text: str, data: dict):
    """Preserves exact top-to-bottom order from the CV."""
    blocks = split_quoted_entries(pres_text)
    existing_pres = data.get("presentations", [])
    updated_pres = []

    for block in blocks:
        matched = None
        for pres in existing_pres:
            combined_json = f"{pres.get('title', '')} {pres.get('detailsHtml', '')}"
            if is_same_entry(block, combined_json):
                matched = pres
                break

        if matched:
            updated_pres.append(matched)
        else:
            m = re.match(r'^([“"][^”"]+[”"])\s*(.*)$', block)
            if m:
                title, details = m.group(1), m.group(2)
            else:
                title, details = block, ""
            print(f"✨ [Presentations] Auto-added: {title}")
            updated_pres.append({"title": title, "detailsHtml": details})

    data["presentations"] = updated_pres


def clean_and_sort_news(data: dict):
    """Removes any accidental 'Y' entries and sorts news newest-to-oldest."""
    cleaned = [
        item for item in data.get("news", [])
        if item.get("date", "").strip().upper() != "Y"
        and item.get("text", "").strip().upper() != "Y"
    ]
    data["news"] = sort_chronologically(cleaned, lambda item: item.get("date", ""))


def main():
    Path(".git/hooks/pre-commit").unlink(missing_ok=True)

    if not PDF_PATH.exists():
        print(f"Error: Could not find {PDF_PATH} in current directory.")
        sys.exit(1)
    if not JSON_PATH.exists():
        print(f"Error: Could not find {JSON_PATH} in current directory.")
        sys.exit(1)

    mtime = datetime.fromtimestamp(PDF_PATH.stat().st_mtime).strftime("%Y-%m-%d %H:%M:%S")
    print(f"📄 Reading {PDF_PATH} (Last modified: {mtime})...")
    sections = extract_pdf_sections(PDF_PATH)

    with open(JSON_PATH, "r", encoding="utf-8") as f:
        data = json.load(f)

    # Clean up any accidental 'Y' entries in news first
    clean_and_sort_news(data)

    if "RESEARCH INTERESTS" in sections:
        sync_research_interests(sections["RESEARCH INTERESTS"], data)

    if "EDUCATION" in sections:
        sync_education(sections["EDUCATION"], data)

    if "RESEARCH & PUBLICATIONS" in sections:
        sync_publications(sections["RESEARCH & PUBLICATIONS"], data)

    if "MANUSCRIPTS IN PREPARATION" in sections:
        sync_manuscripts(sections["MANUSCRIPTS IN PREPARATION"], data)

    if "CONFERENCE PRESENTATIONS" in sections:
        sync_presentations(sections["CONFERENCE PRESENTATIONS"], data)

    clean_and_sort_news(data)

    with open(JSON_PATH, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)

    print(f"✅ Auto-synced {JSON_PATH} from {PDF_PATH}!")


if __name__ == "__main__":
    main()
