import argparse
import re
import sys
from pathlib import Path
from datetime import datetime, timezone
from typing import List, Dict, Tuple, Optional, Callable
from dataclasses import asdict
from concurrent.futures import ThreadPoolExecutor, as_completed

import pandas as pd

from scrapers.base import Job, BaseScraper
from scrapers.jobthai import JobThaiScraper
from scrapers.jobsdb import JobsDBScraper
from scrapers.dekfukngan import DekFuknganScraper
from scrapers.internth import InternTHScraper
from scrapers.linkedin import LinkedInScraper

# ป้องกัน UnicodeEncodeError บน Windows terminal (cp874)
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")


def normalize_text(text: Optional[str]) -> str:
    """
    ทำความสะอาดข้อความ ตัดคำสร้อยบริษัท เครื่องหมายวรรคตอน และช่องว่างส่วนเกิน
    เพื่อใช้เปรียบเทียบหาข้อมูลซ้ำซ้อน (Deduplication)
    """
    if not text:
        return ""
    cleaned = text.lower().strip()

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

    cleaned = re.sub(r"[^\w\s\u0E00-\u0E7F]", " ", cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    return cleaned


def classify_role(title: Optional[str], text: Optional[str]) -> str:
    """
    วิเคราะห์และติดแท็กประเภทสายงาน (Role) โดยอัตโนมัติ
    """
    combined = f"{title or ''} {text or ''}".lower()
    if any(k in combined for k in ["fullstack", "full stack", "full-stack"]):
        return "Fullstack"
    if any(k in combined for k in ["frontend", "front-end", "react", "vue", "angular", "next.js", "html/css"]):
        return "Frontend"
    if any(k in combined for k in ["backend", "back-end", "node", "python", "django", "fastapi", "golang", "go dev", "java", "spring", "c#", ".net", "php", "laravel"]):
        return "Backend"
    if any(k in combined for k in ["data", "analyst", "analytics", "scientist", "ai ", "machine learning", "power bi", "tableau", "sql"]):
        return "Data / AI"
    if any(k in combined for k in ["devops", "cloud", "aws", "azure", "docker", "kubernetes", "infra", "sysadmin"]):
        return "DevOps / Cloud"
    if any(k in combined for k in ["qa", "tester", "test engineer", "automation test", "quality assurance"]):
        return "QA / Tester"
    if any(k in combined for k in ["mobile", "ios", "android", "flutter", "react native", "swift", "kotlin"]):
        return "Mobile"
    if any(k in combined for k in ["ui/ux", "ui / ux", "ux", "ui design", "figma", "graphic", "designer"]):
        return "UI / UX"
    if any(k in combined for k in ["support", "helpdesk", "technician", "network", "system engineer"]):
        return "IT Support"
    return "General IT"


def detect_work_style(text: Optional[str]) -> str:
    """
    ตรวจสอบรูปแบบการทำงาน (Work Style) เช่น WFH, Hybrid, Onsite
    """
    lower = str(text or "").lower()
    if any(k in lower for k in ["work from home", "wfh", "remote", "ทำที่บ้าน"]):
        return "Remote / WFH"
    if any(k in lower for k in ["hybrid", "ไฮบริด"]):
        return "Hybrid"
    return "Onsite"


def detect_paid(salary: Optional[str], text: Optional[str]) -> bool:
    """
    ตรวจสอบว่าประกาศงานมีค่าตอบแทนหรือเบี้ยเลี้ยงหรือไม่
    """
    if isinstance(salary, str) and any(c.isdigit() for c in salary):
        return True
    salary_str = salary if isinstance(salary, str) else ""
    lower = f"{salary_str} {text or ''}".lower()
    paid_keywords = ["เบี้ยเลี้ยง", "stipend", "allowance", "บาท/วัน", "บาท/เดือน", "วันละ", "เดือนละ"]
    return any(k in lower for k in paid_keywords)


def is_senior_or_manager(title: Optional[str], text: Optional[str]) -> bool:
    """
    ตรวจสอบว่าเป็นตำแหน่งระดับ Senior หรือ Manager ที่หลุดเข้ามาหรือไม่
    (หากมีคำว่า intern/ฝึกงาน ระบุไว้ชัดเจนจะไม่นับเป็นงานอาวุโส)
    """
    lower_title = str(title or "").lower()
    intern_keywords = ["intern", "ฝึกงาน", "สหกิจ", "trainee", "นักศึกษา"]
    if any(k in lower_title for k in intern_keywords):
        return False

    negative_keywords = [
        r"\bsenior\b", r"\blead\b", r"\bmanager\b", r"\bdirector\b",
        r"\bvp\b", r"\bhead of\b", r"ผู้จัดการ", r"หัวหน้า",
        r"5\+\s*ปี", r"3\+\s*ปี", r"ประสบการณ์\s*\d+\s*ปี"
    ]
    for pattern in negative_keywords:
        if re.search(pattern, lower_title):
            return True
    return False


def deduplicate_jobs(jobs: List[Job]) -> Tuple[List[Job], int]:
    """
    ขจัดงานซ้ำซ้อนที่ถูกโพสต์ในหลายๆ เว็บ โดยตรวจสอบจาก (ชื่อบริษัท, ชื่อตำแหน่งงาน)
    """
    unique_groups: Dict[Tuple[str, str], List[Job]] = {}

    for job in jobs:
        norm_company = normalize_text(job.company)
        norm_title = normalize_text(job.title)

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

            all_sources = list(dict.fromkeys(j.source for j in job_list if j.source))
            combined_source = ", ".join(all_sources)

            best_job = max(
                job_list,
                key=lambda j: len(j.description or "") + len(j.benefits or "")
            )

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
    คำนวณ Days_Ago, Score, Custom_Keyword_Score, Role, Work_Style, Is_Paid
    """
    if df.empty:
        return df

    now_utc = datetime.now(timezone.utc)
    parsed = pd.to_datetime(df["updated_at"], errors="coerce", utc=True)
    df["Posted_At"] = parsed
    df["Days_Ago"] = (now_utc - parsed).dt.days.fillna(999)

    combined_text = (
        df["title"].fillna("")
        + " "
        + df["description"].fillna("")
        + " "
        + df["benefits"].fillna("")
    )

    df["Score"] = combined_text.str.len()

    # วิเคราะห์ Role, Work Style, Paid
    df["Role"] = [
        classify_role(
            str(row.get("title") or ""),
            str(row.get("description") or "") + " " + str(row.get("benefits") or "")
        )
        for _, row in df.iterrows()
    ]
    df["Work_Style"] = [detect_work_style(text) for text in combined_text]
    df["Is_Paid"] = [
        detect_paid(
            row.get("salary"),
            str(row.get("description") or "") + " " + str(row.get("benefits") or "")
        )
        for _, row in df.iterrows()
    ]

    # คำนวณ Custom Keyword Score
    keywords = [k.strip() for k in (custom_keywords or []) if k.strip()]
    if keywords:
        def match_keywords(text: str) -> Tuple[int, str]:
            text_lower = text.lower()
            matched = [kw for kw in keywords if kw.lower() in text_lower]
            score = len(matched) * 10
            return score, ", ".join(matched) if matched else "-"

        results = combined_text.apply(match_keywords)
        df["Custom_Keyword_Score"] = [r[0] for r in results]
        df["Matched_Keywords"] = [r[1] for r in results]
    else:
        df["Custom_Keyword_Score"] = 0
        df["Matched_Keywords"] = "-"

    return df


def generate_html_dashboard(df: pd.DataFrame, output_path: Path, title: str = "Ranked Internships Dashboard") -> None:
    """
    สร้าง Interactive HTML Dashboard สไตล์ prom-design (Instrument Register)
    มินิมอล ขาว-ดำ-ฟ้า ไม่มี gradient กวาดสายตาอ่านได้ง่าย มีระบบ Favorite ติ๊กงานที่สนใจ
    และแผงควบคุมดึงข้อมูลสด (Live Scrape Monitor) พร้อมตรวจจับสถานะค้าง
    """
    jobs_json = df.to_json(orient="records", force_ascii=False, date_format="iso")

    html_content = f"""<!DOCTYPE html>
<html lang="th">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{title}</title>
    <style>
        :root {{
            --paper: #f8fafc;
            --surface: #ffffff;
            --surface-2: #f1f5f9;
            --line: #e2e8f0;
            --line-strong: #cbd5e1;
            --ink: #0f172a;
            --ink-2: #475569;
            --ink-3: #64748b;
            --signal: #2563eb;
            --signal-hover: #1d4ed8;
            --signal-wash: #eff6ff;
            --signal-border: #bfdbfe;
            --star: #d97706;
            --star-wash: #fffbeb;
            --star-border: #fde68a;
            --success-wash: #ecfdf5;
            --success-text: #065f46;
            --success-border: #a7f3d0;
            --warn-wash: #fffbeb;
            --warn-text: #b45309;
            --warn-border: #fde68a;
            --error-wash: #fef2f2;
            --error-text: #b91c1c;
            --error-border: #fecaca;
            --tabbar-h: 58px;
            --r-control: 8px;
            --r-card: 10px;
        }}
        * {{ box-sizing: border-box; margin: 0; padding: 0; }}
        body {{
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Noto Sans Thai", "Sarabun", sans-serif;
            background-color: var(--paper);
            color: var(--ink);
            line-height: 1.5;
            font-variant-numeric: tabular-nums;
            -webkit-tap-highlight-color: transparent;
            padding: 24px 16px 80px 16px;
        }}
        .container {{
            max-width: 980px;
            margin: 0 auto;
        }}
        /* Header */
        .header {{
            margin-bottom: 20px;
            padding-bottom: 16px;
            border-bottom: 1px solid var(--line);
            display: flex;
            justify-content: space-between;
            align-items: center;
            flex-wrap: wrap;
            gap: 12px;
        }}
        .brand-meta {{
            display: flex;
            flex-direction: column;
        }}
        .brand-eyebrow {{
            font-size: 11px;
            font-weight: 700;
            letter-spacing: 0.08em;
            color: var(--signal);
            text-transform: uppercase;
            margin-bottom: 2px;
        }}
        .header h1 {{
            font-size: 22px;
            font-weight: 700;
            color: var(--ink);
            letter-spacing: -0.02em;
        }}
        .header h1 span {{
            color: var(--signal);
        }}
        .header .subtitle {{
            font-size: 13px;
            color: var(--ink-3);
            margin-top: 2px;
        }}
        .header-actions {{
            display: flex;
            align-items: center;
            gap: 10px;
        }}
        .scrape-trigger-btn {{
            display: inline-flex;
            align-items: center;
            gap: 6px;
            background: var(--signal);
            color: #ffffff;
            border: 1px solid var(--signal);
            padding: 8px 16px;
            border-radius: var(--r-control);
            font-size: 13px;
            font-weight: 600;
            cursor: pointer;
            min-height: 40px;
            touch-action: manipulation;
            transition: background 0.15s ease;
        }}
        .scrape-trigger-btn:hover {{
            background: var(--signal-hover);
        }}
        .scrape-trigger-btn:disabled {{
            opacity: 0.6;
            cursor: not-allowed;
        }}

        /* Live Scrape Monitor Card */
        .scrape-monitor {{
            display: none;
            background: var(--surface);
            border: 1px solid var(--line-strong);
            border-radius: var(--r-card);
            padding: 16px 20px;
            margin-bottom: 20px;
        }}
        .scrape-monitor.is-active {{
            display: block;
        }}
        .monitor-header {{
            display: flex;
            justify-content: space-between;
            align-items: center;
            margin-bottom: 12px;
            padding-bottom: 10px;
            border-bottom: 1px solid var(--line);
        }}
        .monitor-title {{
            font-size: 14px;
            font-weight: 700;
            color: var(--ink);
            display: flex;
            align-items: center;
            gap: 8px;
        }}
        .pulse-dot {{
            width: 8px;
            height: 8px;
            border-radius: 50%;
            background: var(--signal);
            display: inline-block;
        }}
        .pulse-dot.running {{
            box-shadow: 0 0 0 4px var(--signal-wash);
            animation: pulseAnim 1.4s infinite;
        }}
        @keyframes pulseAnim {{
            0% {{ transform: scale(0.95); opacity: 0.8; }}
            50% {{ transform: scale(1.15); opacity: 1; }}
            100% {{ transform: scale(0.95); opacity: 0.8; }}
        }}
        .monitor-close-btn {{
            background: none;
            border: none;
            color: var(--ink-3);
            font-size: 18px;
            cursor: pointer;
            padding: 4px;
            line-height: 1;
        }}
        .watchdog-warning {{
            display: none;
            background: var(--warn-wash);
            border: 1px solid var(--warn-border);
            color: var(--warn-text);
            padding: 10px 14px;
            border-radius: var(--r-control);
            font-size: 13px;
            margin-bottom: 12px;
            line-height: 1.4;
        }}
        .sources-grid {{
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(160px, 1fr));
            gap: 8px;
            margin-bottom: 12px;
        }}
        .source-card {{
            background: var(--surface-2);
            border: 1px solid var(--line);
            border-radius: var(--r-control);
            padding: 8px 12px;
            font-size: 12px;
        }}
        .source-card-name {{
            font-weight: 600;
            color: var(--ink);
            margin-bottom: 4px;
            display: flex;
            justify-content: space-between;
        }}
        .source-card-status {{
            color: var(--ink-3);
        }}
        .monitor-footer {{
            display: flex;
            justify-content: space-between;
            align-items: center;
            font-size: 12px;
            color: var(--ink-3);
            padding-top: 8px;
        }}

        /* Controls & Filter Rows */
        .controls {{
            display: flex;
            flex-direction: column;
            gap: 10px;
            margin-bottom: 16px;
        }}
        .search-box-wrap {{
            position: relative;
            width: 100%;
        }}
        .search-box {{
            width: 100%;
            padding: 12px 16px;
            background: var(--surface);
            border: 1px solid var(--line);
            border-radius: var(--r-control);
            font-size: 14px;
            color: var(--ink);
            outline: none;
            transition: border-color 0.15s ease;
        }}
        .search-box:focus {{
            border-color: var(--signal);
        }}
        .filter-row {{
            display: flex;
            flex-wrap: wrap;
            gap: 6px;
            align-items: center;
        }}
        .filter-label {{
            font-size: 13px;
            font-weight: 600;
            color: var(--ink-2);
            margin-right: 2px;
        }}
        .filter-btn {{
            background: var(--surface);
            border: 1px solid var(--line);
            color: var(--ink-2);
            padding: 6px 12px;
            border-radius: var(--r-control);
            font-size: 13px;
            font-weight: 500;
            cursor: pointer;
            transition: all 0.15s ease;
            user-select: none;
            min-height: 36px;
            display: inline-flex;
            align-items: center;
            gap: 4px;
            touch-action: manipulation;
        }}
        .filter-btn:hover {{
            background: var(--surface-2);
            color: var(--ink);
        }}
        .filter-btn.active {{
            background: var(--signal);
            color: #ffffff;
            border-color: var(--signal);
        }}
        .filter-btn.fav-filter.active {{
            background: var(--star);
            color: #ffffff;
            border-color: var(--star);
        }}
        .count-pill {{
            font-size: 11px;
            padding: 1px 6px;
            border-radius: 999px;
            background: var(--surface-2);
            color: var(--ink-2);
            font-weight: 600;
        }}
        .filter-btn.active .count-pill {{
            background: rgba(255, 255, 255, 0.25);
            color: #ffffff;
        }}

        /* Stats bar */
        .stats-bar {{
            font-size: 13px;
            color: var(--ink-3);
            margin-bottom: 14px;
            display: flex;
            justify-content: space-between;
            align-items: center;
            flex-wrap: wrap;
            gap: 6px;
        }}

        /* Linear Job List */
        .job-list {{
            display: flex;
            flex-direction: column;
            gap: 10px;
        }}
        .job-item {{
            background: var(--surface);
            border: 1px solid var(--line);
            border-radius: var(--r-card);
            padding: 14px 18px;
            display: grid;
            grid-template-columns: 44px 1fr auto;
            align-items: center;
            gap: 16px;
            transition: border-color 0.15s ease;
        }}
        .job-item:hover {{
            border-color: var(--line-strong);
        }}
        .job-rank {{
            font-size: 13px;
            font-weight: 700;
            color: var(--ink-3);
            text-align: center;
            background: var(--surface-2);
            padding: 8px 0;
            border-radius: var(--r-control);
            border: 1px solid var(--line);
        }}
        .job-rank.top-rank {{
            background: var(--signal-wash);
            color: var(--signal);
            border-color: var(--signal-border);
        }}
        .job-info {{
            min-width: 0;
        }}
        .job-title {{
            font-size: 16px;
            font-weight: 600;
            color: var(--ink);
            margin-bottom: 4px;
            white-space: nowrap;
            overflow: hidden;
            text-overflow: ellipsis;
        }}
        .job-company-row {{
            font-size: 14px;
            color: var(--ink-2);
            margin-bottom: 6px;
            display: flex;
            align-items: center;
            gap: 8px;
            flex-wrap: wrap;
        }}
        .job-company {{
            font-weight: 500;
            color: var(--ink);
        }}
        .tags-row {{
            display: flex;
            gap: 6px;
            flex-wrap: wrap;
            align-items: center;
        }}
        .badge {{
            font-size: 12px;
            font-weight: 500;
            padding: 2px 8px;
            border-radius: 4px;
            background: var(--surface-2);
            color: var(--ink-2);
            border: 1px solid var(--line);
        }}
        .badge.province-kk {{
            background: var(--signal-wash);
            color: var(--signal);
            border-color: var(--signal-border);
            font-weight: 600;
        }}
        .badge.paid {{
            background: var(--success-wash);
            color: var(--success-text);
            border-color: var(--success-border);
        }}
        .badge.keyword {{
            background: #fef2f2;
            color: #b91c1c;
            border-color: #fecaca;
        }}
        .badge.blue {{
            background: var(--signal-wash);
            color: var(--signal);
            border-color: var(--signal-border);
        }}
        .job-action {{
            display: flex;
            align-items: center;
            gap: 10px;
        }}
        .job-time {{
            font-size: 12px;
            color: var(--ink-3);
            white-space: nowrap;
        }}
        .fav-btn {{
            background: var(--surface);
            border: 1px solid var(--line);
            color: var(--ink-3);
            width: 44px;
            height: 44px;
            border-radius: var(--r-control);
            display: inline-flex;
            align-items: center;
            justify-content: center;
            cursor: pointer;
            font-size: 18px;
            touch-action: manipulation;
            transition: all 0.15s ease;
        }}
        .fav-btn:hover {{
            border-color: var(--star);
            color: var(--star);
        }}
        .fav-btn.is-active {{
            background: var(--star-wash);
            border-color: var(--star-border);
            color: var(--star);
        }}
        .apply-btn {{
            display: inline-flex;
            align-items: center;
            justify-content: center;
            background: var(--signal);
            color: #ffffff;
            font-size: 13px;
            font-weight: 600;
            text-decoration: none;
            padding: 0 16px;
            height: 44px;
            border-radius: var(--r-control);
            border: 1px solid var(--signal);
            white-space: nowrap;
            touch-action: manipulation;
            transition: all 0.15s ease;
        }}
        .apply-btn:hover {{
            background: var(--signal-hover);
            border-color: var(--signal-hover);
        }}
        .apply-btn.visited {{
            background: #cbd5e1;
            color: #475569;
            border: 1px solid #94a3b8;
        }}
        .apply-btn.visited:hover {{
            background: #94a3b8;
            color: #0f172a;
        }}

        /* Empty state */
        .empty-state {{
            text-align: center;
            padding: 48px 16px;
            color: var(--ink-3);
            background: var(--surface);
            border: 1px solid var(--line);
            border-radius: var(--r-card);
        }}
        .empty-state h3 {{
            font-size: 16px;
            color: var(--ink);
            margin-bottom: 6px;
        }}

        /* Server Connection Modal */
        .modal-scrim {{
            display: none;
            position: fixed;
            inset: 0;
            background: rgba(15, 23, 42, 0.5);
            z-index: 50;
            align-items: center;
            justify-content: center;
            padding: 16px;
        }}
        .modal-scrim.is-open {{
            display: flex;
        }}
        .modal-card {{
            background: var(--surface);
            border: 1px solid var(--line-strong);
            border-radius: var(--r-card);
            padding: 24px;
            max-width: 480px;
            width: 100%;
        }}
        .modal-card h3 {{
            font-size: 18px;
            color: var(--ink);
            margin-bottom: 8px;
        }}
        .modal-card p {{
            font-size: 14px;
            color: var(--ink-2);
            margin-bottom: 12px;
            line-height: 1.5;
        }}
        .code-box {{
            background: var(--surface-2);
            border: 1px solid var(--line);
            padding: 10px 14px;
            border-radius: var(--r-control);
            font-family: monospace;
            font-size: 13px;
            color: var(--ink);
            margin-bottom: 16px;
            user-select: all;
        }}
        .modal-actions {{
            display: flex;
            justify-content: flex-end;
            gap: 10px;
        }}
        .btn-secondary {{
            background: var(--surface);
            border: 1px solid var(--line);
            color: var(--ink-2);
            padding: 8px 16px;
            border-radius: var(--r-control);
            font-size: 13px;
            cursor: pointer;
            min-height: 40px;
        }}

        /* Mobile Bottom Tab Bar (prom-design Playbook) */
        .tabbar {{
            display: none;
            position: fixed;
            inset: auto 0 0 0;
            z-index: 45;
            height: calc(var(--tabbar-h) + env(safe-area-inset-bottom));
            padding-bottom: env(safe-area-inset-bottom);
            background: var(--surface);
            border-top: 1px solid var(--line);
            grid-auto-flow: column;
            grid-auto-columns: 1fr;
        }}
        .tab-item {{
            display: flex;
            flex-direction: column;
            align-items: center;
            justify-content: center;
            gap: 2px;
            font-size: 11px;
            font-weight: 500;
            color: var(--ink-3);
            background: none;
            border: none;
            cursor: pointer;
            min-height: 48px;
            touch-action: manipulation;
        }}
        .tab-item.active {{
            color: var(--signal);
            font-weight: 700;
        }}
        .tab-icon {{
            font-size: 16px;
        }}

        @media (max-width: 768px) {{
            .tabbar {{
                display: grid;
            }}
            body {{
                padding-bottom: calc(var(--tabbar-h) + env(safe-area-inset-bottom) + 32px);
            }}
            .job-item {{
                grid-template-columns: 36px 1fr;
                gap: 12px;
            }}
            .job-action {{
                grid-column: 2;
                justify-content: space-between;
                width: 100%;
                margin-top: 8px;
                padding-top: 8px;
                border-top: 1px solid var(--line);
            }}
            .scrape-trigger-btn.desktop-only {{
                display: none;
            }}
        }}
    </style>
