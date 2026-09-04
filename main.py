import argparse
import re
import sys
from pathlib import Path
from datetime import datetime, timezone
from typing import List, Dict, Tuple, Optional
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
    สร้าง Interactive HTML Dashboard สำหรับเปิดดูในเบราว์เซอร์ได้ทันที
    มีฟิลเตอร์ Search, Role, WFH, เบี้ยเลี้ยง และปุ่มกดลิงก์สมัครงาน
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
            --bg: #0f172a;
            --surface: #1e293b;
            --surface-hover: #334155;
            --primary: #3b82f6;
            --primary-light: #60a5fa;
            --accent: #10b981;
            --text: #f8fafc;
            --text-muted: #94a3b8;
            --border: #334155;
        }}
        * {{ box-sizing: border-box; margin: 0; padding: 0; }}
        body {{
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif;
            background-color: var(--bg);
            color: var(--text);
            line-height: 1.5;
            padding: 24px;
        }}
        .header {{
            max-width: 1200px;
            margin: 0 auto 24px auto;
            display: flex;
            justify-content: space-between;
            align-items: center;
            flex-wrap: wrap;
            gap: 16px;
            border-bottom: 1px solid var(--border);
            padding-bottom: 16px;
        }}
        .header h1 {{ font-size: 26px; font-weight: 700; color: #fff; }}
        .header h1 span {{ color: var(--primary-light); }}
        .controls {{
            max-width: 1200px;
            margin: 0 auto 24px auto;
            display: flex;
            flex-direction: column;
            gap: 12px;
        }}
        .search-bar {{
            width: 100%;
            padding: 12px 18px;
            background: var(--surface);
            border: 1px solid var(--border);
            border-radius: 10px;
            color: #fff;
            font-size: 15px;
            outline: none;
            transition: border-color 0.2s;
        }}
        .search-bar:focus {{ border-color: var(--primary); }}
        .filter-group {{
            display: flex;
            gap: 8px;
            flex-wrap: wrap;
            align-items: center;
        }}
        .filter-chip {{
            padding: 6px 14px;
            border-radius: 20px;
            background: var(--surface);
            border: 1px solid var(--border);
            color: var(--text-muted);
            font-size: 13px;
            cursor: pointer;
            user-select: none;
            transition: all 0.2s;
        }}
        .filter-chip.active {{
            background: var(--primary);
            color: #fff;
            border-color: var(--primary);
            font-weight: 600;
        }}
        .stats-bar {{
            max-width: 1200px;
            margin: 0 auto 16px auto;
            color: var(--text-muted);
            font-size: 14px;
        }}
        .job-grid {{
            max-width: 1200px;
            margin: 0 auto;
            display: grid;
            grid-template-columns: repeat(auto-fill, minmax(360px, 1fr));
            gap: 16px;
        }}
        .job-card {{
            background: var(--surface);
            border: 1px solid var(--border);
            border-radius: 12px;
            padding: 18px;
            display: flex;
            flex-direction: column;
            justify-content: space-between;
            transition: transform 0.2s, border-color 0.2s;
        }}
        .job-card:hover {{
            transform: translateY(-2px);
            border-color: var(--primary-light);
        }}
        .rank-badge {{
            display: inline-block;
            font-size: 12px;
            font-weight: 700;
            padding: 2px 8px;
            border-radius: 6px;
            background: #1e3a8a;
            color: #93c5fd;
            margin-bottom: 8px;
        }}
        .job-title {{
            font-size: 17px;
            font-weight: 600;
            margin-bottom: 4px;
            color: #fff;
        }}
        .job-company {{
            font-size: 14px;
            color: var(--text-muted);
            margin-bottom: 12px;
        }}
        .tags {{
            display: flex;
            gap: 6px;
            flex-wrap: wrap;
            margin-bottom: 14px;
        }}
        .tag {{
            font-size: 12px;
            padding: 3px 8px;
            border-radius: 6px;
            background: #0f172a;
            border: 1px solid #334155;
            color: #cbd5e1;
        }}
        .tag.paid {{ background: #064e3b; color: #6ee7b7; border-color: #047857; }}
        .tag.kw {{ background: #701a75; color: #f5d0fe; border-color: #a21caf; }}
        .tag.role {{ background: #172554; color: #93c5fd; border-color: #1e40af; }}
        .card-footer {{
            display: flex;
            justify-content: space-between;
            align-items: center;
            border-top: 1px solid var(--border);
            padding-top: 12px;
            margin-top: auto;
        }}
        .recency {{ font-size: 12px; color: var(--text-muted); }}
        .apply-btn {{
            background: var(--primary);
            color: #fff;
            padding: 6px 14px;
            border-radius: 6px;
            text-decoration: none;
            font-size: 13px;
            font-weight: 600;
            transition: background 0.2s;
        }}
        .apply-btn:hover {{ background: var(--primary-light); }}
    </style>
</head>
<body>
    <div class="header">
        <h1>🎯 Ranked <span>Internships</span> Dashboard</h1>
        <div style="font-size: 14px; color: var(--text-muted);">อัปเดตล่าสุด: {datetime.now().strftime('%d/%m/%Y %H:%M')}</div>
    </div>

    <div class="controls">
        <input type="text" id="searchInput" class="search-bar" placeholder="🔍 ค้นหาชื่องาน, บริษัท, หรือทักษะที่ต้องการ (เช่น React, Python, เบี้ยเลี้ยง)...">
        <div class="filter-group" id="roleFilters">
            <span style="font-size: 13px; color: var(--text-muted);">Role:</span>
            <div class="filter-chip active" data-role="all">ทั้งหมด</div>
            <div class="filter-chip" data-role="Frontend">Frontend</div>
            <div class="filter-chip" data-role="Backend">Backend</div>
            <div class="filter-chip" data-role="Fullstack">Fullstack</div>
            <div class="filter-chip" data-role="Data / AI">Data / AI</div>
            <div class="filter-chip" data-role="DevOps / Cloud">DevOps</div>
            <div class="filter-chip" data-role="QA / Tester">QA/Tester</div>
            <div class="filter-chip" data-role="Mobile">Mobile</div>
            <div class="filter-chip" data-role="UI / UX">UI/UX</div>
            <div class="filter-chip" data-role="IT Support">IT Support</div>
        </div>
        <div class="filter-group">
            <span style="font-size: 13px; color: var(--text-muted);">ตัวกรองพิเศษ:</span>
            <div class="filter-chip" id="togglePaid">💰 มีเบี้ยเลี้ยง</div>
            <div class="filter-chip" id="toggleWFH">🏠 Work From Home</div>
        </div>
    </div>

    <div class="stats-bar" id="statsText">กำลังโหลด...</div>
    <div class="job-grid" id="jobGrid"></div>

    <script>
        const jobs = {jobs_json};
        let selectedRole = "all";
        let filterPaid = false;
        let filterWFH = false;
        let searchQuery = "";

        const searchInput = document.getElementById("searchInput");
        const jobGrid = document.getElementById("jobGrid");
        const statsText = document.getElementById("statsText");

        function render() {{
            const filtered = jobs.filter(j => {{
                if (selectedRole !== "all" && j.Role !== selectedRole) return false;
                if (filterPaid && !j.Is_Paid) return false;
                if (filterWFH && j.Work_Style !== "Remote / WFH" && j.Work_Style !== "Hybrid") return false;
                if (searchQuery) {{
                    const q = searchQuery.toLowerCase();
                    const text = (j.title + " " + j.company + " " + j.location + " " + (j.Matched_Keywords || "")).toLowerCase();
                    if (!text.includes(q)) return false;
                }}
                return true;
            }});

            statsText.innerText = `แสดงผล ${{filtered.length}} ตำแหน่งงาน (จากทั้งหมด ${{jobs.length}} รายการ)`;
            jobGrid.innerHTML = "";

            if (filtered.length === 0) {{
                jobGrid.innerHTML = '<div style="grid-column: 1/-1; text-align: center; padding: 40px; color: var(--text-muted);">ไม่พบตำแหน่งงานที่ตรงกับเงื่อนไขการค้นหา</div>';
                return;
            }}

            filtered.forEach((j, index) => {{
                const card = document.createElement("div");
                card.className = "job-card";

                const daysText = j.Days_Ago < 999 ? (j.Days_Ago === 0 ? "วันนี้" : `${{Math.round(j.Days_Ago)}} วันที่แล้ว`) : "ไม่ระบุวัน";
                const paidTag = j.Is_Paid ? '<span class="tag paid">💰 มีเบี้ยเลี้ยง</span>' : '';
                const kwTag = j.Matched_Keywords && j.Matched_Keywords !== "-" ? `<span class="tag kw">⭐ ${{j.Matched_Keywords}}</span>` : '';

                card.innerHTML = `
                    <div>
                        <div class="rank-badge">#${{index + 1}}</div>
                        <div class="job-title">${{j.title}}</div>
                        <div class="job-company">🏢 ${{j.company || "ไม่ระบุบริษัท"}}</div>
                        <div class="tags">
                            <span class="tag role">${{j.Role || "General IT"}}</span>
                            <span class="tag">📍 ${{j.province || j.location}}</span>
                            <span class="tag">🌐 ${{j.source}}</span>
                            ${{paidTag}}
                            ${{kwTag}}
                        </div>
                    </div>
                    <div class="card-footer">
                        <span class="recency">🕒 ${{daysText}}</span>
                        <a href="${{j.url}}" target="_blank" class="apply-btn">ดูรายละเอียด ↗</a>
                    </div>
                `;
                jobGrid.appendChild(card);
            }});
        }}

        searchInput.addEventListener("input", (e) => {{
            searchQuery = e.target.value.trim();
            render();
        }});

        document.querySelectorAll("#roleFilters .filter-chip").forEach(chip => {{
            chip.addEventListener("click", () => {{
                document.querySelectorAll("#roleFilters .filter-chip").forEach(c => c.classList.remove("active"));
                chip.classList.add("active");
                selectedRole = chip.dataset.role;
                render();
            }});
        }});

        const togglePaid = document.getElementById("togglePaid");
        togglePaid.addEventListener("click", () => {{
            filterPaid = !filterPaid;
            togglePaid.classList.toggle("active", filterPaid);
            render();
        }});

        const toggleWFH = document.getElementById("toggleWFH");
        toggleWFH.addEventListener("click", () => {{
            filterWFH = !filterWFH;
            toggleWFH.classList.toggle("active", filterWFH);
            render();
        }});

        render();
    </script>
</body>
</html>"""

    output_path.write_text(html_content, encoding="utf-8")
    print(f"[Phase 4] สร้าง Interactive Dashboard สำเร็จ -> {output_path}")


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


def run_pipeline(args: Optional[argparse.Namespace] = None) -> None:
    if args is None:
        args = parse_arguments()

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
        fallback_jobs = fetch_for_province_parallel(args.fallback_province)
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

    # 5. คำนวณความใหม่และให้คะแนน (Recency & Keyword Scoring & Role Classification)
    print("\n[Phase 3] คำนวณความสดใหม่ (Days_Ago), จำแนก Role และคำนวณคะแนนคีย์เวิร์ด...")
    scored_df = add_recency_and_score(df, custom_keywords=custom_keywords)

    # กรองงาน Senior/Manager ออกหากเปิดใช้ strict intern (default: เปิด)
    if not args.no_strict_intern:
        initial_len = len(scored_df)
        mask = [not is_senior_or_manager(row["title"], row["description"]) for _, row in scored_df.iterrows()]
        scored_df = scored_df[mask].reset_index(drop=True)
        dropped_count = initial_len - len(scored_df)
        if dropped_count > 0:
            print(f"[Phase 3] กรองงาน Senior/Manager ที่ไม่ใช่ฝึกงานออก {dropped_count} รายการ (เหลือ {len(scored_df)} งาน)")

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

    # 6. จัดอันดับแบบ Multi-Level Ranking และส่งออก CSV
    print(f"\n[Phase 4] จัดอันดับ (Ranking) และส่งออกไฟล์ผลลัพธ์ (Top {args.top})...")
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

    # สร้าง Interactive HTML Dashboard
    generate_html_dashboard(ranked_df, dashboard_html_path)

    print("=" * 60)
    print("[SUCCESS] ดำเนินการเสร็จสิ้นสมบูรณ์!")


if __name__ == "__main__":
    run_pipeline()
