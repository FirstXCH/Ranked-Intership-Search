from typing import List, Optional
import requests
from bs4 import BeautifulSoup
from .base import BaseScraper, Job

class DekFuknganScraper(BaseScraper):
    def __init__(self):
        super().__init__()
        self.source_name = "dekfukngan"
        self.base_url = "https://www.xn--12cas3c2av3m3a0g7c.com"

    def _fetch_html(self, url: str) -> str:
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        }
        response = requests.get(url, headers=headers, timeout=20)
        response.raise_for_status()
        return response.text

    def scrape(self, target_province: str, limit: int = 100) -> List[Job]:
        print(f"[{self.source_name}] Scraping {target_province} internships...")
        
        # User provided URL searching everywhere
        search_url = f"{self.base_url}/%E0%B8%84%E0%B9%89%E0%B8%99%E0%B8%AB%E0%B8%B2%E0%B8%87%E0%B8%B2%E0%B8%99?search%5Btypes%5D=3277&search%5Ballowance%5D=1&search%5Bpositions%5D%5B%5D=2840"
        
        try:
            html = self._fetch_html(search_url)
            soup = BeautifulSoup(html, "html.parser")
            
            job_cards = soup.find_all("div", class_="job-post-box")
            if not job_cards:
                print(f"[{self.source_name}] No jobs found on search page.")
                return []
                
            jobs: List[Job] = []
            for card in job_cards[:limit]:
                try:
                    a_tag = card.find("a")
                    if not a_tag:
                        continue
                    
                    href = a_tag.get("href", "")
                    job_url = href if href.startswith("http") else self.base_url + href
                    
                    title_elem = card.find("div", class_="job-post-box--capacity")
                    title = title_elem.text.strip() if title_elem else "N/A"
                    
                    company_elem = card.find("div", class_="job-post-box--company")
                    company = company_elem.text.strip() if company_elem else ""
                    
                    location_elem = card.find("div", class_="job-post-box--location")
                    location = location_elem.text.strip() if location_elem else ""
                    
                    # Manual filter by province
                    th_prov = "ขอนแก่น" if target_province == "Khon Kaen" else "กรุงเทพ"
                    if th_prov not in location and target_province.lower() not in location.lower():
                        continue
                    
                    date_elem = card.find("div", class_="job-post-box--date")
                    updated_at = date_elem.text.strip() if date_elem else ""
                    
                    jobs.append(Job(
                        id=href.split("/")[-1],
                        title=title,
                        company=company,
                        location=location,
                        province=target_province,
                        url=job_url,
                        source=self.source_name,
                        updated_at=updated_at,
                        description=title
                    ))
                except Exception as ex:
                    pass
            
            return jobs
        except Exception as e:
            print(f"[{self.source_name}] Error scraping: {e}")
            return []
