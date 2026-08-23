import re
import json
from typing import List, Dict, Optional
import requests
from bs4 import BeautifulSoup

from .base import BaseScraper, Job

class JobThaiScraper(BaseScraper):
    def __init__(self):
        super().__init__()
        self.source_name = "jobthai"
        self.base_url = "https://www.jobthai.com"
        self.config = {
            "source_name": self.source_name,
            "base_url": self.base_url,
            "next_data_search_key_prefix": "searchJobs(",
            "next_data_detail_key_prefix": "getJobRawData(",
            "job_detail_path_template": "/th/company/job/{id}",
        }

    def _fetch_html(self, url: str, headers: Optional[Dict[str, str]] = None) -> str:
        headers = headers or {"User-Agent": "Mozilla/5.0"}
        response = requests.get(url, headers=headers, timeout=20)
        response.raise_for_status()
        return response.text

    def _normalize_url(self, href: str, base_url: str) -> str:
        if not href:
            return ""
        if href.startswith("http"):
            return href
        return base_url.rstrip("/") + "/" + href.lstrip("/")

    def _html_to_text(self, value: Optional[str]) -> str:
        if not value:
            return ""
        return " ".join(BeautifulSoup(value, "html.parser").get_text(" ", strip=True).split())

    def _extract_next_data_payload(self, html: str) -> Dict:
        match = re.search(
            r'<script id="__NEXT_DATA__" type="application/json"[^>]*>(.*?)</script>',
            html,
            flags=re.DOTALL
        )
        if not match:
            raise ValueError("Could not find __NEXT_DATA__ payload in HTML.")
        return json.loads(match.group(1))

    def _parse_jobs_from_search(self, html: str) -> List[Job]:
        payload = self._extract_next_data_payload(html)
        root_query = payload.get("props", {}).get("apolloState", {}).get("ROOT_QUERY", {})

        key_prefix = self.config["next_data_search_key_prefix"]
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

            job_id = str(entry.get("id"))
            detail_path = self.config["job_detail_path_template"].format(id=job_id)
            job_url = self._normalize_url(detail_path, self.config["base_url"])

            jobs.append(
                Job(
                    id=job_id,
                    title=title,
                    company=str(entry.get("companyName", "")).strip(),
                    location=location,
                    province="06", # Temporary, gets updated in scrape()
                    url=job_url,
                    salary=str(entry.get("salary", "")).strip() or None,
                    source=self.source_name,
                    updated_at=str(entry.get("updatedAt", "")).strip() or None,
                )
            )

        return jobs

    def _parse_job_detail(self, html: str, job_url: str) -> Dict[str, str]:
        payload = self._extract_next_data_payload(html)
        root_query = payload.get("props", {}).get("apolloState", {}).get("ROOT_QUERY", {})

        key_prefix = self.config["next_data_detail_key_prefix"]
        detail_key = next((key for key in root_query if key.startswith(key_prefix)), None)
        if not detail_key:
            raise ValueError(f"Could not find detail key prefix '{key_prefix}' for {job_url}")

        data = root_query.get(detail_key, {}).get("data", {})
        if not isinstance(data, dict):
            raise ValueError(f"Detail payload for {job_url} is not a dict.")

        return {
            "description": self._html_to_text(data.get("description")),
            "benefits": self._html_to_text(data.get("benefit")),
            "updated_at": str(data.get("updatedAt", "")).strip(),
        }

    def _enrich_jobs_with_details(self, jobs: List[Job]) -> None:
        for job in jobs:
            try:
                detail_html = self._fetch_html(job.url)
                detail = self._parse_job_detail(detail_html, job.url)
                job.description = detail["description"]
                job.benefits = detail["benefits"]
                if detail["updated_at"]:
                    job.updated_at = detail["updated_at"]
            except requests.RequestException as error:
                print(f"[warn] Failed to fetch detail URL: {job.url} ({error})")
            except (ValueError, json.JSONDecodeError) as error:
                # Fallback to simple HTML parsing if Next.js payload is not found
                try:
                    soup = BeautifulSoup(detail_html, "html.parser")
                    job.description = soup.body.text.strip()[:3000] if soup.body else ""
                except Exception as e:
                    print(f"[warn] Fallback HTML parse failed: {job.url} ({e})")

    def scrape(self, target_province: str, limit: int = 100) -> List[Job]:
        print(f"[{self.source_name}] Scraping {target_province} internships...")
        
        # JobThai province IDs
        province_id = "06" if target_province == "Khon Kaen" else "1"
        
        # Base search URL for IT jobs
        search_url = f"{self.base_url}/th/jobs?jobtype=7&subjobtype=52&province={province_id}"
        
        search_html = self._fetch_html(search_url)
        jobs = self._parse_jobs_from_search(search_html)
        if not jobs:
            return []
            
        # Limit the number of jobs
        jobs = jobs[:limit]
        
        # update province name in jobs
        for job in jobs:
            job.province = target_province
            job.location = "Khon Kaen" if target_province == "Khon Kaen" else "Bangkok"
            
        self._enrich_jobs_with_details(jobs)
        return jobs
