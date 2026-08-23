import pandas as pd
from pathlib import Path
from datetime import datetime, timezone
from typing import List
from dataclasses import asdict

from scrapers.base import Job, BaseScraper
from scrapers.jobthai import JobThaiScraper
from scrapers.jobsdb import JobsDBScraper
from scrapers.dekfukngan import DekFuknganScraper
from scrapers.internth import InternTHScraper

def jobs_to_dataframe(jobs: List[Job]) -> pd.DataFrame:
    if not jobs:
        return pd.DataFrame()
    return pd.DataFrame([asdict(j) for j in jobs])

def filter_it_jobs(df: pd.DataFrame) -> pd.DataFrame:
    # ผู้ใช้สั่งให้ยกเลิกการกรอง และใช้ข้อมูล raw ทั้งหมด
    return df

def add_recency_and_score(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return df
        
    now_utc = datetime.now(timezone.utc)
    parsed = pd.to_datetime(df["updated_at"], errors="coerce", utc=True)
    df["Posted_At"] = parsed
    df["Days_Ago"] = (now_utc - parsed).dt.days
    
    # ถ้าไม่มีวันที่ ให้อนุมานว่าเก่า (เช่น 999 วัน)
    df["Days_Ago"] = df["Days_Ago"].fillna(999)

    combined_text = (
        df["description"].fillna("")
        + " "
        + df["benefits"].fillna("")
    )
    
    # ความยาวของเนื้อหาใช้แทนคะแนนความละเอียด
    df["Score"] = combined_text.str.len()
    return df

def run_pipeline() -> None:
    output_dir = Path("outputs")
    output_dir.mkdir(exist_ok=True)
    raw_csv_path = output_dir / "raw_internships.csv"
    ranked_csv_path = output_dir / "ranked_internships.csv"
    
    # สร้าง Scraper ทั้งหมด
    scrapers: List[BaseScraper] = [
        JobThaiScraper(),
        JobsDBScraper(),
        DekFuknganScraper(),
        InternTHScraper(),
    ]

    all_jobs: List[Job] = []
    
    def fetch_for_province(province: str):
        print(f"\n[phase 1] Scraping {province} internships from all sources...")
        province_jobs = []
        for scraper in scrapers:
            try:
                jobs = scraper.scrape(target_province=province, limit=50) # fetch up to 50 per source
                province_jobs.extend(jobs)
            except Exception as e:
                print(f"[warn] {scraper.source_name} failed: {e}")
        return province_jobs

    # 1. Fetch Khon Kaen
    all_jobs.extend(fetch_for_province("Khon Kaen"))
    
    # filter just to check how many IT jobs we got
    temp_df = jobs_to_dataframe(all_jobs)
    if not temp_df.empty:
        temp_filtered = filter_it_jobs(temp_df)
    else:
        temp_filtered = pd.DataFrame()
        
    # 2. If Khon Kaen jobs < 100, fetch Bangkok
    if len(temp_filtered) < 100:
        print(f"\n[phase 1] Khon Kaen jobs are only {len(temp_filtered)}. Fetching Bangkok as fallback...")
        all_jobs.extend(fetch_for_province("Bangkok"))
    
    print(f"\n[phase 1] Total raw jobs collected: {len(all_jobs)}")
    
    if not all_jobs:
        print("No jobs found from any source.")
        return
        
    # แปลงเป็น DataFrame และเซฟตัวดิบ
    df = jobs_to_dataframe(all_jobs)
    df.to_csv(raw_csv_path, index=False, encoding="utf-8-sig")
    print(f"[phase 1] Saved raw data -> {raw_csv_path}")
    
    print("\n[phase 2] Bypassing IT filter (User requested to rank all raw data)...")
    filtered_df = filter_it_jobs(df)
    print(f"[phase 2] Rows to rank: {len(filtered_df)}")
    
    if not filtered_df.empty:
        print("\n[phase 3] Calculating Recency and Scores...")
        scored_df = add_recency_and_score(filtered_df)
        
        print("\n[phase 4] Ranking and exporting...")
        # Sort by Days_Ago (ascending) then Score (descending)
        ranked_df = scored_df.sort_values(by=["Days_Ago", "Score"], ascending=[True, False])
        
        # จำกัดแค่ 100 ที่
        ranked_df = ranked_df.head(100)

        export_columns = [
            "title",
            "company",
            "location",
            "province",
            "salary",
            "Score",
            "Days_Ago",
            "source",
            "updated_at",
            "url"
        ]
        
        ranked_df[export_columns].to_csv(ranked_csv_path, index=False, encoding="utf-8-sig")
        print(f"[phase 4] Saved {len(ranked_df)} ranked data -> {ranked_csv_path}")
    else:
        print("No jobs left after filtering. Ranked CSV not created.")
        
if __name__ == "__main__":
    run_pipeline()
