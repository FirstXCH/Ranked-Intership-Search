# Work Log - Ranked Internship Search

## ทำไปแล้ว (Done)
- ปรับโครงสร้างแบบ OOP (มี `BaseScraper`)
- รองรับการดึงหลายแหล่ง (Multi-Source): `JobThai`, `JobsDB`, `DekFukngan`, `InternTH`, `LinkedIn`
- ปรับการเชื่อมโยงแต่ละเว็บให้ถูกต้องตามโครงสร้างใหม่ (อ่าน payload, JSON, HTML)
- เพิ่มระบบ Fallback: ค้นหาจังหวัดขอนแก่นก่อน หากได้งานรวมต่ำกว่าเกณฑ์ (default: 100) จะค้นหากรุงเทพฯ มาต่อท้าย
- ยกเลิกเว็บที่ไม่เสถียรหรือไม่เกี่ยวข้อง (เช่น `JobBKK` และ `ThaiJob`)
- ปรับระบบให้คะแนนโดยนำ `description` และ `benefits` มาคิดรวมเป็นคะแนน (Score) ความละเอียด
- คำนวณความใหม่ของโพสต์ (`Days_Ago`)
- จัดอันดับงานที่ดีที่สุด แล้วเซฟลง `outputs/ranked_internships.csv`
- บันทึกข้อมูลดิบทั้งหมดลง `outputs/raw_internships.csv`
- จัดการไฟล์ใน `.gitignore` ไม่ให้ Commit ไฟล์ผลลัพธ์ (outputs) รวมถึงไฟล์ระบบอย่าง `__pycache__`
- แก้ไขบั๊ก JobThai Bangkok: ปรับรหัสจังหวัดกรุงเทพฯ จาก `"1"` เป็น `"01"`
- ระบบดึงหน้าถัดไป (Pagination): วนลูปดึงข้อมูลหน้าถัดไป (`page=1, 2, 3...`) ในทุก Scraper
- ระบบขจัดงานซ้ำซ้อน (Deduplication): เปรียบเทียบชื่อบริษัทและตำแหน่งงาน โดยตัดคำสร้อย และรวม `source`
- ระบบ Custom Keyword Scoring: รับคีย์เวิร์ดเพิ่มเติมเพื่อบวกคะแนน พร้อมคอลัมน์ `Matched_Keywords`
- ระบบ Backoff / Retry & Throttling: ป้องกันการถูกแบนด้วย Exponential Backoff และ Random Delay
- **[New] เพิ่ม LinkedIn Scraper:** ดึงงานฝึกงานสาย Tech จาก LinkedIn Guest Job Search API
- **[New] Parallel Scraping Engine:** ใช้ `ThreadPoolExecutor` ดึงข้อมูลทุกแหล่งพร้อมกันแบบคู่ขนาน เร็วขึ้นกว่าเดิม 4 เท่า
- **[New] Smart Internship Filtering:** คัดกรองงานระดับ Senior, Lead, Manager, หรือระบุประสบการณ์หลายปีที่ไม่ใช่งานฝึกงานทิ้งอัตโนมัติ
- **[New] Role Classification & Filter:** จำแนกสายงาน (Frontend, Backend, Fullstack, Data/AI, DevOps, QA, Mobile, UI/UX, IT Support) พร้อมตัวเลือก `--role`
- **[New] Paid-Only & WFH Filters:** ตัวกรองเฉพาะงานที่มีเบี้ยเลี้ยง (`--paid-only`) และงาน Work From Home/Hybrid (`--wfh`)
- **[New] Interactive HTML Dashboard:** สร้างหน้าเว็บแดชบอร์ดสรุปและค้นหาตำแหน่งงานใน `outputs/dashboard.html` เปิดดูและคลิกสมัครได้ทันที

