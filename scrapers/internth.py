import re
import urllib.parse
from typing import List, Optional
import requests
from bs4 import BeautifulSoup
from .base import BaseScraper, Job

class InternTHScraper(BaseScraper):
    def __init__(self):
        super().__init__()
        self.source_name = "internth"
        self.base_url = "https://internth.com"

        self.province_map = {
            "khon kaen": "ขอนแก่น",
            "ขอนแก่น": "ขอนแก่น",
            "bangkok": "กรุงเทพ",
            "กรุงเทพ": "กรุงเทพ",
            "กรุงเทพมหานคร": "กรุงเทพ",
            "bkk": "กรุงเทพ",
            "chiang mai": "เชียงใหม่",
            "เชียงใหม่": "เชียงใหม่",
            "chon buri": "ชลบุรี",
            "ชลบุรี": "ชลบุรี",
            "phuket": "ภูเก็ต",
            "ภูเก็ต": "ภูเก็ต",
        }

        self.category_map = {
            "it": "คอมพิวเตอร์-ไอที",
            "computer": "คอมพิวเตอร์-ไอที",
            "software": "คอมพิวเตอร์-ไอที",
            "marketing": "การตลาด",
            "accounting": "บัญชี",
            "graphic": "กราฟิกดีไซน์",
        }

    def _get_province_slug(self, target_province: str) -> str:
        norm = target_province.strip().lower()
        thai_name = self.province_map.get(norm, target_province.strip())
        return urllib.parse.quote(thai_name)

    def _get_category_slug(self, category: str) -> str:
        norm = category.strip().lower()
        thai_cat = self.category_map.get(norm, "คอมพิวเตอร์-ไอที")
        return urllib.parse.quote(thai_cat)

    def scrape(
        self,
        target_province: str,
        limit: int = 50,
        max_pages: int = 5,
        category: str = "it"
    ) -> List[Job]:
        print(f"[{self.source_name}] Scraping {target_province} (Category: {category}, Target limit: {limit})...")

        province_path = self._get_province_slug(target_province)
        category_path = self._get_category_slug(category)

        all_jobs: List[Job] = []
        seen_ids = set()

        for page in range(1, max_pages + 1):
            page_query = f"?page={page}" if page > 1 else ""
            search_url = f"{self.base_url}/%E0%B8%9D%E0%B8%B6%E0%B8%81%E0%B8%87%E0%B8%B2%E0%B8%99/{province_path}/{category_path}{page_query}"

            try:
                html = self._fetch_html(search_url)
            except Exception as e:
                print(f"[warn] [{self.source_name}] Error fetching page {page}: {e}")
                break

            soup = BeautifulSoup(html, "html.parser")
            job_cards = soup.find_all("div", class_=re.compile(r"JobCard__JobCardStyle"))
            if not job_cards:
                break

            new_jobs = []
            for card in job_cards:
                try:
                    details_div = card.find("div", class_="details")
                    if not details_div:
                        continue

                    job_a = details_div.find("h3").find("a") if details_div.find("h3") else None
                    if not job_a:
                        continue

                    href = job_a.get("href", "")
                    job_id = href.split("/")[-1]
                    if not job_id or job_id in seen_ids:
                        continue

                    job_url = href if href.startswith("http") else self.base_url + href
                    title = job_a.text.strip()

                    company_div = card.find("div", class_="company-details")
                    company_a = company_div.find("a") if company_div else None
                    company = company_a.text.strip() if company_a else ""

                    seen_ids.add(job_id)
                    new_jobs.append(Job(
                        id=job_id,
                        title=title,
                        company=company,
                        location=target_province,
                        province=target_province,
                        url=job_url,
                        source=self.source_name,
                        description=title
                    ))
                except Exception:
                    pass

            all_jobs.extend(new_jobs)
            print(f"  [{self.source_name}] Page {page}: found {len(new_jobs)} matching jobs (Total: {len(all_jobs)})")

            if len(all_jobs) >= limit:
                all_jobs = all_jobs[:limit]
                break

            self._throttle_delay(0.5, 1.0)

        return all_jobs
