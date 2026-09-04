import re
import json
from typing import List, Optional
from bs4 import BeautifulSoup
from .base import BaseScraper, Job

class JobsDBScraper(BaseScraper):
    def __init__(self):
        super().__init__()
        self.source_name = "jobsdb"
        self.base_url = "https://th.jobsdb.com"

        self.province_keywords = {
            "khon kaen": ["ขอนแก่น", "khon kaen", "khonkaen"],
            "ขอนแก่น": ["ขอนแก่น", "khon kaen"],
            "bangkok": ["กรุงเทพ", "กรุงเทพมหานคร", "bangkok", "bkk"],
            "กรุงเทพ": ["กรุงเทพ", "กรุงเทพมหานคร", "bangkok", "bkk"],
            "กรุงเทพมหานคร": ["กรุงเทพ", "กรุงเทพมหานคร", "bangkok", "bkk"],
            "chiang mai": ["เชียงใหม่", "chiang mai", "chiangmai"],
            "เชียงใหม่": ["เชียงใหม่", "chiang mai"],
            "chon buri": ["ชลบุรี", "chon buri", "chonburi"],
            "ชลบุรี": ["ชลบุรี", "chon buri"],
            "phuket": ["ภูเก็ต", "phuket"],
            "ภูเก็ต": ["ภูเก็ต", "phuket"],
        }

    def _matches_province(self, location: str, target_province: str) -> bool:
        """
        ตรวจสอบว่าสถานที่ในประกาศงานตรงกับจังหวัดเป้าหมายหรือไม่
        """
        if not location:
            return False
        loc_lower = location.lower()
        target_lower = target_province.strip().lower()

        keywords = self.province_keywords.get(target_lower, [target_lower])
        return any(kw in loc_lower for kw in keywords)

    def _get_search_url(self, page: int = 1, category: str = "it") -> str:
        cat_lower = category.strip().lower()
        if cat_lower in ["it", "computer", "software"]:
            return (
                f"{self.base_url}/th/internship-jobs-in-information-communication-technology"
                f"?subclassification=6287%2C6286%2C6302%2C6301%2C6295%2C6284%2C6288%2C6289%2C6290%2C6293"
                f"&page={page}"
            )
        # กรณีหมวดหมู่อื่นๆ
        return f"{self.base_url}/th/internship-{cat_lower}-jobs?page={page}"

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
            search_url = self._get_search_url(page=page, category=category)
            try:
                html = self._fetch_html(search_url)
            except Exception as e:
                print(f"[warn] [{self.source_name}] Error fetching page {page}: {e}")
                break

            match = re.search(r'window\.SEEK_REDUX_DATA\s*=\s*(.*?});', html)
            if not match:
                # ลองค้นหาแบบ JSON script หรือ tag สำรอง
                break

            try:
                data = json.loads(match.group(1))
                results = data.get('results', {}).get('results', {})
                jobs_data = results.get('jobs', [])
            except Exception as e:
                print(f"[warn] [{self.source_name}] Failed to parse JSON on page {page}: {e}")
                break

            if not jobs_data:
                break

            new_jobs = []
            for entry in jobs_data:
                job_id = str(entry.get('id', ''))
                if not job_id or job_id in seen_ids:
                    continue

                title = str(entry.get('title', '')).strip()
                company = str(entry.get('advertiser', {}).get('description', '')).strip()

                loc_list = entry.get('locations', [])
                location = loc_list[0].get('label', '') if loc_list else ''

                # กรองตามจังหวัดเป้าหมาย
                if not self._matches_province(location, target_province):
                    continue

                salary = str(entry.get('salaryLabel', '')).strip()
                url = f"{self.base_url}/th/job/{job_id}"
                updated_at = str(entry.get('listingDate', '')).strip()

                bullet_points = entry.get('bulletPoints', []) or []
                benefits = " ".join(str(bp) for bp in bullet_points if bp)
                description = str(entry.get('teaser', '')).strip()

                seen_ids.add(job_id)
                job_obj = Job(
                    id=job_id,
                    title=title,
                    company=company,
                    location=location or target_province,
                    province=target_province,
                    url=url,
                    salary=salary or None,
                    source=self.source_name,
                    updated_at=updated_at or None,
                    description=description,
                    benefits=benefits
                )
                new_jobs.append(job_obj)

            all_jobs.extend(new_jobs)
            print(f"  [{self.source_name}] Page {page}: found {len(new_jobs)} matching jobs (Total: {len(all_jobs)})")

            if len(all_jobs) >= limit:
                all_jobs = all_jobs[:limit]
                break

            self._throttle_delay(0.5, 1.0)

        return all_jobs
