import re
import json
from typing import List, Optional
import requests
from bs4 import BeautifulSoup
from .base import BaseScraper, Job

class JobsDBScraper(BaseScraper):
    def __init__(self):
        super().__init__()
        self.source_name = "jobsdb"
        # 6281 is IT category, we use keyword + location instead of hardcoded subclassification to be broad
        # 10223 is Khon Kaen location ID in JobsDB, but we can also use 'khon-kaen' in url
        self.base_url = "https://th.jobsdb.com"
        
    def _fetch_html(self, url: str) -> str:
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        }
        response = requests.get(url, headers=headers, timeout=20)
        response.raise_for_status()
        return response.text

    def scrape(self, target_province: str, limit: int = 100) -> List[Job]:
        print(f"[{self.source_name}] Scraping {target_province} internships...")
        
        # User provided url + subclassification filter (Search all Thailand)
        search_url = f"{self.base_url}/th/internship-jobs-in-information-communication-technology?subclassification=6287%2C6286%2C6302%2C6301%2C6295%2C6284%2C6288%2C6289%2C6290%2C6293"
        
        try:
            html = self._fetch_html(search_url)
            
            # Find the Redux state payload
            import re, json
            match = re.search(r'window\.SEEK_REDUX_DATA\s*=\s*(.*?});', html)
            if not match:
                print(f"[{self.source_name}] Could not find SEEK_REDUX_DATA")
                return []
                
            data = json.loads(match.group(1))
            results = data.get('results', {}).get('results', {})
            
            if not isinstance(results, dict):
                print(f"[{self.source_name}] Invalid payload structure.")
                return []
                
            jobs_data = results.get('jobs', [])
            
            if not jobs_data:
                print(f"[{self.source_name}] No jobs found in payload.")
                return []
                
            jobs: List[Job] = []
            for entry in jobs_data[:limit]:
                job_id = str(entry.get('id', ''))
                title = entry.get('title', '')
                company = entry.get('advertiser', {}).get('description', '')
                
                loc_list = entry.get('locations', [])
                location = loc_list[0].get('label', '') if loc_list else ''
                
                # Filter by province manually since we search all
                th_prov = "ขอนแก่น" if target_province == "Khon Kaen" else "กรุงเทพ"
                if th_prov not in location and target_province.lower() not in location.lower():
                    continue
                    
                salary = entry.get('salaryLabel', '')
                
                # job url
                url = f"{self.base_url}/th/job/{job_id}"
                
                # updated_at (listingDate)
                updated_at = entry.get('listingDate', '')
                
                # bullet points as benefits
                bullet_points = entry.get('bulletPoints', [])
                benefits = " ".join(bullet_points)
                
                # teaser as description
                description = entry.get('teaser', '')
                
                jobs.append(Job(
                    id=job_id,
                    title=title,
                    company=company,
                    location=location,
                    province=target_province,
                    url=url,
                    salary=salary or None,
                    source=self.source_name,
                    updated_at=updated_at or None,
                    description=description,
                    benefits=benefits
                ))
                
            return jobs
        except Exception as e:
            print(f"[{self.source_name}] Error scraping: {e}")
            return []
