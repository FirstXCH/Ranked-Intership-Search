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
    สร้าง Interactive HTML Dashboard สไตล์ Minimal ขาว-ดำ-ฟ้า
    ออกแบบเป็นรายการแถวเดี่ยว (Linear List) กวาดสายตาลงมาอ่านได้ง่าย
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
            --bg: #f8fafc;
            --surface: #ffffff;
            --border: #e2e8f0;
            --text-main: #0f172a;
            --text-sub: #475569;
            --text-muted: #64748b;
            --primary: #2563eb;
            --primary-hover: #1d4ed8;
            --primary-soft: #eff6ff;
            --primary-border: #bfdbfe;
            --success-soft: #ecfdf5;
            --success-text: #065f46;
            --success-border: #a7f3d0;
        }}
        * {{ box-sizing: border-box; margin: 0; padding: 0; }}
        body {{
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif;
            background-color: var(--bg);
            color: var(--text-main);
            line-height: 1.5;
            padding: 32px 16px;
        }}
        .container {{
            max-width: 960px;
            margin: 0 auto;
        }}
        .header {{
            margin-bottom: 24px;
            padding-bottom: 20px;
            border-bottom: 1px solid var(--border);
            display: flex;
            justify-content: space-between;
            align-items: flex-end;
            flex-wrap: wrap;
            gap: 12px;
        }}
        .header h1 {{
            font-size: 24px;
            font-weight: 700;
            color: var(--text-main);
            letter-spacing: -0.02em;
        }}
        .header h1 span {{
            color: var(--primary);
        }}
        .header .subtitle {{
            font-size: 13px;
            color: var(--text-muted);
            margin-top: 4px;
        }}
        .controls {{
            display: flex;
            flex-direction: column;
            gap: 12px;
            margin-bottom: 20px;
        }}
        .search-box {{
            width: 100%;
            padding: 12px 16px;
            background: var(--surface);
            border: 1px solid var(--border);
            border-radius: 8px;
            font-size: 15px;
            color: var(--text-main);
            outline: none;
            transition: border-color 0.15s;
        }}
        .search-box:focus {{
            border-color: var(--primary);
        }}
        .filter-row {{
            display: flex;
            flex-wrap: wrap;
            gap: 6px;
            align-items: center;
        }}
        .filter-btn {{
            background: var(--surface);
            border: 1px solid var(--border);
            color: var(--text-sub);
            padding: 6px 12px;
            border-radius: 6px;
            font-size: 13px;
            font-weight: 500;
            cursor: pointer;
            transition: all 0.15s;
            user-select: none;
        }}
        .filter-btn:hover {{
            background: #f1f5f9;
            color: var(--text-main);
        }}
        .filter-btn.active {{
            background: var(--primary);
            color: #ffffff;
            border-color: var(--primary);
        }}
        .stats {{
            font-size: 13px;
            color: var(--text-muted);
            margin-bottom: 16px;
            display: flex;
            justify-content: space-between;
        }}
        /* รายการงานแบบแถวเดี่ยว กวาดสายตาลงมาอ่านได้ง่าย */
        .job-list {{
            display: flex;
            flex-direction: column;
            gap: 10px;
        }}
        .job-item {{
            background: var(--surface);
            border: 1px solid var(--border);
            border-radius: 8px;
            padding: 16px 20px;
            display: grid;
            grid-template-columns: 44px 1fr auto;
            align-items: center;
            gap: 16px;
            transition: border-color 0.15s, background-color 0.15s;
        }}
        .job-item:hover {{
            border-color: #cbd5e1;
            background-color: #fafbfc;
        }}
        .job-rank {{
            font-size: 14px;
            font-weight: 700;
            color: var(--text-muted);
            text-align: center;
            background: #f1f5f9;
            padding: 6px 0;
            border-radius: 6px;
            border: 1px solid var(--border);
        }}
        .job-rank.top-rank {{
            background: var(--primary-soft);
            color: var(--primary);
            border-color: var(--primary-border);
        }}
        .job-info {{
            min-width: 0;
        }}
        .job-title {{
            font-size: 16px;
            font-weight: 600;
            color: var(--text-main);
            margin-bottom: 4px;
            white-space: nowrap;
            overflow: hidden;
            text-overflow: ellipsis;
        }}
        .job-company-row {{
            font-size: 14px;
            color: var(--text-sub);
            margin-bottom: 8px;
            display: flex;
            align-items: center;
            gap: 8px;
            flex-wrap: wrap;
        }}
        .job-company {{
            font-weight: 500;
            color: var(--text-main);
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
            background: #f1f5f9;
            color: var(--text-sub);
            border: 1px solid var(--border);
        }}
        .badge.province-kk {{
            background: var(--primary-soft);
            color: var(--primary);
            border-color: var(--primary-border);
            font-weight: 600;
        }}
        .badge.paid {{
            background: var(--success-soft);
            color: var(--success-text);
            border-color: var(--success-border);
        }}
        .badge.keyword {{
            background: #fef2f2;
            color: #b91c1c;
            border-color: #fecaca;
        }}
        .badge.blue {{
            background: var(--primary-soft);
            color: var(--primary);
            border-color: var(--primary-border);
        }}
        .job-action {{
            display: flex;
            flex-direction: column;
            align-items: flex-end;
            gap: 8px;
        }}
        .job-time {{
            font-size: 12px;
            color: var(--text-muted);
            white-space: nowrap;
        }}
        .apply-btn {{
            display: inline-block;
            background: var(--primary);
            color: #ffffff;
            font-size: 13px;
            font-weight: 500;
            text-decoration: none;
            padding: 6px 14px;
            border-radius: 6px;
            white-space: nowrap;
            transition: background 0.15s;
        }}
        .apply-btn:hover {{
            background: var(--primary-hover);
        }}
        @media (max-width: 640px) {{
            .job-item {{
                grid-template-columns: 36px 1fr;
                gap: 12px;
            }}
            .job-action {{
                grid-column: 2;
                flex-direction: row;
                justify-content: space-between;
                align-items: center;
                margin-top: 8px;
                padding-top: 8px;
                border-top: 1px solid var(--border);
            }}
        }}
    </style>
