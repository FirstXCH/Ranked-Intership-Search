import re
import urllib.parse
from typing import List, Optional
from bs4 import BeautifulSoup
from .base import BaseScraper, Job

class LinkedInScraper(BaseScraper):
    def __init__(self):
        super().__init__()
        self.source_name = "linkedin"
        self.base_url = "https://www.linkedin.com/jobs-guest/jobs/api/seeMoreJobPostings/search"

        self.province_map = {
            "khon kaen": "Khon Kaen, Thailand",
            "ขอนแก่น": "Khon Kaen, Thailand",
            "bangkok": "Bangkok, Thailand",
            "กรุงเทพ": "Bangkok, Thailand",
            "กรุงเทพมหานคร": "Bangkok, Thailand",
            "bkk": "Bangkok, Thailand",
            "chiang mai": "Chiang Mai, Thailand",
            "เชียงใหม่": "Chiang Mai, Thailand",
            "chon buri": "Chon Buri, Thailand",
            "ชลบุรี": "Chon Buri, Thailand",
            "phuket": "Phuket, Thailand",
            "ภูเก็ต": "Phuket, Thailand",
        }

    def _get_location_query(self, target_province: str) -> str:
        norm = target_province.strip().lower()
        loc = self.province_map.get(norm, f"{target_province}, Thailand")
        return urllib.parse.quote(loc)

    def scrape(
        self,
        target_province: str,
        limit: int = 50,
        max_pages: int = 5,
        category: str = "it"
    ) -> List[Job]:
        print(f"[{self.source_name}] Scraping {target_province} (Category: {category}, Target limit: {limit})...")

        loc_query = self._get_location_query(target_province)
        cat_query = urllib.parse.quote(f"internship {category}")

        all_jobs: List[Job] = []
        seen_ids = set()

        for page in range(max_pages):
            start = page * 10
            url = f"{self.base_url}?keywords={cat_query}&location={loc_query}&start={start}"

            try:
                html = self._fetch_html(url)
            except Exception as e:
                print(f"[warn] [{self.source_name}] Error fetching page {page + 1}: {e}")
                break

            soup = BeautifulSoup(html, "html.parser")
            cards = soup.find_all("li")
            if not cards:
                break

            new_jobs = []
            for card in cards:
                try:
                    title_elem = card.find("h3", class_=re.compile(r"base-search-card__title"))
                    if not title_elem:
                        continue
                    title = title_elem.text.strip()

                    comp_elem = card.find("h4", class_=re.compile(r"base-search-card__subtitle"))
                    company = comp_elem.text.strip() if comp_elem else ""

                    loc_elem = card.find("span", class_=re.compile(r"job-search-card__location"))
                    location = loc_elem.text.strip() if loc_elem else target_province

                    link_elem = card.find("a", class_=re.compile(r"base-card__full-link"))
                    if not link_elem or not link_elem.get("href"):
                        continue

                    raw_url = link_elem["href"]
                    # ลบ tracking query string ออกจาก URL
                    clean_url = raw_url.split("?")[0]

                    # ดึง Job ID จาก URL เช่น ...-4436546236
                    id_match = re.search(r"-(\d+)$", clean_url)
                    job_id = id_match.group(1) if id_match else str(abs(hash(clean_url)))

                    if job_id in seen_ids:
                        continue

                    time_elem = card.find("time")
                    updated_at = time_elem.get("datetime", "") if time_elem else ""

                    seen_ids.add(job_id)
                    job_obj = Job(
                        id=job_id,
                        title=title,
                        company=company,
                        location=location,
                        province=target_province,
                        url=clean_url,
                        source=self.source_name,
                        updated_at=updated_at or None,
                        description=f"{title} at {company}"
                    )
                    new_jobs.append(job_obj)
                except Exception:
                    pass

            all_jobs.extend(new_jobs)
            print(f"  [{self.source_name}] Page {page + 1}: found {len(new_jobs)} jobs (Total: {len(all_jobs)})")

            if len(all_jobs) >= limit:
                all_jobs = all_jobs[:limit]
                break

            self._throttle_delay(0.8, 1.5)

        return all_jobs
