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

        # ตารางจับคู่รหัสจังหวัดของ JobThai (Prefix รหัสจังหวัดสองหลัก)
        self.province_code_map = {
            "bangkok": "01",
            "กรุงเทพ": "01",
            "กรุงเทพมหานคร": "01",
            "bkk": "01",
            "khon kaen": "06",
            "ขอนแก่น": "06",
            "chiang mai": "07",
            "เชียงใหม่": "07",
            "chon buri": "08",
            "ชลบุรี": "08",
            "nonthaburi": "03",
            "นนทบุรี": "03",
            "pathum thani": "04",
            "ปทุมธานี": "04",
            "samut prakan": "02",
            "สมุทรปราการ": "02",
            "phuket": "11",
            "ภูเก็ต": "11",
            "songkhla": "10",
            "สงขลา": "10",
            "nakhon ratchasima": "09",
            "นครราชสีมา": "09",
        }

        # ตารางจับคู่รหัสหมวดหมู่งาน (subjobtype) ของ JobThai
        self.category_code_map = {
            "it": "52",            # คอมพิวเตอร์/IT/โปรแกรมเมอร์
            "computer": "52",
            "software": "52",
            "marketing": "3",      # การตลาด
            "accounting": "1",     # บัญชี
            "engineer": "10",      # วิศวกร
            "graphic": "5",        # ออกแบบ/กราฟิก
        }

    def _get_province_code(self, province_name: str) -> str:
        """
        แปลงชื่อจังหวัดเป็นรหัสของ JobThai (เช่น '01' สำหรับกรุงเทพฯ, '06' สำหรับขอนแก่น)
        """
        normalized = province_name.strip().lower()
        if normalized in self.province_code_map:
            return self.province_code_map[normalized]
        # ถ้าระบุเป็นตัวเลข 2 หลักอยู่แล้วให้ใช้ค่านั้นได้เลย
        if normalized.isdigit():
            return normalized.zfill(2)
        # ค่าเริ่มต้นใช้ กรุงเทพฯ (01)
        return "01"

    def _get_category_code(self, category_name: str) -> Optional[str]:
        """
        แปลงชื่อหมวดหมู่งานเป็นรหัส subjobtype ของ JobThai
        """
        normalized = category_name.strip().lower()
        return self.category_code_map.get(normalized, "52")

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
        try:
            payload = self._extract_next_data_payload(html)
        except Exception:
            return []

        root_query = payload.get("props", {}).get("apolloState", {}).get("ROOT_QUERY", {})
        key_prefix = self.config["next_data_search_key_prefix"]
        search_key = next((key for key in root_query if key.startswith(key_prefix)), None)
        if not search_key:
            return []

        entries = root_query.get(search_key, {}).get("data", {}).get("data", [])
        if not isinstance(entries, list):
            return []

        jobs: List[Job] = []
        for entry in entries:
            title = str(entry.get("jobTitle", "")).strip()
            if not title:
                continue

            district_raw = (entry.get("district") or {}).get("name")
            province_raw = (entry.get("province") or {}).get("name")
            district = str(district_raw or "").strip()
            province = str(province_raw or "").strip()
            location = " ".join(part for part in [district, province] if part)

            job_id = str(entry.get("id"))
            detail_path = self.config["job_detail_path_template"].format(id=job_id)
            job_url = self._normalize_url(detail_path, self.config["base_url"])

            jobs.append(
                Job(
                    id=job_id,
                    title=title,
                    company=str(entry.get("companyName", "")).strip(),
                    location=location or province,
                    province=province,
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
        """
        ดึงรายละเอียดงานเพิ่มเติม (Job Description & Benefits) พร้อมระบบ Throttling ป้องกันการยิงถี่
        """
        for job in jobs:
            try:
                detail_html = self._fetch_html(job.url)
                detail = self._parse_job_detail(detail_html, job.url)
                job.description = detail["description"]
                job.benefits = detail["benefits"]
                if detail["updated_at"]:
                    job.updated_at = detail["updated_at"]
            except requests.RequestException as error:
                print(f"[warn] [{self.source_name}] Failed to fetch detail URL: {job.url} ({error})")
            except (ValueError, json.JSONDecodeError):
                # Fallback ไปดึงข้อความจาก HTML พื้นฐานถ้า Next.js payload ไม่มี
                try:
                    soup = BeautifulSoup(detail_html, "html.parser")
                    job.description = soup.body.text.strip()[:3000] if soup.body else ""
                except Exception:
                    pass
            # หน่วงเวลาสุ่มเล็กน้อยระหว่างดึง detail
            self._throttle_delay(0.3, 0.7)

    def scrape(
        self,
        target_province: str,
        limit: int = 50,
        max_pages: int = 5,
        category: str = "it"
    ) -> List[Job]:
        print(f"[{self.source_name}] Scraping {target_province} (Category: {category}, Target limit: {limit})...")

        province_id = self._get_province_code(target_province)
        subjobtype = self._get_category_code(category)
        subjob_param = f"&subjobtype={subjobtype}" if subjobtype else ""

        all_jobs: List[Job] = []
        seen_ids = set()

        # วนลูป Pagination ดึงหน้าถัดไปจนกว่าจะครบ limit หรือหมดหน้า
        for page in range(1, max_pages + 1):
            search_url = f"{self.base_url}/th/jobs?jobtype=7{subjob_param}&province={province_id}&page={page}"
            try:
                search_html = self._fetch_html(search_url)
                jobs_on_page = self._parse_jobs_from_search(search_html)
            except Exception as e:
                print(f"[warn] [{self.source_name}] Error fetching page {page}: {e}")
                break

            if not jobs_on_page:
                # ไม่มีงานในหน้านี้แล้ว
                break

            new_jobs = []
            for j in jobs_on_page:
                if j.id not in seen_ids:
                    seen_ids.add(j.id)
                    j.province = target_province
                    new_jobs.append(j)

            all_jobs.extend(new_jobs)
            print(f"  [{self.source_name}] Page {page}: found {len(new_jobs)} jobs (Total so far: {len(all_jobs)})")

            if len(all_jobs) >= limit:
                all_jobs = all_jobs[:limit]
                break

            # หน่วงเวลาเล็กน้อยก่อนเปิดหน้าถัดไป
            self._throttle_delay(0.5, 1.0)

        if not all_jobs:
            return []

        # ดึงรายละเอียดเพิ่มเติมสำหรับงานทั้งหมดที่รวบรวมได้
        print(f"  [{self.source_name}] Enriching details for {len(all_jobs)} jobs...")
        self._enrich_jobs_with_details(all_jobs)
        return all_jobs