</head>
<body>
    <div class="container">
        <header class="header">
            <div class="brand-meta">
                <div class="brand-eyebrow">IT and Software Engineering</div>
                <h1>Ranked <span>Internships</span></h1>
                <div class="subtitle">ระบบจัดอันดับงานฝึกงาน (เรียงพื้นที่เป้าหมายก่อน · ตรวจสอบ 5 แหล่งข้อมูล)</div>
            </div>
            <div class="header-actions">
                <button class="scrape-trigger-btn desktop-only" id="desktopScrapeBtn" onclick="triggerScrape()">
                    <span>🔄</span> ดึงข้อมูลสด
                </button>
                <div class="subtitle" id="lastUpdatedText">อัปเดต: {datetime.now().strftime('%d/%m/%Y %H:%M')}</div>
            </div>
        </header>

        <!-- Live Scrape Monitor Card -->
        <section class="scrape-monitor" id="scrapeMonitor" aria-live="polite">
            <div class="monitor-header">
                <div class="monitor-title">
                    <span class="pulse-dot" id="monitorDot"></span>
                    <span id="monitorStatusText">ระบบกวาดข้อมูลสด (Live Data Engine)</span>
                </div>
                <button class="monitor-close-btn" onclick="closeMonitor()" title="ปิดหน้าต่าง">✕</button>
            </div>

            <div class="watchdog-warning" id="watchdogWarning">
                ⚠️ บางเว็บไซต์ใช้เวลาตอบสนองนานกว่าปกติ: ระบบกำลังรัน Retry หรือเตรียมข้ามอัตโนมัติ ไม่ต้องกังวลว่าระบบจะค้าง
            </div>

            <div class="sources-grid" id="sourcesGrid">
                <div class="source-card" id="src-LinkedIn">
                    <div class="source-card-name"><span>LinkedIn</span> <span id="cnt-LinkedIn">0</span></div>
                    <div class="source-card-status" id="st-LinkedIn">รอดำเนินการ</div>
                </div>
                <div class="source-card" id="src-JobThai">
                    <div class="source-card-name"><span>JobThai</span> <span id="cnt-JobThai">0</span></div>
                    <div class="source-card-status" id="st-JobThai">รอดำเนินการ</div>
                </div>
                <div class="source-card" id="src-JobsDB">
                    <div class="source-card-name"><span>JobsDB</span> <span id="cnt-JobsDB">0</span></div>
                    <div class="source-card-status" id="st-JobsDB">รอดำเนินการ</div>
                </div>
                <div class="source-card" id="src-DekFukngan">
                    <div class="source-card-name"><span>เด็กฝึกงาน</span> <span id="cnt-DekFukngan">0</span></div>
                    <div class="source-card-status" id="st-DekFukngan">รอดำเนินการ</div>
                </div>
                <div class="source-card" id="src-InternTH">
                    <div class="source-card-name"><span>InternTH</span> <span id="cnt-InternTH">0</span></div>
                    <div class="source-card-status" id="st-InternTH">รอดำเนินการ</div>
                </div>
            </div>

            <div class="monitor-footer">
                <span id="monitorLogMessage">พร้อมเริ่มการดึงข้อมูลรอบใหม่</span>
                <span id="monitorElapsed">เวลาที่ใช้: 0s</span>
            </div>
        </section>

        <!-- Filters & Search Controls -->
        <section class="controls">
            <div class="search-box-wrap">
                <input type="text" id="searchInput" class="search-box" placeholder="พิมพ์ค้นหาตำแหน่ง, บริษัท, หรือทักษะที่สนใจ (เช่น React, Python, Data, QA)...">
            </div>

            <div class="filter-row" id="quickFilters">
                <span class="filter-label">ตัวกรอง:</span>
                <button class="filter-btn active" id="filterAll">ทั้งหมด <span class="count-pill" id="pillAll">0</span></button>
                <button class="filter-btn fav-filter" id="filterFav">⭐ ที่สนใจ <span class="count-pill" id="pillFav">0</span></button>
                <button class="filter-btn" id="filterKK">📍 เฉพาะขอนแก่น</button>
                <button class="filter-btn" id="filterPaid">💰 มีเบี้ยเลี้ยง</button>
                <button class="filter-btn" id="filterWFH">🏠 Work From Home</button>
            </div>

            <div class="filter-row" id="roleFilters">
                <span class="filter-label">สายงาน:</span>
                <button class="filter-btn active" data-role="all">ทั้งหมด</button>
                <button class="filter-btn" data-role="Frontend">Frontend</button>
                <button class="filter-btn" data-role="Backend">Backend</button>
                <button class="filter-btn" data-role="Fullstack">Fullstack</button>
                <button class="filter-btn" data-role="Data / AI">Data / AI</button>
                <button class="filter-btn" data-role="DevOps / Cloud">DevOps</button>
                <button class="filter-btn" data-role="QA / Tester">QA</button>
                <button class="filter-btn" data-role="Mobile">Mobile</button>
                <button class="filter-btn" data-role="UI / UX">UI/UX</button>
                <button class="filter-btn" data-role="IT Support">IT Support</button>
            </div>
        </section>

        <!-- Stats row -->
        <div class="stats-bar">
            <span id="statsCount">กำลังโหลดข้อมูล...</span>
            <span>เรียงลำดับ: ขอนแก่นขึ้นก่อน · ความตรงคีย์เวิร์ด · ความสดใหม่</span>
        </div>

        <!-- Linear Job List -->
        <main class="job-list" id="jobList"></main>
    </div>

    <!-- Server Connection Guide Modal -->
    <div class="modal-scrim" id="serverModal" role="dialog" aria-modal="true" aria-labelledby="modalTitle">
        <div class="modal-card">
            <h3 id="modalTitle">⚡ เชื่อมต่อเซิร์ฟเวอร์ดึงข้อมูลในเครื่อง</h3>
            <p>
                ปุ่มดึงข้อมูลสดต้องการให้รัน Local Server ในโฟลเดอร์โปรเจกต์ เพื่อรันกระบวนการ Scrape และแสดงสถานะแบบ Real-time
            </p>
            <p><strong>วิธีเปิดใช้งาน:</strong> เปิด Command Prompt หรือ Terminal แล้วรันคำสั่ง:</p>
            <div class="code-box">python server.py</div>
            <p style="font-size: 12px; color: var(--ink-3);">
                เมื่อรันคำสั่งแล้ว เซิร์ฟเวอร์จะเปิดที่ http://localhost:8000 จากนั้นกดปุ่มลองเชื่อมต่อใหม่ได้ทันที
            </p>
            <div class="modal-actions">
                <button class="btn-secondary" onclick="closeServerModal()">ปิด</button>
                <button class="scrape-trigger-btn" onclick="retryServerConnection()">ลองเชื่อมต่อใหม่</button>
            </div>
        </div>
    </div>

    <!-- Mobile Bottom Tab Bar -->
    <nav class="tabbar" role="navigation" aria-label="เมนูการนำทางหลัก">
        <button class="tab-item active" id="tabAll" onclick="selectTab('all')">
            <span class="tab-icon">💼</span>
            <span>งานทั้งหมด</span>
        </button>
        <button class="tab-item" id="tabKK" onclick="selectTab('kk')">
            <span class="tab-icon">📍</span>
            <span>ขอนแก่น</span>
        </button>
        <button class="tab-item" id="tabFav" onclick="selectTab('fav')">
            <span class="tab-icon">⭐</span>
            <span>ที่สนใจ (<span id="tabFavCount">0</span>)</span>
        </button>
        <button class="tab-item" id="tabScrape" onclick="triggerScrape()">
            <span class="tab-icon">🔄</span>
            <span>ดึงข้อมูล</span>
        </button>
    </nav>

    <script>
        let jobs = {jobs_json};
        let selectedRole = "all";
        let onlyKK = false;
        let onlyPaid = false;
        let onlyWFH = false;
        let onlyFav = false;
        let searchQuery = "";

        const FAV_STORAGE_KEY = "ranked_internship_favorites_v1";
        const VISITED_STORAGE_KEY = "ranked_internship_visited_urls";

        // Local Storage Helpers
        function getFavorites() {{
            try {{
                return JSON.parse(localStorage.getItem(FAV_STORAGE_KEY)) || [];
            }} catch (e) {{
                return [];
            }}
        }}

        function toggleFavorite(url, event) {{
            if (event) event.stopPropagation();
            try {{
                let favs = getFavorites();
                const index = favs.indexOf(url);
                if (index > -1) {{
                    favs.splice(index, 1);
                }} else {{
                    favs.push(url);
                }}
                localStorage.setItem(FAV_STORAGE_KEY, JSON.stringify(favs));
                updateFavCounts();
                render();
            }} catch (e) {{
                console.error("Favorite toggle error:", e);
            }}
        }}

        function getVisitedUrls() {{
            try {{
                return JSON.parse(localStorage.getItem(VISITED_STORAGE_KEY)) || [];
            }} catch (e) {{
                return [];
            }}
        }}

        function markUrlVisited(url) {{
            try {{
                const visited = getVisitedUrls();
                if (!visited.includes(url)) {{
                    visited.push(url);
                    localStorage.setItem(VISITED_STORAGE_KEY, JSON.stringify(visited));
                }}
            }} catch (e) {{}}
        }}

        function handleApplyClick(btn, rawUrl) {{
            markUrlVisited(rawUrl);
            btn.classList.add("visited");
            btn.innerText = "ดูแล้ว ✓";
        }}

        function updateFavCounts() {{
            const favs = getFavorites();
            const count = favs.length;
            const pillFav = document.getElementById("pillFav");
            const tabFavCount = document.getElementById("tabFavCount");
            if (pillFav) pillFav.innerText = count;
            if (tabFavCount) tabFavCount.innerText = count;
        }}

        // DOM References
        const searchInput = document.getElementById("searchInput");
        const jobList = document.getElementById("jobList");
        const statsCount = document.getElementById("statsCount");
        const pillAll = document.getElementById("pillAll");

        // Scrape Monitor Elements
        const scrapeMonitor = document.getElementById("scrapeMonitor");
        const monitorDot = document.getElementById("monitorDot");
        const monitorStatusText = document.getElementById("monitorStatusText");
        const monitorLogMessage = document.getElementById("monitorLogMessage");
        const monitorElapsed = document.getElementById("monitorElapsed");
        const watchdogWarning = document.getElementById("watchdogWarning");
        const serverModal = document.getElementById("serverModal");
        const desktopScrapeBtn = document.getElementById("desktopScrapeBtn");

        let pollInterval = null;
        const API_BASE = window.location.origin.startsWith("http") ? window.location.origin : "http://localhost:8000";

        function closeMonitor() {{
            scrapeMonitor.classList.remove("is-active");
        }}

        function closeServerModal() {{
            serverModal.classList.remove("is-open");
        }}

        async function triggerScrape() {{
            scrapeMonitor.classList.add("is-active");
            monitorDot.classList.add("running");
            monitorStatusText.innerText = "กำลังเชื่อมต่อเพื่อดึงข้อมูลสด...";
            desktopScrapeBtn.disabled = true;

            try {{
                const res = await fetch(`${{API_BASE}}/api/scrape`, {{
                    method: "POST",
                    headers: {{ "Content-Type": "application/json" }}
                }});

                if (!res.ok && res.status !== 409) {{
                    throw new Error("HTTP " + res.status);
                }}

                startPollingStatus();
            }} catch (err) {{
                desktopScrapeBtn.disabled = false;
                monitorDot.classList.remove("running");
                monitorStatusText.innerText = "ไม่สามารถเชื่อมต่อ Local Server ได้";
                serverModal.classList.add("is-open");
            }}
        }}

        async function retryServerConnection() {{
            closeServerModal();
            triggerScrape();
        }}

        function startPollingStatus() {{
            if (pollInterval) clearInterval(pollInterval);
            pollInterval = setInterval(checkStatus, 900);
            checkStatus();
        }}

        async function checkStatus() {{
            try {{
                const res = await fetch(`${{API_BASE}}/api/status`);
                if (!res.ok) return;
                const data = await res.json();

                monitorElapsed.innerText = `เวลาที่ใช้: ${{data.elapsed_seconds || 0}}s`;
                monitorLogMessage.innerText = data.message || "กำลังประมวลผล...";

                if (data.is_stuck) {{
                    watchdogWarning.style.display = "block";
                }} else {{
                    watchdogWarning.style.display = "none";
                }}

                if (data.sources) {{
                    for (const [src, sinfo] of Object.entries(data.sources)) {{
                        const cntEl = document.getElementById(`cnt-${{src}}`);
                        const stEl = document.getElementById(`st-${{src}}`);
                        if (cntEl) cntEl.innerText = `${{sinfo.count || 0}} งาน`;
                        if (stEl) {{
                            if (sinfo.status === "running") {{
                                stEl.innerText = "⏳ กำลังดึงข้อมูล...";
                                stEl.style.color = "var(--signal)";
                            }} else if (sinfo.status === "done") {{
                                stEl.innerText = "✓ สำเร็จ";
                                stEl.style.color = "var(--success-text)";
                            }} else if (sinfo.status === "error") {{
                                stEl.innerText = "⚠️ ข้าม (Rate Limit)";
                                stEl.style.color = "var(--warn-text)";
                            }} else {{
                                stEl.innerText = "รอดำเนินการ";
                                stEl.style.color = "var(--ink-3)";
                            }}
                        }}
                    }}
                }}

                if (!data.running) {{
                    clearInterval(pollInterval);
                    pollInterval = null;
                    desktopScrapeBtn.disabled = false;
                    monitorDot.classList.remove("running");
                    monitorStatusText.innerText = data.error ? "เกิดข้อผิดพลาดในการดึงข้อมูล" : "ดึงข้อมูลและจัดอันดับสำเร็จ!";
                    watchdogWarning.style.display = "none";

                    if (!data.error) {{
                        await reloadJobs();
                    }}
                }}
            }} catch (e) {{
                // หากหยุดเชื่อมต่อชั่วคราว
            }}
        }}

        async function reloadJobs() {{
            try {{
                const res = await fetch(`${{API_BASE}}/api/jobs`);
                if (!res.ok) return;
                const freshJobs = await res.json();
                if (Array.isArray(freshJobs) && freshJobs.length > 0) {{
                    jobs = freshJobs;
                    const now = new Date();
                    const timeStr = `${{now.getDate().toString().padStart(2, '0')}}/${{(now.getMonth()+1).toString().padStart(2, '0')}}/${{now.getFullYear()}} ${{now.getHours().toString().padStart(2, '0')}}:${{now.getMinutes().toString().padStart(2, '0')}}`;
                    document.getElementById("lastUpdatedText").innerText = `อัปเดต: ${{timeStr}}`;
                    render();
                }}
            }} catch (e) {{
                console.warn("Reload jobs failed:", e);
            }}
        }}

        // Mobile Tab Selection
        function selectTab(tab) {{
            document.querySelectorAll(".tab-item").forEach(t => t.classList.remove("active"));
            const target = document.getElementById("tab" + tab.charAt(0).toUpperCase() + tab.slice(1));
            if (target) target.classList.add("active");

            if (tab === "all") {{
                onlyFav = false;
                onlyKK = false;
                document.getElementById("filterAll").classList.add("active");
                document.getElementById("filterFav").classList.remove("active");
                document.getElementById("filterKK").classList.remove("active");
            }} else if (tab === "kk") {{
                onlyFav = false;
                onlyKK = true;
                document.getElementById("filterAll").classList.remove("active");
                document.getElementById("filterFav").classList.remove("active");
                document.getElementById("filterKK").classList.add("active");
            }} else if (tab === "fav") {{
                onlyFav = true;
                document.getElementById("filterAll").classList.remove("active");
                document.getElementById("filterFav").classList.add("active");
            }}
            render();
        }}

        // Main Render Function
        function render() {{
            const visitedList = getVisitedUrls();
            const favoritesList = getFavorites();
            if (pillAll) pillAll.innerText = jobs.length;

            const filtered = jobs.filter(j => {{
                if (onlyFav && !favoritesList.includes(j.url)) return false;
                if (selectedRole !== "all" && j.Role !== selectedRole) return false;
                if (onlyKK) {{
                    const prov = (j.province || j.location || "").toLowerCase();
                    if (!prov.includes("khon kaen") && !prov.includes("ขอนแก่น")) return false;
                }}
                if (onlyPaid && !j.Is_Paid) return false;
                if (onlyWFH && j.Work_Style !== "Remote / WFH" && j.Work_Style !== "Hybrid") return false;
                if (searchQuery) {{
                    const q = searchQuery.toLowerCase();
                    const text = (j.title + " " + j.company + " " + j.location + " " + (j.Matched_Keywords || "") + " " + (j.Role || "")).toLowerCase();
                    if (!text.includes(q)) return false;
                }}
                return true;
            }});

            statsCount.innerText = `แสดง ${{filtered.length}} จากทั้งหมด ${{jobs.length}} รายการ`;
            jobList.innerHTML = "";

            if (filtered.length === 0) {{
                if (onlyFav) {{
                    jobList.innerHTML = `
                        <div class="empty-state">
                            <h3>ยังไม่มีตำแหน่งงานที่บันทึกไว้ในรายการโปรด</h3>
                            <p>แตะที่ไอคอนรูปดาว ⭐ บนการ์ดงานใดก็ได้ เพื่อบันทึกงานที่คุณสนใจไว้ดูภายหลัง</p>
                        </div>
                    `;
                }} else {{
                    jobList.innerHTML = `
                        <div class="empty-state">
                            <h3>ไม่พบตำแหน่งงานที่ตรงกับเงื่อนไขการค้นหา</h3>
                            <p>ลองปรับคำค้นหาหรือเปลี่ยนตัวกรองสายงานเพื่อดูตำแหน่งงานเพิ่มเติม</p>
                        </div>
                    `;
                }}
                return;
            }}

            filtered.forEach((j, idx) => {{
                const item = document.createElement("div");
                item.className = "job-item";

                const isKK = (j.province || j.location || "").toLowerCase().includes("khon kaen") || (j.province || j.location || "").includes("ขอนแก่น");
                const provBadgeClass = isKK ? "badge province-kk" : "badge";
                const provText = isKK ? "📍 ขอนแก่น" : `📍 ${{j.province || j.location}}`;

                const daysAgo = Math.round(j.Days_Ago);
                const timeText = j.Days_Ago < 999 ? (daysAgo === 0 ? "วันนี้" : `${{daysAgo}} วันที่แล้ว`) : "ไม่ระบุวัน";

                const paidBadge = j.Is_Paid ? '<span class="badge paid">💰 มีเบี้ยเลี้ยง</span>' : '';
                const kwBadge = (j.Matched_Keywords && j.Matched_Keywords !== "-") ? `<span class="badge keyword">⭐ ${{j.Matched_Keywords}}</span>` : '';
                const wfhBadge = (j.Work_Style && j.Work_Style !== "Onsite") ? `<span class="badge blue">🏠 ${{j.Work_Style}}</span>` : '';

                const isVisited = visitedList.includes(j.url);
                const btnClass = isVisited ? "apply-btn visited" : "apply-btn";
                const btnText = isVisited ? "ดูแล้ว ✓" : "ดูงาน ↗";

                const isFav = favoritesList.includes(j.url);
                const favBtnClass = isFav ? "fav-btn is-active" : "fav-btn";
                const favIcon = isFav ? "★" : "☆";

                item.innerHTML = `
                    <div class="job-rank ${{idx < 3 ? 'top-rank' : ''}}">#${{idx + 1}}</div>
                    <div class="job-info">
                        <div class="job-title" title="${{j.title}}">${{j.title}}</div>
                        <div class="job-company-row">
                            <span class="job-company">${{j.company || "ไม่ระบุชื่อบริษัท"}}</span>
                            <span class="${{provBadgeClass}}">${{provText}}</span>
                        </div>
                        <div class="tags-row">
                            <span class="badge">${{j.Role || "General IT"}}</span>
                            <span class="badge">${{j.source}}</span>
                            ${{paidBadge}}
                            ${{kwBadge}}
                            ${{wfhBadge}}
                        </div>
                    </div>
                    <div class="job-action">
                        <button class="${{favBtnClass}}" onclick="toggleFavorite('${{j.url.replace(/'/g, "\\\\'") }}', event)" title="บันทึกรายการที่สนใจ" aria-label="บันทึกรายการที่สนใจ">${{favIcon}}</button>
                        <span class="job-time">🕒 ${{timeText}}</span>
                        <a href="${{j.url}}" target="_blank" rel="noopener noreferrer" class="${{btnClass}}" onclick="handleApplyClick(this, '${{j.url.replace(/'/g, "\\\\'") }}')">${{btnText}}</a>
                    </div>
                `;
                jobList.appendChild(item);
            }});
        }}

        // Search Input Listener
        searchInput.addEventListener("input", (e) => {{
            searchQuery = e.target.value.trim();
            render();
        }});

        // Role Filter Listeners
        document.querySelectorAll("#roleFilters .filter-btn").forEach(btn => {{
            btn.addEventListener("click", () => {{
                document.querySelectorAll("#roleFilters .filter-btn").forEach(b => b.classList.remove("active"));
                btn.classList.add("active");
                selectedRole = btn.dataset.role;
                render();
            }});
        }});

        // Quick Filters Listeners
        const filterAll = document.getElementById("filterAll");
        filterAll.addEventListener("click", () => {{
            onlyFav = false;
            onlyKK = false;
            filterAll.classList.add("active");
            filterFav.classList.remove("active");
            filterKK.classList.remove("active");
            render();
        }});

        const filterFav = document.getElementById("filterFav");
        filterFav.addEventListener("click", () => {{
            onlyFav = !onlyFav;
            filterFav.classList.toggle("active", onlyFav);
            if (onlyFav) filterAll.classList.remove("active");
            render();
        }});

        const filterKK = document.getElementById("filterKK");
        filterKK.addEventListener("click", () => {{
            onlyKK = !onlyKK;
            filterKK.classList.toggle("active", onlyKK);
            if (onlyKK) filterAll.classList.remove("active");
            render();
        }});

        const filterPaid = document.getElementById("filterPaid");
        filterPaid.addEventListener("click", () => {{
            onlyPaid = !onlyPaid;
            filterPaid.classList.toggle("active", onlyPaid);
            render();
        }});

        const filterWFH = document.getElementById("filterWFH");
        filterWFH.addEventListener("click", () => {{
            onlyWFH = !onlyWFH;
            filterWFH.classList.toggle("active", onlyWFH);
            render();
        }});

        // Initial setup
        updateFavCounts();
        render();
    </script>
