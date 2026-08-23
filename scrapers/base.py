from abc import ABC, abstractmethod
from typing import List, Optional
from dataclasses import dataclass
from datetime import datetime

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

class BaseScraper(ABC):
    def __init__(self):
        self.source_name = "base"

    @abstractmethod
    def scrape(self, target_province: str, limit: int = 100) -> List[Job]:
        """
        Scrape internship jobs for the target province (e.g. 'Khon Kaen', 'Bangkok').
        Must be implemented by subclasses.
        """
        raise NotImplementedError
