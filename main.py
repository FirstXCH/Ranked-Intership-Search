import requests
from bs4 import BeautifulSoup
from dataclasses import dataclass
from typing import List, Dict, Optional
import json
import re


@dataclass
class Job:
    title: str
    company: str
    location: str
    url: str
    salary: Optional[str] = None
    source: str = "unknown"


def fetch_html(url: str, headers: Optional[Dict[str, str]] = None) -> str:
    headers = headers or {"User-Agent": "Mozilla/5.0"}
    response = requests.get(url, headers=headers, timeout=20)
    response.raise_for_status()
    return response.text


def clean_text(node) -> str:
    if node is None:
        return ""
    return " ".join(node.get_text(" ", strip=True).split())


def normalize_url(href: str, base_url: str) -> str:
    if not href:
        return ""
    if href.startswith("http"):
        return href
    return base_url.rstrip("/") + "/" + href.lstrip("/")


def parse_jobs_from_next_data(html: str, config: Dict) -> List[Job]:
    key_prefix = config.get("next_data_search_key_prefix", "")
    if not key_prefix:
        return []

    match = re.search(
        r'<script id="__NEXT_DATA__" type="application/json" crossorigin="anonymous">(.*?)</script>',
        html,
    )
    if not match:
        return []

    payload = json.loads(match.group(1))
    root_query = (
        payload.get("props", {})
        .get("apolloState", {})
        .get("ROOT_QUERY", {})
    )

    search_key = next((key for key in root_query if key.startswith(key_prefix)), None)
    if not search_key:
        return []

    entries = (
        root_query.get(search_key, {})
        .get("data", {})
        .get("data", [])
    )
    if not isinstance(entries, list):
        return []

    jobs: List[Job] = []
    for entry in entries:
        title = str(entry.get("jobTitle", "")).strip()
        if not title:
            continue

        company = str(entry.get("companyName", "")).strip()
        province = str((entry.get("province") or {}).get("name", "")).strip()
        district = str((entry.get("district") or {}).get("name", "")).strip()
        location = " ".join(part for part in [district, province] if part)
        salary = str(entry.get("salary", "")).strip() or None

        job_id = entry.get("id")
        job_url = ""
        if job_id:
            detail_path = config.get("job_detail_path_template", "/th/job/{id}").format(id=job_id)
            job_url = normalize_url(detail_path, config["base_url"])

        jobs.append(Job(
            title=title,
            company=company,
            location=location,
            url=job_url,
            salary=salary,
            source=config["source_name"],
        ))

    return jobs


def parse_jobs_from_html(html: str, config: Dict) -> List[Job]:
    next_data_jobs = parse_jobs_from_next_data(html, config)
    if next_data_jobs:
        return next_data_jobs

    soup = BeautifulSoup(html, "html.parser")
    cards = []
    selectors = config.get("card_selectors") or [config.get("card_selector", "")]
    for selector in selectors:
        if not selector:
            continue
        cards = soup.select(selector)
        if cards:
            break

    if not cards:
        print(f"[{config['source_name']}] No job cards were found. The page may render jobs with JavaScript.")
        return []

    jobs: List[Job] = []
    for card in cards:
        title_el = card.select_one(config.get("title_selector", "a[href]"))
        company_el = card.select_one(config.get("company_selector", ""))
        location_el = card.select_one(config.get("location_selector", ""))
        link_el = card.select_one(config.get("link_selector", "a[href]"))

        title = clean_text(title_el)
        if not title:
            continue

        company = clean_text(company_el)
        location = clean_text(location_el)
        url = normalize_url(link_el.get("href") if link_el else "", config["base_url"])

        jobs.append(Job(
            title=title,
            company=company,
            location=location,
            url=url,
            source=config["source_name"],
        ))

    return jobs


JOBTHAI_CONFIG = {
    "source_name": "jobthai",
    "base_url": "https://www.jobthai.com",
    "next_data_search_key_prefix": "searchJobs(",
    "job_detail_path_template": "/th/job/{id}",
    "card_selectors": [
        ".job-item",
        ".job-card",
        "article",
        "[data-job-id]",
        ".job-list-item",
    ],
    "title_selector": "a[href]",
    "company_selector": ".company-name, .company, .job-company",
    "location_selector": ".location, .job-location, .job-area",
    "link_selector": "a[href]",
}


def main():
    url = "https://www.jobthai.com/th/jobs?jobtype=7&subjobtype=52"
    html = fetch_html(url)
    jobs = parse_jobs_from_html(html, JOBTHAI_CONFIG)

    print(f"Found {len(jobs)} jobs")
    for job in jobs[:10]:
        print(job.title, "|", job.company, "|", job.location)
        print(job.url)


if __name__ == "__main__":
    main()
