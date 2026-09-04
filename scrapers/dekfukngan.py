from typing import List, Optional
import requests
from bs4 import BeautifulSoup
from .base import BaseScraper, Job

class DekFuknganScraper(BaseScraper):
    def __init__(self):
        super().__init__()
        self.source_name = "dekfukngan"
        self.base_url = "https://www.xn--12cas3c2av3m3a0g7c.com"

        self.province_keywords = {
            "khon kaen": ["ขอนแก่น", "khon kaen"],
            "ขอนแก่น": ["ขอนแก่น", "khon kaen"],
            "bangkok": ["กรุงเทพ", "กรุงเทพมหานคร", "bangkok", "bkk"],
            "กรุงเทพ": ["กรุงเทพ", "กรุงเทพมหานคร", "bangkok", "bkk"],
            "กรุงเทพมหานคร": ["กรุงเทพ", "กรุงเทพมหานคร", "bangkok", "bkk"],
            "chiang mai": ["เชียงใหม่", "chiang mai"],
            "เชียงใหม่": ["เชียงใหม่", "chiang mai"],
            "chon buri": ["ชลบุรี", "chon buri"],
            "ชลบุรี": ["ชลบุรี", "chon buri"],
            "phuket": ["ภูเก็ต", "phuket"],
            "ภูเก็ต": ["ภูเก็ต", "phuket"],
        }

    def _matches_province(self, location: str, target_province: str) -> bool:
        if not location:
            return False
        loc_lower = location.lower()
        target_lower = target_province.strip().lower()
        keywords = self.province_keywords.get(target_lower, [target_lower])
        return any(kw in loc_lower for kw in keywords)

    def scrape(
        self,
        target_province: str,
        limit: int = 50,
        max_pages: int = 5,
        category: str = "it"
    ) -> List[Job]:
        print(f"[{self.source_name}] Scraping {target_province} (Category: {category}, Target limit: {limit})...")

        all_jobs: List[Job] = []
        seen_ids = set()

        for page in range(1, max_pages + 1):
            # ค้นหางานฝึกงานสายคอมพิวเตอร์/ไอที (position=2840) พร้อมระบบแบ่งหน้า page={page}
            search_url = (
                f"{self.base_url}/%E0%B8%84%E0%B9%89%E0%B8%99%E0%B8%AB%E0%B8%B2%E0%B8%87%E0%B8%B2%E0%B8%99"
                f"?page={page}&search%5Btypes%5D=3277&search%5Ballowance%5D=1&search%5Bpositions%5D%5B%5D=2840"
            )

            try:
                html = self._fetch_html(search_url)
            except Exception as e:
                print(f"[warn] [{self.source_name}] Error fetching page {page}: {e}")
                break

            soup = BeautifulSoup(html, "html.parser")
            job_cards = soup.find_all("div", class_="job-post-box")
            if not job_cards:
                break

            new_jobs = []
            for card in job_cards:
                try:
                    a_tag = card.find("a")
                    if not a_tag:
                        continue

                    href = a_tag.get("href", "")
                    job_id = href.split("/")[-1]
                    if not job_id or job_id in seen_ids:
                        continue

                    job_url = href if href.startswith("http") else self.base_url + href

                    title_elem = card.find("div", class_="job-post-box--capacity")
                    title = title_elem.text.strip() if title_elem else "N/A"

                    company_elem = card.find("div", class_="job-post-box--company")
                    company = company_elem.text.strip() if company_elem else ""

                    location_elem = card.find("div", class_="job-post-box--location")
                    location = location_elem.text.strip() if location_elem else ""

                    # ตรวจสอบจังหวัดเป้าหมาย
                    if not self._matches_province(location, target_province):
                        continue

                    date_elem = card.find("div", class_="job-post-box--date")
                    updated_at = date_elem.text.strip() if date_elem else ""

                    seen_ids.add(job_id)
                    new_jobs.append(Job(
                        id=job_id,
                        title=title,
                        company=company,
                        location=location or target_province,
                        province=target_province,
                        url=job_url,
                        source=self.source_name,
                        updated_at=updated_at or None,
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