</body>
</html>"""

    output_path.write_text(html_content, encoding="utf-8")
    print(f"[Phase 4] สร้าง prom-design Dashboard สำเร็จ -> {output_path}")


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
        "--role",
        type=str,
        default="",
        help="กรองเฉพาะสายงาน เช่น 'frontend', 'backend', 'data', 'fullstack', 'qa'"
    )
    parser.add_argument(
        "--paid-only",
        action="store_true",
        help="เอาเฉพาะงานที่มีค่าตอบแทนหรือเบี้ยเลี้ยง"
    )
    parser.add_argument(
        "--wfh",
        action="store_true",
        help="เอาเฉพาะงานที่เป็น Remote / Work From Home หรือ Hybrid"
    )
    parser.add_argument(
        "--no-strict-intern",
        action="store_true",
        help="ปิดการกรองงาน Senior/Manager (เก็บงานทั้งหมดไว้)"
    )
    parser.add_argument(
        "--top",
        type=int,
        default=100,
        help="จำนวนงานที่จะ Export ลงใน ranked_internships.csv (ค่าเริ่มต้น: 100)"
    )
    return parser.parse_args()


def run_pipeline(
    args: Optional[argparse.Namespace] = None,
    progress_callback: Optional[Callable[[str, Dict], None]] = None
) -> pd.DataFrame:
    if args is None:
        args = parse_arguments()

    def notify(stage: str, data: Optional[Dict] = None) -> None:
        if progress_callback:
            try:
                progress_callback(stage, data or {})
            except Exception:
                pass

    output_dir = Path("outputs")
    output_dir.mkdir(exist_ok=True)
    raw_csv_path = output_dir / "raw_internships.csv"
    ranked_csv_path = output_dir / "ranked_internships.csv"
    dashboard_html_path = output_dir / "dashboard.html"

    custom_keywords = [k.strip() for k in args.keywords.split(",") if k.strip()]

    print("=" * 60)
    print("[INFO] เริ่มต้นระบบ Ranked Internship Search (ETL Pipeline - Parallel Engine)")
    print(f"[*] จังหวัดหลัก: {args.province}")
    if not args.no_fallback:
        print(f"[*] จังหวัดสำรอง (Fallback): {args.fallback_province} (หากงาน < {args.min_jobs})")
    print(f"[*] หมวดหมู่: {args.category}")
    print(f"[*] จำนวนงานสูงสุดต่อเว็บ: {args.limit}")
    if custom_keywords:
        print(f"[*] คีย์เวิร์ดบวกคะแนน: {', '.join(custom_keywords)}")
    if args.role:
        print(f"[*] กรองเฉพาะ Role: {args.role}")
    if args.paid_only:
        print("[*] กรองเฉพาะงานที่มีเบี้ยเลี้ยง (--paid-only)")
    if args.wfh:
        print("[*] กรองเฉพาะงาน WFH / Remote (--wfh)")
    print("=" * 60)

    notify("start", {
        "province": args.province,
        "fallback_province": args.fallback_province,
        "category": args.category,
        "limit": args.limit,
    })

    scrapers: List[BaseScraper] = [
        JobThaiScraper(),
        JobsDBScraper(),
        DekFuknganScraper(),
        InternTHScraper(),
        LinkedInScraper(),
    ]

    all_jobs: List[Job] = []

    def fetch_for_province_parallel(province: str) -> List[Job]:
        print(f"\n[Phase 1] Scraping '{province}' internships from all 5 sources concurrently...")
        province_jobs = []

        def scrape_worker(scraper: BaseScraper) -> Tuple[str, List[Job], Optional[Exception]]:
            notify("source_start", {"source": scraper.source_name, "province": province})
            try:
                jobs = scraper.scrape(
                    target_province=province,
                    limit=args.limit,
                    max_pages=5,
                    category=args.category
                )
                return scraper.source_name, jobs, None
            except Exception as e:
                return scraper.source_name, [], e

        with ThreadPoolExecutor(max_workers=len(scrapers)) as executor:
            futures = [executor.submit(scrape_worker, s) for s in scrapers]
            for future in as_completed(futures):
                name, jobs, err = future.result()
                notify("source_done", {
                    "source": name,
                    "province": province,
                    "count": len(jobs),
                    "error": str(err) if err else None
                })
                if err:
                    print(f"  [!] [warn] {name} failed: {err}")
                else:
                    province_jobs.extend(jobs)
                    print(f"  [+] {name}: ได้รับ {len(jobs)} งาน")

        return province_jobs

    # 1. ดึงข้อมูลแบบคู่ขนาน (Parallel) จากจังหวัดเป้าหมายหลัก
    all_jobs.extend(fetch_for_province_parallel(args.province))
    print(f"\n[Phase 1] ผลรวมงานจาก '{args.province}': {len(all_jobs)} งาน")

    # 2. ตรวจสอบ Fallback ถ้างานในจังหวัดหลักมีน้อยกว่าเกณฑ์ที่กำหนด
    if not args.no_fallback and len(all_jobs) < args.min_jobs:
        print(
            f"\n[Phase 1] งานใน {args.province} มีเพียง {len(all_jobs)} งาน "
            f"(น้อยกว่าเกณฑ์ขั้นต่ำ {args.min_jobs}) -> กำลังดึง {args.fallback_province} เป็นสำรอง..."
        )
        notify("fallback_start", {
            "primary_count": len(all_jobs),
            "needed": args.min_jobs,
            "fallback_province": args.fallback_province
        })
        fallback_jobs = fetch_for_province_parallel(args.fallback_province)
        all_jobs.extend(fallback_jobs)

    print(f"\n[Phase 1] รวบรวมงานดิบทั้งหมดได้: {len(all_jobs)} รายการ")

    if not all_jobs:
        print("[!] ไม่พบประกาศงานจากแหล่งข้อมูลใดๆ ยุติการทำงาน")
        notify("complete", {"total_jobs": 0})
        return pd.DataFrame()

    # 3. ขจัดข้อมูลซ้ำซ้อนข้ามเว็บไซต์ (Deduplication)
    print("\n[Phase 2] ตรวจสอบและขจัดงานซ้ำซ้อนข้ามเว็บไซต์ (Deduplication)...")
    deduped_jobs, duplicate_count = deduplicate_jobs(all_jobs)
    print(f"[Phase 2] ขจัดงานซ้ำไป {duplicate_count} รายการ (เหลืองานเอกลักษณ์ {len(deduped_jobs)} รายการ)")
    notify("dedup", {
        "total_raw": len(all_jobs),
        "deduped": len(deduped_jobs),
        "removed": duplicate_count
    })

    # 4. แปลงเป็น DataFrame และบันทึก Raw Data
    df = jobs_to_dataframe(deduped_jobs)
    df.to_csv(raw_csv_path, index=False, encoding="utf-8-sig")
    print(f"[Phase 2] บันทึกข้อมูลดิบที่ไม่ซ้ำลง -> {raw_csv_path}")

    # 5. คำนวณความใหม่และให้คะแนน (Recency & Keyword Scoring & Role Classification)
    print("\n[Phase 3] คำนวณความสดใหม่ (Days_Ago), จำแนก Role และคำนวณคะแนนคีย์เวิร์ด...")
    scored_df = add_recency_and_score(df, custom_keywords=custom_keywords)

    # กรองงาน Senior/Manager ออกหากเปิดใช้ strict intern (default: เปิด)
    dropped_count = 0
    if not args.no_strict_intern:
        initial_len = len(scored_df)
        mask = [not is_senior_or_manager(row["title"], row["description"]) for _, row in scored_df.iterrows()]
        scored_df = scored_df[mask].reset_index(drop=True)
        dropped_count = initial_len - len(scored_df)
        if dropped_count > 0:
            print(f"[Phase 3] กรองงาน Senior/Manager ที่ไม่ใช่ฝึกงานออก {dropped_count} รายการ (เหลือ {len(scored_df)} งาน)")

    notify("filtering", {
        "dropped_seniors": dropped_count,
        "remaining": len(scored_df)
    })

    # กรอง Role หากระบุ
    if args.role:
        target_role = args.role.strip().lower()
        scored_df = scored_df[scored_df["Role"].str.lower().str.contains(target_role)].reset_index(drop=True)
        print(f"[Phase 3] กรองเฉพาะ Role '{args.role}' -> เหลือ {len(scored_df)} งาน")

    # กรอง Paid Only หากระบุ
    if args.paid_only:
        scored_df = scored_df[scored_df["Is_Paid"] == True].reset_index(drop=True)
        print(f"[Phase 3] กรองเฉพาะงานที่มีเบี้ยเลี้ยง -> เหลือ {len(scored_df)} งาน")

    # กรอง WFH หากระบุ
    if args.wfh:
        scored_df = scored_df[scored_df["Work_Style"].isin(["Remote / WFH", "Hybrid"])].reset_index(drop=True)
        print(f"[Phase 3] กรองเฉพาะงาน WFH/Remote -> เหลือ {len(scored_df)} งาน")

    # 6. จัดอันดับแบบ Multi-Level Ranking (เรียงขอนแก่นก่อนเสมอ ตามคำสั่งผู้ใช้)
    print(f"\n[Phase 4] จัดอันดับ (Ranking) โดยเรียงงานในจังหวัด '{args.province}' ขึ้นก่อนเสมอ...")
    target_prov = args.province.strip().lower()

    def is_primary_prov(p: str) -> int:
        plow = str(p or "").lower()
        if target_prov in plow:
            return 1
        if target_prov in ["khon kaen", "ขอนแก่น"] and ("khon kaen" in plow or "ขอนแก่น" in plow):
            return 1
        return 0

    scored_df["Is_Primary_Province"] = scored_df["province"].apply(is_primary_prov)

    # จัดเรียง: 1. ขอนแก่นขึ้นก่อน 2. คีย์เวิร์ดตรงมากที่สุด 3. โพสต์ใหม่ที่สุด 4. เนื้อหาละเอียดที่สุด
    ranked_df = scored_df.sort_values(
        by=["Is_Primary_Province", "Custom_Keyword_Score", "Days_Ago", "Score"],
        ascending=[False, False, True, False]
    ).reset_index(drop=True)

    ranked_df = ranked_df.head(args.top)

    export_columns = [
        "title",
        "company",
        "location",
        "province",
        "Role",
        "Work_Style",
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
    notify("ranking", {"total_ranked": len(ranked_df)})

    # สร้าง Interactive HTML Dashboard
    generate_html_dashboard(ranked_df, dashboard_html_path)

    notify("complete", {"total_jobs": len(ranked_df)})
    print("=" * 60)
    print("[SUCCESS] ดำเนินการเสร็จสิ้นสมบูรณ์!")
    return ranked_df


if __name__ == "__main__":
    run_pipeline()