</head>
<body>
    <div class="container">
        <header class="header">
            <div>
                <h1>🎯 Ranked <span>Internships</span></h1>
                <div class="subtitle">ระบบค้นหาและจัดอันดับงานฝึกงานสายไอที (เรียงพื้นที่เป้าหมายขึ้นก่อน)</div>
            </div>
            <div class="subtitle">อัปเดต: {datetime.now().strftime('%d/%m/%Y %H:%M')}</div>
        </header>

        <section class="controls">
            <input type="text" id="searchInput" class="search-box" placeholder="พิมพ์ค้นหาตำแหน่งงาน, ชื่อบริษัท, ทักษะที่สนใจ (เช่น React, Python, Data)...">
            <div class="filter-row" id="roleFilters">
                <span style="font-size: 13px; font-weight: 600; color: var(--text-sub); margin-right: 4px;">สายงาน:</span>
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
            <div class="filter-row">
                <span style="font-size: 13px; font-weight: 600; color: var(--text-sub); margin-right: 4px;">ตัวเลือกพิเศษ:</span>
                <button class="filter-btn" id="filterKK">📍 เฉพาะขอนแก่น</button>
                <button class="filter-btn" id="filterPaid">💰 มีเบี้ยเลี้ยง</button>
                <button class="filter-btn" id="filterWFH">🏠 Work From Home</button>
            </div>
        </section>

        <div class="stats">
            <span id="statsCount">กำลังโหลดข้อมูล...</span>
            <span>จัดเรียง: ขอนแก่นขึ้นก่อน &bull; ความตรงคีย์เวิร์ด &bull; ความใหม่</span>
        </div>

        <main class="job-list" id="jobList"></main>
    </div>

    <script>
        const jobs = {jobs_json};
        let selectedRole = "all";
        let onlyKK = false;
        let onlyPaid = false;
        let onlyWFH = false;
        let searchQuery = "";

        const searchInput = document.getElementById("searchInput");
        const jobList = document.getElementById("jobList");
        const statsCount = document.getElementById("statsCount");

        function render() {{
            const filtered = jobs.filter(j => {{
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

            statsCount.innerText = `พบ ${{filtered.length}} ตำแหน่งงาน (จากทั้งหมด ${{jobs.length}} รายการ)`;
            jobList.innerHTML = "";

            if (filtered.length === 0) {{
                jobList.innerHTML = '<div style="text-align: center; padding: 48px 16px; color: var(--text-muted); background: #ffffff; border: 1px solid var(--border); border-radius: 8px;">ไม่พบตำแหน่งงานที่ตรงกับเงื่อนไขการค้นหา</div>';
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
                        <span class="job-time">🕒 ${{timeText}}</span>
                        <a href="${{j.url}}" target="_blank" rel="noopener noreferrer" class="apply-btn">ดูงาน ↗</a>
                    </div>
                `;
                jobList.appendChild(item);
            }});
        }}

        searchInput.addEventListener("input", (e) => {{
            searchQuery = e.target.value.trim();
            render();
        }});

        document.querySelectorAll("#roleFilters .filter-btn").forEach(btn => {{
            btn.addEventListener("click", () => {{
                document.querySelectorAll("#roleFilters .filter-btn").forEach(b => b.classList.remove("active"));
                btn.classList.add("active");
                selectedRole = btn.dataset.role;
                render();
            }});
        }});

        const filterKK = document.getElementById("filterKK");
        filterKK.addEventListener("click", () => {{
            onlyKK = !onlyKK;
            filterKK.classList.toggle("active", onlyKK);
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

        render();
    </script>
</body>
</html>"""

    output_path.write_text(html_content, encoding="utf-8")
    print(f"[Phase 4] สร้าง Minimal Dashboard สำเร็จ -> {output_path}")


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

    # สร้าง Interactive HTML Dashboard
    generate_html_dashboard(ranked_df, dashboard_html_path)

    print("=" * 60)
    print("[SUCCESS] ดำเนินการเสร็จสิ้นสมบูรณ์!")


if __name__ == "__main__":
    run_pipeline()