## กำลังใช้งานตอนนี้ (Current Behavior)
- ค้นหาแบบคู่ขนาน (Parallel) ผ่าน 5 แหล่งข้อมูล:
  - JobThai
  - JobsDB
  - DekFukngan (เด็กฝึกงาน.com)
  - InternTH
  - LinkedIn
- ดึงข้อมูลผ่าน Pagination สูงสุด 5 หน้าจนครบเป้าหมายที่กำหนดต่อเว็บ
- คัดกรองและจับคู่งานตามจังหวัดเป้าหมาย (Default: Khon Kaen -> Fallback: Bangkok)
- ขจัดงานซ้ำซ้อนข้ามเว็บไซต์ และรวมแหล่งที่มาในฟิลด์ `source`
- กรองงาน Senior/Manager ทิ้ง เพื่อให้ได้ตำแหน่งงานฝึกงานจริง
- จัดอันดับแบบ Multi-Level:
  1. `Custom_Keyword_Score` (มากไปน้อย - ยิ่งตรงคีย์เวิร์ดยิ่งขึ้นก่อน)
  2. `Days_Ago` (น้อยไปมาก - โพสต์สดใหม่ที่สุด)
  3. `Score` (มากไปน้อย - ความละเอียดของเนื้อหา)
- สร้างไฟล์ผลลัพธ์ทั้ง CSV และ Interactive HTML Dashboard

## วิธีรัน (Usage & CLI Commands)

### 1. รันแบบพื้นฐาน (Default)
```powershell
.\.venv\Scripts\python.exe main.py
```

### 2. รันพร้อมระบุคีย์เวิร์ดบวกคะแนน
```powershell
.\.venv\Scripts\python.exe main.py --keywords "เบี้ยเลี้ยง,ที่พัก,React,Python,WFH"
```

### 3. กรองเฉพาะสายงาน และเอาเฉพาะงานที่มีเบี้ยเลี้ยง
```powershell
.\.venv\Scripts\python.exe main.py --role "data" --paid-only
```

### 4. กรองงาน Work From Home / Remote
```powershell
.\.venv\Scripts\python.exe main.py --province "Bangkok" --no-fallback --wfh
```

### 5. ตัวเลือกทั้งหมด (All Options)
- `--province`: จังหวัดหลักที่ต้องการค้นหา (Default: `"Khon Kaen"`)
- `--fallback-province`: จังหวัดสำรองหากงาน < min-jobs (Default: `"Bangkok"`)
- `--no-fallback`: ปิดระบบ Fallback ไม่ดึงจังหวัดสำรอง
- `--min-jobs`: จำนวนงานขั้นต่ำในจังหวัดหลักก่อนดึงสำรอง (Default: `100`)
- `--category`: หมวดหมู่งาน (Default: `it`)
- `--limit`: จำนวนงานเป้าหมายสูงสุดต่อเว็บไซต์ (Default: `50`)
- `--keywords`, `-k`: คีย์เวิร์ดคั่นด้วยจุลภาค เช่น `"เบี้ยเลี้ยง,ที่พัก,Python"`
- `--role`: กรองเฉพาะสายงาน เช่น `frontend`, `backend`, `data`, `qa`
- `--paid-only`: กรองเฉพาะงานที่มีเบี้ยเลี้ยง/ค่าตอบแทน
- `--wfh`: กรองเฉพาะงาน Work From Home / Hybrid
- `--no-strict-intern`: ปิดการกรองงาน Senior/Manager
- `--top`: จำนวนงานที่ต้องการ Export ลง `ranked_internships.csv` (Default: `100`)

## ไฟล์ผลลัพธ์
- `outputs/raw_internships.csv`: ข้อมูลงานดิบทั้งหมดที่ผ่านการ Deduplicate แล้ว
- `outputs/ranked_internships.csv`: ข้อมูลงานที่จัดอันดับแล้ว พร้อมคะแนนคีย์เวิร์ด
- `outputs/dashboard.html`: หน้าเว็บแดชบอร์ดค้นหาและคัดกรองงานแบบ Interactive
