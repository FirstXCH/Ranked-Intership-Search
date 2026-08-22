from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional
import json
import re

import pandas as pd
import requests
from bs4 import BeautifulSoup


@dataclass
class Job:
    id: int
    title: str
    company: str
    location: str
    province_id: str
    url: str
    salary: Optional[str] = None
    source: str = "unknown"
    updated_at: Optional[str] = None
    description: str = ""
    benefits: str = ""


def fetch_html(url: str, headers: Optional[Dict[str, str]] = None) -> str:
    headers = headers or {"User-Agent": "Mozilla/5.0"}
    response = requests.get(url, headers=headers, timeout=20)
    response.raise_for_status()
    return response.text


def normalize_url(href: str, base_url: str) -> str:
    if not href:
        return ""
    if href.startswith("http"):
        return href
    return base_url.rstrip("/") + "/" + href.lstrip("/")


def html_to_text(value: Optional[str]) -> str:
    if not value:
        return ""
    return " ".join(BeautifulSoup(value, "html.parser").get_text(" ", strip=True).split())


def extract_next_data_payload(html: str) -> Dict:
    match = re.search(
        r'<script id="__NEXT_DATA__" type="application/json" crossorigin="anonymous">(.*?)</script>',
        html,
    )
    if not match:
        raise ValueError("Could not find __NEXT_DATA__ payload in HTML.")
    return json.loads(match.group(1))


def parse_jobs_from_search_next_data(html: str, config: Dict) -> List[Job]:
    payload = extract_next_data_payload(html)
    root_query = payload.get("props", {}).get("apolloState", {}).get("ROOT_QUERY", {})

    key_prefix = config["next_data_search_key_prefix"]
    search_key = next((key for key in root_query if key.startswith(key_prefix)), None)
    if not search_key:
        raise ValueError(f"Could not find search key prefix '{key_prefix}' in ROOT_QUERY.")

    entries = root_query.get(search_key, {}).get("data", {}).get("data", [])
    if not isinstance(entries, list):
        raise ValueError("Search payload exists but 'data.data' is not a list.")

    jobs: List[Job] = []
    for entry in entries:
        title = str(entry.get("jobTitle", "")).strip()
        if not title:
            continue

        district_raw = (entry.get("district") or {}).get("name")
        province_raw = (entry.get("province") or {}).get("name")
        district = str(district_raw or "").strip()
        province = str(province_raw or "").strip()
        province_id = str((entry.get("province") or {}).get("id", "")).strip()
        location = " ".join(part for part in [district, province] if part)

        job_id = int(entry.get("id"))
        detail_path = config["job_detail_path_template"].format(id=job_id)
        job_url = normalize_url(detail_path, config["base_url"])

        jobs.append(
            Job(
                id=job_id,
                title=title,
                company=str(entry.get("companyName", "")).strip(),
                location=location,
                province_id=province_id,
                url=job_url,
                salary=str(entry.get("salary", "")).strip() or None,
                source=config["source_name"],
                updated_at=str(entry.get("updatedAt", "")).strip() or None,
            )
        )

    return jobs


def parse_job_detail_next_data(html: str, job_url: str, config: Dict) -> Dict[str, str]:
    payload = extract_next_data_payload(html)
    root_query = payload.get("props", {}).get("apolloState", {}).get("ROOT_QUERY", {})

    key_prefix = config["next_data_detail_key_prefix"]
    detail_key = next((key for key in root_query if key.startswith(key_prefix)), None)
    if not detail_key:
        raise ValueError(f"Could not find detail key prefix '{key_prefix}' for {job_url}")

    data = root_query.get(detail_key, {}).get("data", {})
    if not isinstance(data, dict):
        raise ValueError(f"Detail payload for {job_url} is not a dict.")

    return {
        "description": html_to_text(data.get("description")),
        "benefits": html_to_text(data.get("benefit")),
        "updated_at": str(data.get("updatedAt", "")).strip(),
    }


def enrich_jobs_with_details(jobs: List[Job], config: Dict) -> None:
    for job in jobs:
        try:
            detail_html = fetch_html(job.url)
            detail = parse_job_detail_next_data(detail_html, job.url, config)
            job.description = detail["description"]
            job.benefits = detail["benefits"]
            if detail["updated_at"]:
                job.updated_at = detail["updated_at"]
        except requests.RequestException as error:
            print(f"[warn] Failed to fetch detail URL: {job.url} ({error})")
        except (ValueError, json.JSONDecodeError) as error:
            print(f"[warn] Failed to parse detail payload: {job.url} ({error})")


def jobs_to_dataframe(jobs: List[Job]) -> pd.DataFrame:
    return pd.DataFrame(asdict(job) for job in jobs)


PROVINCE_ID_BY_NAME = {
    "ขอนแก่น": "06",
}


