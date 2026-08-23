from typing import List
import requests
from bs4 import BeautifulSoup
from .base import BaseScraper, Job

class InternTHScraper(BaseScraper):
    def __init__(self):
        super().__init__()
        self.source_name = "internth"
        self.base_url = "https://internth.com"

    def _fetch_html(self, url: str) -> str:
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        }
        response = requests.get(url, headers=headers, timeout=20)
        response.raise_for_status()
        return response.text

    def scrape(self, target_province: str, limit: int = 100) -> List[Job]:
        print(f"[{self.source_name}] Scraping {target_province} internships...")
        
        # URL encode the province
        if target_province == "Khon Kaen":
            province_path = "%E0%B8%82%E0%B8%AD%E0%B8%99%E0%B9%81%E0%B8%81%E0%B9%88%E0%B8%99"
        else:
            province_path = "%E0%B8%81%E0%B8%A3%E0%B8%B8%E0%B8%87%E0%B9%80%E0%B8%97%E0%B8%9E"
            
        search_url = f"{self.base_url}/%E0%B8%9D%E0%B8%B6%E0%B8%81%E0%B8%87%E0%B8%B2%E0%B8%99/{province_path}/%E0%B8%84%E0%B8%AD%E0%B8%A1%E0%B8%9E%E0%B8%B4%E0%B8%A7%E0%B9%80%E0%B8%95%E0%B8%AD%E0%B8%A3%E0%B9%8C-%E0%B9%84%E0%B8%AD%E0%B8%97%E0%B8%B5"
        
        try:
            html = self._fetch_html(search_url)
            soup = BeautifulSoup(html, "html.parser")
            
            import re
            job_cards = soup.find_all("div", class_=re.compile(r"JobCard__JobCardStyle"))
            if not job_cards:
                print(f"[{self.source_name}] No jobs found.")
                return []
                
            jobs: List[Job] = []
            for card in job_cards[:limit]:
                try:
                    # Extract job details
                    details_div = card.find("div", class_="details")
                    if not details_div:
                        continue
                        
                    job_a = details_div.find("h3").find("a") if details_div.find("h3") else None
                    if not job_a:
                        continue
                        
                    href = job_a.get("href", "")
                    job_url = href if href.startswith("http") else self.base_url + href
                    title = job_a.text.strip()
                    
                    # Extract company
                    company_div = card.find("div", class_="company-details")
                    company_a = company_div.find("a") if company_div else None
                    company = company_a.text.strip() if company_a else ""
                    
                    jobs.append(Job(
                        id=href.split("/")[-1],
                        title=title,
                        company=company,
                        location="Khon Kaen" if target_province == "Khon Kaen" else "Bangkok",
                        province=target_province,
                        url=job_url,
                        source=self.source_name,
                        description=title
                    ))
                except Exception as ex:
                    pass
            
            return jobs
        except Exception as e:
            print(f"[{self.source_name}] Error scraping (DNS or blocked): {e}")
            return []
