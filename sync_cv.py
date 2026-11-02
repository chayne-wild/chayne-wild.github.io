cat << 'EOF' > ~/chayne-wild.github.io/sync_cv.py
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
    return y.group(1) if y else ""


def strip_html(text: str) -> str:
    text = re.sub(r"<[^>]+>", "", text)
    text = text.replace("“", '"').replace("”", '"').replace("’", "'")
    return re.sub(r"\s+", " ", text).strip().lower()


def is_same_entry(pdf_block: str, json_text: str, threshold: float = 0.65) -> bool:
    a = strip_html(pdf_block)
    b = strip_html(json_text)
    if not a or not b:
        return False
    if b in a or a in b:
        return True
    return SequenceMatcher(None, a, b).ratio() >= threshold


def extract_pdf_sections(pdf_path: Path) -> dict:
    reader = PdfReader(str(pdf_path))
    full_text = "\n".join(page.extract_text() or "" for page in reader.pages)

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

    pattern = r"(?:^|\n)\s*(" + "|".join(re.escape(h) for h in headings) + r")\s*(?=\n|$)"
    parts = re.split(pattern, full_text)

    sections = {}
    for i in range(1, len(parts), 2):
        sec_name = parts[i].strip()
        sec_body = parts[i + 1].strip() if i + 1 < len(parts) else ""
        sections[sec_name] = sec_body

    return sections


def split_blocks(section_text: str) -> list:
    lines = [line.strip() for line in section_text.splitlines()]
    blocks = []
    current = []

    for line in lines:
        if not line:
            if current:
                blocks.append(" ".join(current))
                current = []
        else:
            if current and (
                line.startswith(('"', "“", "Review of ", "Wild, Chayne"))
                and current[-1].endswith((".", ")", '"', "”"))
            ):
                blocks.append(" ".join(current))
                current = [line]
            else:
                current.append(line)

    if current:
        blocks.append(" ".join(current))
    return blocks


def sync_research_interests(ri_text: str, data: dict):
    flat_text = re.sub(r"\s+", " ", ri_text).strip()
    pattern = r"(?:^|(?<=\.\s))([^.:]{3,120}?):\s*(.+?)(?=(?:\.\s+[^.:]{3,120}?:)|$)"
    matches = re.findall(pattern, flat_text)

    new_interests = []
    for title, desc in matches:
        clean_desc = desc.strip()
        if not clean_desc.endswith("."):
            clean_desc += "."
        new_interests.append({
            "title": title.strip(),
            "description": clean_desc
        })

    if new_interests and new_interests != data.get("researchInterests"):
        print("\n✨ [Research Interests] Updated from CV:")
        for item in new_interests:
            print(f"  • {item['title']}: {item['description'][:65]}...")
        data["researchInterests"] = new_interests


def sync_education(edu_text: str, data: dict) -> list:
    new_news_suggestions = []
    phd = data["education"][0]

    def_match = re.search(r"\(Target Defense:\s*([^)]+)\)", edu_text, re.IGNORECASE)
    if def_match:
        new_def_date = def_match.group(1).strip()
        expected_str = f"Target Defense: {new_def_date}"
        if phd.get("date") != expected_str:
            print(f"\n✨ [Education] Updated Ph.D. Target Defense: '{phd.get('date')}' -> '{expected_str}'")
            phd["date"] = expected_str
            new_news_suggestions.append(
                (new_def_date, f"Target defense for Ph.D. dissertation, <em>{phd['thesisTitle']}</em>.")
            )

    diss_match = re.search(r"Dissertation:\s*(.+?)(?=\n|Committee:)", edu_text, re.DOTALL)
    if diss_match:
        new_title = re.sub(r"\s+", " ", diss_match.group(1)).strip()
        if phd.get("thesisTitle") != new_title:
            print(f"\n✨ [Education] Updated Dissertation Title:\n  Old: {phd.get('thesisTitle')}\n  New: {new_title}")
            phd["thesisTitle"] = new_title

    return new_news_suggestions


def sync_publications(pub_text: str, data: dict) -> list:
    blocks = split_blocks(pub_text)
    existing_pubs = data.get("publications", [])
    updated_pubs = []
    new_news_suggestions = []

    for block in blocks:
        matched = None
        for pub in existing_pubs:
            combined_json = f"{pub.get('titleHtml', '')} {pub.get('authorsHtml', '')}"
            if is_same_entry(block, combined_json):
                matched = pub
                break

        if matched:
            updated_pubs.append(matched)
        else:
            print(f"\n✨ [New Publication Detected in CV]:\n  {block}")
            pub_type = input("  Badge Type (e.g., Peer-Reviewed Article, Book Review, Computational Software) [Publication]: ").strip() or "Publication"
            default_date = extract_date_from_text(block) or "2026"
            pub_year = input(f"  Publication Date/Year [{default_date}]: ").strip() or default_date

            url_match = re.search(r"(https?://\S+)", block)
            default_url = url_match.group(1).rstrip(".") if url_match else ""
            url = input(f"  External Link URL [{default_url or 'Enter to skip'}]: ").strip() or default_url

            links = []
            if url:
                label = "Code & Repository" if "github.com" in url else "Publication Link"
                icon = "fa-brands fa-github" if "github.com" in url else "fa-solid fa-arrow-up-right-from-square"
                links.append({"label": label, "url": url, "icon": icon})

            clean_title = re.sub(r"https?://\S+", "", block).strip()
            new_entry = {
                "type": pub_type,
                "badgeClass": "badge-software" if "software" in pub_type.lower() else "",
                "year": pub_year,
                "titleHtml": clean_title,
                "authorsHtml": "Wild, Chayne.",
                "citation": block,
                "links": links,
            }
            updated_pubs.append(new_entry)
            new_news_suggestions.append((pub_year, f"New {pub_type.lower()} published: {clean_title}"))

    for pub in existing_pubs:
        if pub not in updated_pubs:
            keep = input(f"\n⚠️ Existing publication not found in PDF: '{strip_html(pub['titleHtml'])[:60]}...'\n  Keep it on the website anyway? [Y/n]: ").strip().lower()
            if keep != "n":
                updated_pubs.append(pub)

    data["publications"] = sort_chronologically(updated_pubs, lambda item: item.get("year", ""))
    return new_news_suggestions