def filter_base_dataframe(df: pd.DataFrame, target_location: str) -> pd.DataFrame:
    target = target_location.strip()
    province_id = PROVINCE_ID_BY_NAME.get(target)
    if province_id:
        location_mask = df["province_id"].fillna("").eq(province_id)
    else:
        location_mask = df["location"].fillna("").str.contains(target, case=False, regex=False)

    tech_keywords = [
        "software",
        "developer",
        "programmer",
        "data",
        "it",
        "network",
        "cloud",
        "system",
        "web",
        "backend",
        "frontend",
        "full stack",
        "ai",
        "machine learning",
        "คอมพิวเตอร์",
        "โปรแกรม",
        "ไอที",
        "ดาต้า",
    ]
    title_text = df["title"].fillna("").str.lower()
    tech_mask = pd.Series(False, index=df.index)
    for keyword in tech_keywords:
        tech_mask = tech_mask | title_text.str.contains(keyword.lower(), regex=False)

    return df[location_mask & tech_mask].copy()


def score_custom_keywords(df: pd.DataFrame, custom_keywords: List[str]) -> pd.DataFrame:
    normalized_keywords = [kw.strip() for kw in custom_keywords if kw.strip()]
    combined_text = (
        df["description"].fillna("")
        + " "
        + df["benefits"].fillna("")
        + " "
        + df["title"].fillna("")
    ).str.lower()

    def score_row(text: str) -> int:
        return sum(1 for kw in normalized_keywords if kw.lower() in text)

    df["Custom_Keyword_Score"] = combined_text.apply(score_row)
    return df


def add_recency_columns(df: pd.DataFrame) -> pd.DataFrame:
    now_utc = datetime.now(timezone.utc)
    parsed = pd.to_datetime(df["updated_at"], errors="coerce", utc=True)
    df["Posted_At"] = parsed
    df["Days_Ago"] = (now_utc - parsed).dt.days
    return df


def run_pipeline(search_url: str, config: Dict, custom_keywords: List[str], target_location: str) -> None:
    output_dir = Path("outputs")
    output_dir.mkdir(parents=True, exist_ok=True)
    raw_csv_path = output_dir / "raw_internships.csv"
    scored_all_csv_path = output_dir / "scored_all_internships.csv"
    ranked_csv_path = output_dir / "ranked_khonkaen_internships.csv"

    print("[phase 1] Extracting search page...")
    search_html = fetch_html(search_url)
    jobs = parse_jobs_from_search_next_data(search_html, config)

    print(f"[phase 1] Found {len(jobs)} jobs in search payload. Enriching details...")
    enrich_jobs_with_details(jobs, config)

    raw_df = jobs_to_dataframe(jobs)
    raw_df.to_csv(raw_csv_path, index=False, encoding="utf-8-sig")
    print(f"[phase 1] Saved raw data -> {raw_csv_path}")

    scored_all_df = score_custom_keywords(raw_df.copy(), custom_keywords)
    scored_all_df = add_recency_columns(scored_all_df)
    scored_all_df.to_csv(scored_all_csv_path, index=False, encoding="utf-8-sig")
    print(f"[phase 2] Saved scored all rows -> {scored_all_csv_path}")

    print(f"[phase 2] Filtering to {target_location} + tech titles...")
    filtered_df = filter_base_dataframe(scored_all_df, target_location)
    print(f"[phase 2] Rows after base filter: {len(filtered_df)}")

    print("[phase 3] Ranking and exporting...")
    ranked_df = filtered_df.sort_values(
        by=["Custom_Keyword_Score", "Days_Ago"],
        ascending=[False, True],
    )

    export_columns = [
        "title",
        "company",
        "location",
        "province_id",
        "salary",
        "url",
        "Custom_Keyword_Score",
        "Days_Ago",
        "updated_at",
        "source",
    ]
    ranked_df[export_columns].to_csv(ranked_csv_path, index=False, encoding="utf-8-sig")
    print(f"[phase 3] Saved ranked data -> {ranked_csv_path}")


JOBTHAI_CONFIG = {
    "source_name": "jobthai",
    "base_url": "https://www.jobthai.com",
    "next_data_search_key_prefix": "searchJobs(",
    "next_data_detail_key_prefix": "getJobRawData(",
    "job_detail_path_template": "/th/job/{id}",
}


def main() -> None:
    target_location = "ขอนแก่น"
    search_url = "https://www.jobthai.com/th/jobs?jobtype=7&subjobtype=52&province=06"
    keyword_text = input(
        "ใส่คีย์เวิร์ดเพิ่มเติม (คั่นด้วย ,) เช่น เบี้ยเลี้ยง,ที่พัก,work from home: "
    ).strip()
    custom_keywords = [kw.strip() for kw in keyword_text.split(",")] if keyword_text else []
    print(f"Using custom keywords: {custom_keywords}")
    run_pipeline(search_url, JOBTHAI_CONFIG, custom_keywords, target_location)


if __name__ == "__main__":
    main()
