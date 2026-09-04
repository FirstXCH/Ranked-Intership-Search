from abc import ABC, abstractmethod
from typing import List, Optional, Dict
from dataclasses import dataclass
import time
import random
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

@dataclass
class Job:
    id: str
    title: str
    company: str
    location: str
    province: str
    url: str
    salary: Optional[str] = None
    source: str = "unknown"
    updated_at: Optional[str] = None
    description: str = ""
    benefits: str = ""

def get_retry_session(
    retries: int = 3,
    backoff_factor: float = 1.0,
    status_forcelist: tuple = (429, 500, 502, 503, 504)
) -> requests.Session:
    """
    สร้าง requests.Session พร้อมระบบ Retry และ Exponential Backoff
    เพื่อป้องกันการถูกตัดการเชื่อมต่อ หรือ Rate-limit ชั่วคราว
    """
    session = requests.Session()
    retry_strategy = Retry(
        total=retries,
        backoff_factor=backoff_factor,
        status_forcelist=status_forcelist,
        allowed_methods=["GET", "POST"],
        raise_on_status=False
    )
    adapter = HTTPAdapter(max_retries=retry_strategy)
    session.mount("http://", adapter)
    session.mount("https://", adapter)
    return session

class BaseScraper(ABC):
    def __init__(self):
        self.source_name = "base"
        self.session = get_retry_session()
        self.default_headers = {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/120.0.0.0 Safari/537.36"
            )
        }

    def _fetch_html(self, url: str, headers: Optional[Dict[str, str]] = None, timeout: int = 20) -> str:
        """
        ดึงข้อมูล HTML จาก URL ที่กำหนด ผ่าน Session ที่มี Retry/Backoff
        """
        req_headers = {**self.default_headers, **(headers or {})}
        response = self.session.get(url, headers=req_headers, timeout=timeout)
        response.raise_for_status()
        return response.text

    def _throttle_delay(self, min_sec: float = 0.5, max_sec: float = 1.2) -> None:
        """
        หน่วงเวลาสุ่มเล็กน้อยเพื่อป้องกันการส่งคำขอถี่เกินไป (Request Throttling)
        """
        time.sleep(random.uniform(min_sec, max_sec))

    @abstractmethod
    def scrape(
        self,
        target_province: str,
        limit: int = 50,
        max_pages: int = 5,
        category: str = "it"
    ) -> List[Job]:
        """
        ดึงข้อมูลประกาศรับสมัครงานตามจังหวัดและหมวดหมู่ที่ระบุ
        พร้อมรองรับการดึงหลายหน้า (Pagination) จนครบจำนวน limit
        """
        raise NotImplementedError