def sync_manuscripts(ms_text: str, data: dict):
    blocks = split_blocks(ms_text)
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
            print(f"\n✨ [New Manuscript in Prep Detected in CV]:\n  {block}")
            m = re.match(r'^([“"][^”"]+[”"])\s*(.*)$', block)
            title = m.group(1) if m else block
            rest = m.group(2) if m else ""
            updated_ms.append({"title": title, "venueHtml": rest})

    if updated_ms:
        data["manuscripts"] = updated_ms


def sync_presentations(pres_text: str, data: dict) -> list:
    blocks = split_blocks(pres_text)
    existing_pres = data.get("presentations", [])
    updated_pres = []
    new_news_suggestions = []

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
            print(f"\n✨ [New Conference Presentation Detected in CV]:\n  {block}")
            m = re.match(r'^([“"][^”"]+[”"])\s*(.*)$', block)
            if m:
                title, details = m.group(1), m.group(2)
            else:
                title, details = block, ""

            new_entry = {"title": title, "detailsHtml": details}
            updated_pres.append(new_entry)
            pres_date = extract_date_from_text(block) or "Upcoming"
            new_news_suggestions.append((pres_date, f"Presenting {title} at {details}"))

    data["presentations"] = sort_chronologically(
        updated_pres, lambda item: extract_date_from_text(item.get("detailsHtml", ""))
    )
    return new_news_suggestions


def review_news_interactively(data: dict, suggestions: list):
    print("\n" + "=" * 65)
    print(" 🔔 VERIFY 'RECENT & UPCOMING' (NEWS) SECTION")
    print("=" * 65)

    news_list = data.get("news", [])

    for suggested_date, suggested_text in suggestions:
        print(f"\nSuggested update from CV changes:\n  [{suggested_date}] {suggested_text}")
        ans = input("  Add this to 'Recent & Upcoming'? [y/N]: ").strip().lower()
        if ans == "y":
            custom_date = input(f"  Date label [{suggested_date}]: ").strip() or suggested_date
            custom_text = input(f"  Text [{suggested_text}]: ").strip() or suggested_text
            news_list.insert(0, {"date": custom_date, "text": custom_text})

    verified_news = []
    print("\nReviewing current 'Recent & Upcoming' items:")
    for idx, item in enumerate(news_list, start=1):
        print(f"\n  {idx}. [{item['date']}] {item['text']}")
        choice = input("     Action -> [K]eep (Enter), [E]dit, or [D]elete? ").strip().lower()
        if choice == "d":
            print("     ✗ Removed.")
            continue
        elif choice == "e":
            new_date = input(f"     New date [{item['date']}]: ").strip() or item["date"]
            new_text = input(f"     New text [{item['text']}]: ").strip() or item["text"]
            verified_news.append({"date": new_date, "text": new_text})
            print("     ✓ Updated.")
        else:
            verified_news.append(item)

    while True:
        add_more = input("\nAdd a custom 'Recent & Upcoming' item? [y/N]: ").strip().lower()
        if add_more != "y":
            break
        n_date = input("  Date (e.g., Spring 2027, December 2026): ").strip()
        n_text = input("  Description (HTML like <em>Title</em> allowed): ").strip()
        if n_date and n_text:
            verified_news.append({"date": n_date, "text": n_text})

    data["news"] = sort_chronologically(verified_news, lambda item: item.get("date", ""))


def main():
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

    suggestions = []

    if "RESEARCH INTERESTS" in sections:
        sync_research_interests(sections["RESEARCH INTERESTS"], data)

    if "EDUCATION" in sections:
        suggestions.extend(sync_education(sections["EDUCATION"], data))

    if "RESEARCH & PUBLICATIONS" in sections:
        suggestions.extend(sync_publications(sections["RESEARCH & PUBLICATIONS"], data))

    if "MANUSCRIPTS IN PREPARATION" in sections:
        sync_manuscripts(sections["MANUSCRIPTS IN PREPARATION"], data)

    if "CONFERENCE PRESENTATIONS" in sections:
        suggestions.extend(sync_presentations(sections["CONFERENCE PRESENTATIONS"], data))

    review_news_interactively(data, suggestions)

    with open(JSON_PATH, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)

    print(f"\n✅ Successfully synced and sorted {JSON_PATH} (Newest/Forthcoming -> Oldest)!")


if __name__ == "__main__":
    main()
EOF
