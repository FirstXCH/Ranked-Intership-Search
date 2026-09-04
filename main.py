import argparse
import re
from pathlib import Path
from datetime import datetime, timezone
from typing import List, Dict, Tuple, Optional
from dataclasses import asdict

import pandas as pd

from scrapers.base import Job, BaseScraper
from scrapers.jobthai import JobThaiScraper
from scrapers.jobsdb import JobsDBScraper
from scrapers.dekfukngan import DekFuknganScraper
from scrapers.internth import InternTHScraper


def normalize_text(text: Optional[str]) -> str:
    """
    ทำความสะอาดข้อความ ตัดคำสร้อยบริษัท เครื่องหมายวรรคตอน และช่องว่างส่วนเกิน
    เพื่อใช้เปรียบเทียบหาข้อมูลซ้ำซ้อน (Deduplication)
    """
    if not text:
        return ""
    cleaned = text.lower().strip()

    # ตัดคำสร้อยบริษัทภาษาไทยทั่วไป
    thai_patterns = [
        r"บริษัท\s*",
        r"จำกัด\s*\(มหาชน\)",
        r"\(มหาชน\)",
        r"จำกัด\s*",
        r"บจก\.\s*",
        r"บมจ\.\s*",
        r"หจก\.\s*",
    ]
    for p in thai_patterns:
        cleaned = re.sub(p, "", cleaned, flags=re.IGNORECASE)

    # ตัดคำสร้อยบริษัทภาษาอังกฤษ
    eng_patterns = [
        r"\bco\.,?\s*ltd\.?",
        r"\bltd\.?",
        r"\binc\.?",
        r"\bcorp(\.|\b)",
        r"\bllc\.?",
        r"\bco\b",
        r"\bgroup\b",
    ]
    for p in eng_patterns:
        cleaned = re.sub(p, "", cleaned, flags=re.IGNORECASE)

    # ตัดคำระบุการฝึกงานในชื่อตำแหน่งเพื่อจับคู่ให้แม่นยำขึ้น
    title_terms = [
        r"\(สหกิจศึกษา\)",
        r"\(ฝึกงาน\)",
        r"\(นักศึกษาฝึกงาน\)",
        r"\binternship\b",
        r"\bintern\b",
        r"\btrainee\b",
    ]
    for p in title_terms:
        cleaned = re.sub(p, "", cleaned, flags=re.IGNORECASE)

    # ลบอักขระพิเศษ เว้นวรรคส่วนเกิน และสัญลักษณ์
    cleaned = re.sub(r"[^\w\s\u0E00-\u0E7F]", " ", cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    return cleaned


def deduplicate_jobs(jobs: List[Job]) -> Tuple[List[Job], int]:
    """
    ขจัดงานซ้ำซ้อนที่ถูกโพสต์ในหลายๆ เว็บ โดยตรวจสอบจาก (ชื่อบริษัท, ชื่อตำแหน่งงาน)
    หากพบงานซ้ำ จะรวมรายชื่อ source เข้าด้วยกัน และเลือกเก็บเนื้อหาที่มีรายละเอียดมากที่สุด
    """
    unique_groups: Dict[Tuple[str, str], List[Job]] = {}

    for job in jobs:
        norm_company = normalize_text(job.company)
        norm_title = normalize_text(job.title)

        # หากไม่มีชื่อบริษัท ให้ใช้ ID ของตัวเองเป็นคีย์เพื่อไม่ให้เผลอยุบรวมผิด
        if not norm_company:
            key = (f"unknown_{job.id}", norm_title)
        else:
            key = (norm_company, norm_title)

        if key not in unique_groups:
            unique_groups[key] = []
        unique_groups[key].append(job)

    deduped_jobs: List[Job] = []
    duplicate_count = 0

    for key, job_list in unique_groups.items():
        if len(job_list) == 1:
            deduped_jobs.append(job_list[0])
        else:
            duplicate_count += len(job_list) - 1

            # รวมแหล่งที่มาทั้งหมด เช่น 'jobthai, dekfukngan'
            all_sources = list(dict.fromkeys(j.source for j in job_list if j.source))
            combined_source = ", ".join(all_sources)

            # คัดเลือกรายการที่มีเนื้อหาละเอียดที่สุด (ความยาว description + benefits)
            best_job = max(
                job_list,
                key=lambda j: len(j.description or "") + len(j.benefits or "")
            )

            # ตรวจสอบเพิ่มเติม หากงานที่ดีที่สุดไม่มีเงินเดือนแต่มีงานอื่นที่มี ให้ดึงมาเติม
            if not best_job.salary:
                for alt in job_list:
                    if alt.salary:
                        best_job.salary = alt.salary
                        break

            best_job.source = combined_source
            deduped_jobs.append(best_job)

    return deduped_jobs, duplicate_count


def jobs_to_dataframe(jobs: List[Job]) -> pd.DataFrame:
    if not jobs:
        return pd.DataFrame()
    return pd.DataFrame([asdict(j) for j in jobs])


def add_recency_and_score(df: pd.DataFrame, custom_keywords: Optional[List[str]] = None) -> pd.DataFrame:
    """
    คำนวณความใหม่ของโพสต์ (Days_Ago), ความละเอียดของเนื้อหา (Score)
    และคะแนนคีย์เวิร์ดที่ผู้ใช้ระบุ (Custom_Keyword_Score พร้อม Matched_Keywords)
    """
    if df.empty:
        return df

    now_utc = datetime.now(timezone.utc)
    parsed = pd.to_datetime(df["updated_at"], errors="coerce", utc=True)
    df["Posted_At"] = parsed
    df["Days_Ago"] = (now_utc - parsed).dt.days

    # ถ้าไม่มีวันที่ ให้อนุมานว่าเป็นประกาศเก่า
    df["Days_Ago"] = df["Days_Ago"].fillna(999)

    combined_text = (
        df["title"].fillna("")
        + " "
        + df["description"].fillna("")
        + " "
        + df["benefits"].fillna("")
    )

    # ความยาวของเนื้อหาใช้แทนคะแนนความละเอียด
    df["Score"] = combined_text.str.len()

    # คำนวณ Custom Keyword Score
    keywords = [k.strip() for k in (custom_keywords or []) if k.strip()]
    if keywords:
        def match_keywords(text: str) -> Tuple[int, str]:
            text_lower = text.lower()
            matched = [kw for kw in keywords if kw.lower() in text_lower]
            # คะแนนคำนวณจากจำนวนคีย์เวิร์ดที่พบ (คำละ 10 คะแนน)
            score = len(matched) * 10
            return score, ", ".join(matched) if matched else "-"

        results = combined_text.apply(match_keywords)
        df["Custom_Keyword_Score"] = [r[0] for r in results]
        df["Matched_Keywords"] = [r[1] for r in results]
    else:
        df["Custom_Keyword_Score"] = 0
        df["Matched_Keywords"] = "-"

    return df


import sys

# ป้องกัน UnicodeEncodeError บน Windows terminal (cp874)
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")


def parse_arguments() -> argparse.Namespace:
    """
    สร้างตัวรับคำสั่ง CLI Parameters
    """
    parser = argparse.ArgumentParser(
        description="Ranked Internship Search - ค้นหาและจัดอันดับงานฝึกงานสาย IT จากหลายเว็บไซต์"
    )
    parser.add_argument(
        "--province",
        type=str,
        default="Khon Kaen",
        help="จังหวัดหลักที่ต้องการค้นหา (ค่าเริ่มต้น: 'Khon Kaen')"
    )
    parser.add_argument(
        "--fallback-province",
        type=str,
        default="Bangkok",
        help="จังหวัดสำรองหากจังหวัดหลักได้งานน้อยกว่าเกณฑ์ (ค่าเริ่มต้น: 'Bangkok')"
    )
    parser.add_argument(
        "--no-fallback",
        action="store_true",
        help="ปิดระบบ Fallback ไม่ดึงจังหวัดสำรองเพิ่ม"
    )
    parser.add_argument(
        "--min-jobs",
        type=int,
        default=100,
        help="จำนวนงานขั้นต่ำในจังหวัดหลัก หากได้น้อยกว่านี้จะดึงจังหวัดสำรอง (ค่าเริ่มต้น: 100)"
    )
    parser.add_argument(
        "--category",
        type=str,
        default="it",
        help="หมวดหมู่งาน เช่น 'it', 'marketing', 'accounting' (ค่าเริ่มต้น: 'it')"
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=50,
        help="จำนวนงานสูงสุดต่อหนึ่งเว็บไซต์ (ค่าเริ่มต้น: 50)"
    )
    parser.add_argument(
        "--keywords", "-k",
        type=str,
        default="",
        help="คีย์เวิร์ดกำหนดเองสำหรับบวกคะแนน คั่นด้วยจุลภาค เช่น 'เบี้ยเลี้ยง,ที่พัก,React,Python'"
    )
    parser.add_argument(
        "--top",
        type=int,
        default=100,
        help="จำนวนงานที่จะ Export ลงใน ranked_internships.csv (ค่าเริ่มต้น: 100)"
    )
    return parser.parse_args()


def run_pipeline(args: Optional[argparse.Namespace] = None) -> None:
    if args is None:
        args = parse_arguments()

    output_dir = Path("outputs")
    output_dir.mkdir(exist_ok=True)
    raw_csv_path = output_dir / "raw_internships.csv"
    ranked_csv_path = output_dir / "ranked_internships.csv"

    # แปลงคีย์เวิร์ดเป็นรายการคำ
    custom_keywords = [k.strip() for k in args.keywords.split(",") if k.strip()]

    print("=" * 60)
    print("[INFO] เริ่มต้นระบบ Ranked Internship Search (ETL Pipeline)")
    print(f"[*] จังหวัดหลัก: {args.province}")
    if not args.no_fallback:
        print(f"[*] จังหวัดสำรอง (Fallback): {args.fallback_province} (หากงาน < {args.min_jobs})")
    print(f"[*] หมวดหมู่: {args.category}")
    print(f"[*] จำนวนงานสูงสุดต่อเว็บ: {args.limit}")
    if custom_keywords:
        print(f"[*] คีย์เวิร์ดบวกคะแนน: {', '.join(custom_keywords)}")
    print("=" * 60)

    scrapers: List[BaseScraper] = [
        JobThaiScraper(),
        JobsDBScraper(),
        DekFuknganScraper(),
        InternTHScraper(),
    ]

    all_jobs: List[Job] = []

    def fetch_for_province(province: str) -> List[Job]:
        print(f"\n[Phase 1] Scraping '{province}' internships from all sources...")
        province_jobs = []
        for scraper in scrapers:
            try:
                jobs = scraper.scrape(
                    target_province=province,
                    limit=args.limit,
                    max_pages=5,
                    category=args.category
                )
                province_jobs.extend(jobs)
                print(f"  [+] {scraper.source_name}: ได้รับ {len(jobs)} งาน")
            except Exception as e:
                print(f"  [!] [warn] {scraper.source_name} failed: {e}")
        return province_jobs

    # 1. ดึงข้อมูลจากจังหวัดเป้าหมายหลัก
    all_jobs.extend(fetch_for_province(args.province))
    print(f"\n[Phase 1] ผลรวมงานจาก '{args.province}': {len(all_jobs)} งาน")

    # 2. ตรวจสอบ Fallback ถ้างานในจังหวัดหลักมีน้อยกว่าเกณฑ์ที่กำหนด
    if not args.no_fallback and len(all_jobs) < args.min_jobs:
        print(
            f"\n[Phase 1] งานใน {args.province} มีเพียง {len(all_jobs)} งาน "
            f"(น้อยกว่าเกณฑ์ขั้นต่ำ {args.min_jobs}) -> กำลังดึง {args.fallback_province} เป็นสำรอง..."
        )
        fallback_jobs = fetch_for_province(args.fallback_province)
        all_jobs.extend(fallback_jobs)

    print(f"\n[Phase 1] รวบรวมงานดิบทั้งหมดได้: {len(all_jobs)} รายการ")

    if not all_jobs:
        print("[!] ไม่พบประกาศงานจากแหล่งข้อมูลใดๆ ยุติการทำงาน")
        return

    # 3. ขจัดข้อมูลซ้ำซ้อนข้ามเว็บไซต์ (Deduplication)
    print("\n[Phase 2] ตรวจสอบและขจัดงานซ้ำซ้อนข้ามเว็บไซต์ (Deduplication)...")
    deduped_jobs, duplicate_count = deduplicate_jobs(all_jobs)
    print(f"[Phase 2] ขจัดงานซ้ำไป {duplicate_count} รายการ (เหลืองานเอกลักษณ์ {len(deduped_jobs)} รายการ)")

    # 4. แปลงเป็น DataFrame และบันทึก Raw Data
    df = jobs_to_dataframe(deduped_jobs)
    df.to_csv(raw_csv_path, index=False, encoding="utf-8-sig")
    print(f"[Phase 2] บันทึกข้อมูลดิบที่ไม่ซ้ำลง -> {raw_csv_path}")

    # 5. คำนวณความใหม่และให้คะแนน (Recency & Keyword Scoring)
    print("\n[Phase 3] คำนวณความสดใหม่ (Days_Ago) และคำนวณคะแนนคีย์เวิร์ด...")
    scored_df = add_recency_and_score(df, custom_keywords=custom_keywords)

    # 6. จัดอันดับแบบ Multi-Level Ranking และส่งออก CSV
    print(f"\n[Phase 4] จัดอันดับ (Ranking) และส่งออกไฟล์ผลลัพธ์ (Top {args.top})...")
    # ลำดับการจัดอันดับ:
    # 1. Custom_Keyword_Score (มากไปน้อย - ตรงกับคำที่ต้องการมากที่สุด)
    # 2. Days_Ago (น้อยไปมาก - โพสต์สดใหม่ที่สุด)
    # 3. Score (มากไปน้อย - เนื้อหาละเอียดที่สุด)
    ranked_df = scored_df.sort_values(
        by=["Custom_Keyword_Score", "Days_Ago", "Score"],
        ascending=[False, True, False]
    )

    ranked_df = ranked_df.head(args.top)

    export_columns = [
        "title",
        "company",
        "location",
        "province",
        "salary",
        "Custom_Keyword_Score",
        "Matched_Keywords",
        "Score",
        "Days_Ago",
        "source",
        "updated_at",
        "url"
    ]

    ranked_df[export_columns].to_csv(ranked_csv_path, index=False, encoding="utf-8-sig")
    print(f"[Phase 4] บันทึกผลการจัดอันดับ {len(ranked_df)} อันดับแรก -> {ranked_csv_path}")
    print("=" * 60)
    print("[SUCCESS] ดำเนินการเสร็จสิ้นสมบูรณ์!")


if __name__ == "__main__":
    run_pipeline()
