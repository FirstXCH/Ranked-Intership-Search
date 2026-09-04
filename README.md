# Ranked Internship Search 🎯

ระบบรวบรวม คัดกรอง และจัดอันดับงานฝึกงานสายไอทีและซอฟต์แวร์ (Tech Internship Search & Ranking ETL Pipeline) พร้อมหน้าเว็บแดชบอร์ดสไตล์ **prom-design (Instrument Register)** ที่มีระบบกดดึงข้อมูลสดและรายงานสถานะแบบเรียลไทม์

---

## 📌 โครงการนี้คืออะไรและเกี่ยวกับอะไร?

**Ranked Internship Search** คือเครื่องมืออัจฉริยะสำหรับนักศึกษาที่กำลังมองหาสถานที่ฝึกงานสายเทคโนโลยี สารสนเทศ และพัฒนาซอฟต์แวร์ (IT, Software Engineering, Data, DevOps, QA)

### ปัญหาที่พบในการค้นหางานฝึกงานทั่วไป:
1. **ต้องเปิดค้นหาทีละเว็บไซต์:** ข้อมูลกระจายอยู่หลายแพลตฟอร์ม เช่น JobThai, JobsDB, LinkedIn, เด็กฝึกงาน ฯลฯ
2. **เจองานอาวุโสปะปน:** ผลการค้นหามักมีงานระดับ Senior, Lead, Manager หรือต้องการประสบการณ์ 3 ถึง 5 ปีหลุดเข้ามา
3. **งานซ้ำซ้อนข้ามเว็บ:** หลายบริษัทโพสต์รับสมัครงานเดียวกันในหลายเว็บไซต์พร้อมกัน
4. **ค้นหาในพื้นที่เป้าหมายได้ยาก:** โดยเฉพาะจังหวัดหัวเมืองต่างจังหวัด (เช่น ขอนแก่น) หางานได้ยาก หรือได้ผลลัพธ์ไม่ตรงจุด

### โครงการนี้ช่วยแก้ไขปัญหาอย่างไร:
- **รวบรวมจาก 5 แหล่งชั้นนำ:** กวาดข้อมูลแบบคู่ขนาน (Parallel) จาก LinkedIn, JobThai, JobsDB, เด็กฝึกงาน (DekFukngan), และ InternTH
- **Smart Internship Filtering:** คัดกรองและตัดตำแหน่ง Senior/Manager ออกอัตโนมัติ 100% ทำให้ได้งานสำหรับนักศึกษาฝึกงานจริง
- **ระบบขจัดงานซ้ำ (Deduplication):** ตรวจจับชื่อบริษัทและตำแหน่งเพื่อยุบรวมงานที่โพสต์หลายเว็บเข้าด้วยกัน
- **จัดอันดับงานตรงใจ:** เรียงตำแหน่งงานในจังหวัดเป้าหมาย (ขอนแก่น) ขึ้นก่อนเสมอ พร้อมระบบ Fallback ดึงงานในกรุงเทพฯ มาเสริมหากงานมีน้อยกว่าเกณฑ์
- **Interactive Dashboard:** หน้าเว็บสวยงาม ใช้งานง่าย มีระบบบันทึกงานโปรด (Favorite ⭐), ปุ่มระบุว่าดูแล้ว ("ดูแล้ว ✓"), และปุ่มกดดึงข้อมูลสดพร้อมรายงานสถานะทีละเว็บ

---

## ✨ จุดเด่นและฟีเจอร์หลัก (Key Features)

### 1. ⚡ Multi-Source Parallel Scraping Engine
- ดึงข้อมูลจาก 5 แหล่งพร้อมกันด้วย `ThreadPoolExecutor`:
  - **LinkedIn:** ดึงผ่าน Guest Job Search API คัดงาน Tech บริษัทชั้นนำ
  - **JobThai:** รองรับ Pagination และรหัสจังหวัดแม่นยำ
  - **JobsDB:** ค้นหาตำแหน่งงานฝึกงานด้านซอฟต์แวร์
  - **เด็กฝึกงาน (DekFukngan):** แหล่งงานฝึกงานเฉพาะทางสำหรับนักศึกษา
  - **InternTH:** เว็บบอร์ดและประกาศรับสมัครเด็กฝึกงาน
- ความเร็วสูง: ใช้เวลากวาดข้อมูลพร้อมกันเพียง 15 ถึง 30 วินาที

### 2. 🎯 Smart Internship Filtering & Negative Keywords
- กรองคำที่ไม่ใช่ฝึกงาน เช่น `Senior`, `Lead`, `Manager`, `Director`, `Head of`, `ประสบการณ์ ... ปี` ทิ้งทันที
- คัดกรองเฉพาะงานสำหรับนักศึกษาฝึกงานและสหกิจศึกษาเท่านั้น

### 3. 🏷️ Role Classification & Custom Keyword Scoring
- จำแนกสายงานอัตโนมัติ: `Frontend`, `Backend`, `Fullstack`, `Data / AI`, `DevOps / Cloud`, `QA / Tester`, `Mobile`, `UI / UX`, `IT Support`
- คำนวณคะแนนตามคีย์เวิร์ดที่ผู้ใช้ระบุ (เช่น ภาษาโปรแกรม, Framework, หรือความต้องการพิเศษ)
- คำนวณความสดใหม่ของประกาศ (`Days_Ago`) เพื่อนำตำแหน่งงานที่เพิ่งโพสต์ใหม่ขึ้นมานำเสนอ

### 4. 💰 Allowance & Work From Home Detection
- ตรวจจับสวัสดิการเบี้ยเลี้ยงและค่าตอบแทน (`Is_Paid`)
- ตรวจจับรูปแบบการทำงาน Work From Home / Remote หรือ Hybrid (`Work_Style`)

### 5. 🎨 Interactive Dashboard (prom-design Instrument Register)
- ดีไซน์มินิมอล ขาว-ดำ-ฟ้า ไม่มี Gradient: อ่านง่าย สบายตา กวาดสายตาได้รวดเร็ว
- **Mobile Bottom Tab Bar:** แถบนำทางด้านล่าง 4 เมนู รองรับหน้าจอมือถือ (375px/390px) แบบเต็มพื้นที่ ไม่ล้นจอ
- **Tabular Numbers:** ตัวเลข อันดับ และวันที่แสดงผลตรงแนวด้วย `font-variant-numeric: tabular-nums`
- **ปุ่มระบุว่าเปิดดูแล้ว (Visited Tracking):** ปุ่ม "ดูงาน ↗" เมื่อคลิกจะเปลี่ยนเป็นสีเทา "ดูแล้ว ✓" และจำค่าใน LocalStorage

### 6. 🔄 Live Scraping & Real-time Status Monitor
- มีปุ่ม **"🔄 ดึงข้อมูลสด"** บนหน้าเว็บ ทำงานร่วมกับ Local Server (`server.py`)
- แผงควบคุมแสดงความคืบหน้าแบบ Real-time:
  - บอกสถานะของแต่ละเว็บ (กำลังดึง, สำเร็จกี่งาน, หรือข้ามกรณีติด Rate Limit)
  - มีตัวจับเวลา (Elapsed Timer)
  - มีระบบ **Watchdog Timer** แจ้งเตือนเมื่อเว็บปลายทางตอบสนองช้า เพื่อให้ผู้ใช้ทราบว่าระบบกำลังรอหรือเตรียมข้าม ไม่ได้เกิดอาการค้าง
- เมื่อกวาดข้อมูลเสร็จสิ้น หน้าเว็บจะโหลดข้อมูลตำแหน่งงานใหม่มาแสดงทันทีโดยไม่ต้อง Refresh หน้า

### 7. ⭐ ระบบ Favorite (รายการโปรด)
- ปุ่มรูปดาว ⭐ บนการ์ดงานทุกตำแหน่ง สำหรับติ๊กเลือกงานที่สนใจ
- ข้อมูลถูกจัดเก็บใน `localStorage` ของเบราว์เซอร์อย่างปลอดภัย
- มีชิปตัวกรองและแท็บ "⭐ ที่สนใจ ([จำนวน])" อัปเดตตัวเลขนับแบบเรียลไทม์

---

## 💻 การติดตั้งและเตรียมสภาพแวดล้อม (Installation)

### ข้อกำหนดเบื้องต้น
- Python 3.10 ขึ้นไป
- Git

### ขั้นตอนการติดตั้ง

1. **Clone โครงการจาก GitHub:**
```powershell
git clone https://github.com/FirstXCH/Ranked-Intership-Search.git
cd Ranked-Intership-Search
```

2. **สร้างและเปิดใช้งาน Virtual Environment:**
```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
```

3. **ติดตั้งแพ็กเกจที่จำเป็น:**
```powershell
pip install -r requirements.txt
```

---

## 🚀 วิธีการใช้งาน (Usage)

โครงการนี้รองรับการใช้งาน 2 รูปแบบ:

### วิธีที่ 1: รัน Local Web Server เพื่อใช้งานผ่านหน้าเว็บ (แนะนำ 👍)

เป็นวิธีที่สะดวกที่สุด สามารถค้นหา กรอง บันทึกงานโปรด และกดปุ่มดึงข้อมูลสดผ่านเบราว์เซอร์ได้ทันที

```powershell
.\.venv\Scripts\python.exe server.py --port 8000
```
เปิดเว็บเบราว์เซอร์ไปที่: **http://localhost:8000/**

- คลิกปุ่ม **"🔄 ดึงข้อมูลสด"** เพื่อสั่งให้ระบบเริ่มกวาดข้อมูลใหม่แบบสดๆ
- ดูสถานะการดึงข้อมูลจากแต่ละเว็บได้แบบ Real-time
- คลิกดาว ⭐ เพื่อบันทึกงานที่สนใจ
- คลิกลิงก์ "ดูงาน ↗" เพื่อไปยังหน้าสมัครงานของบริษัทต้นทาง

---

### วิธีที่ 2: รันผ่าน Command Line Interface (CLI)

เหมาะสำหรับการรันกวาดข้อมูลแบบกำหนดค่าเฉพาะเจาะจง หรือรันเป็น Scheduled Task

#### 1. รันแบบค่าเริ่มต้น (Default)
ค้นหาในขอนแก่นก่อน หากได้งานน้อยกว่า 100 ตำแหน่งจะดึงกรุงเทพฯ มาเสริมอัตโนมัติ:
```powershell
.\.venv\Scripts\python.exe main.py
```

#### 2. รันพร้อมระบุคีย์เวิร์ดพิเศษเพื่อบวกคะแนน
```powershell
.\.venv\Scripts\python.exe main.py --keywords "เบี้ยเลี้ยง,React,Python,Node,WFH"
```

#### 3. กรองเฉพาะสายงาน และเอาเฉพาะงานที่มีค่าตอบแทน (เบี้ยเลี้ยง)
```powershell
.\.venv\Scripts\python.exe main.py --role "backend" --paid-only
```

#### 4. กรองเฉพาะงานสาย Data ในกรุงเทพฯ ที่ทำแบบ Work From Home ได้
```powershell
.\.venv\Scripts\python.exe main.py --province "Bangkok" --no-fallback --role "data" --wfh
```

#### 5. ดึงงานสาย Frontend ในขอนแก่น พร้อมส่งออก 50 อันดับแรก
```powershell
.\.venv\Scripts\python.exe main.py --province "Khon Kaen" --role "frontend" --top 50
```

---

## ⚙️ รายการคำสั่ง CLI Parameters ทั้งหมด

| พารามิเตอร์ | ตัวย่อ | ค่าเริ่มต้น | คำอธิบาย |
|---|---|---|---|
| `--province` | | `"Khon Kaen"` | จังหวัดหลักที่ต้องการค้นหา |
| `--fallback-province` | | `"Bangkok"` | จังหวัดสำรองกรณีงานในจังหวัดหลักน้อยกว่าเกณฑ์ |
| `--no-fallback` | | `False` | ปิดระบบ Fallback ไม่ดึงจังหวัดสำรองเพิ่ม |
| `--min-jobs` | | `100` | จำนวนงานขั้นต่ำในจังหวัดหลักก่อนเปิดใช้ Fallback |
| `--category` | | `"it"` | หมวดหมู่งาน เช่น `it`, `marketing`, `accounting` |
| `--limit` | | `50` | จำนวนงานสูงสุดที่ต้องการดึงต่อหนึ่งเว็บไซต์ |
| `--keywords` | `-k` | `""` | คีย์เวิร์ดบวกคะแนน คั่นด้วยจุลภาค เช่น `"React,Python"` |
| `--role` | | `""` | กรองเฉพาะสายงาน เช่น `frontend`, `backend`, `data`, `qa` |
| `--paid-only` | | `False` | กรองเฉพาะตำแหน่งที่มีเบี้ยเลี้ยงหรือค่าตอบแทน |
| `--wfh` | | `False` | กรองเฉพาะตำแหน่งที่ทำแบบ Remote / WFH หรือ Hybrid |
| `--no-strict-intern`| | `False` | ปิดการกรองงาน Senior/Manager (เก็บทุกตำแหน่งไว้) |
| `--top` | | `100` | จำนวนงานสูงสุดที่จะบันทึกลงใน `ranked_internships.csv` |

---

## 📁 โครงสร้างโปรเจกต์ (Project Structure)

```text
Ranked-Internship-Search/
├── scrapers/                     # โมดูล Scraper สำหรับแต่ละเว็บไซต์
│   ├── base.py                   # คลาสแม่ BaseScraper พร้อมระบบ Retry/Backoff
│   ├── linkedin.py               # LinkedIn Guest API Scraper
│   ├── jobthai.py                # JobThai Scraper (Multi-page & Province)
│   ├── jobsdb.py                 # JobsDB Scraper
│   ├── dekfukngan.py             # เด็กฝึกงาน.com Scraper
│   └── internth.py               # InternTH Scraper
├── outputs/                      # โฟลเดอร์เก็บผลลัพธ์ (สร้างอัตโนมัติ)
│   ├── raw_internships.csv       # ข้อมูลงานดิบทั้งหมดที่ผ่านการ Deduplicate
│   ├── ranked_internships.csv    # ข้อมูลงานที่ผ่านการกรองและจัดอันดับแล้ว
│   └── dashboard.html            # หน้าเว็บแดชบอร์ดค้นหางานแบบ Interactive
├── main.py                       # สคริปต์หลัก ETL Pipeline และตัวสร้าง Dashboard
├── server.py                     # Local HTTP Server และ REST API สำหรับ Live Scraping
├── requirements.txt              # รายการ Library ที่โปรเจกต์ต้องใช้
├── work_log.md                   # บันทึกประวัติและรายละเอียดการพัฒนา
└── README.md                     # เอกสารแนะนำการใช้งานโครงการ
```

---

## 📐 กฎการออกแบบและวิศวกรรม (Engineering Standards)

- **prom-design (Instrument Register):** ออกแบบตามมาตรฐาน The Assembly มุ่งเน้นการใช้งานจริง ข้อมูลแน่น กวาดสายตาง่าย ปุ่มสัมผัสขนาดไม่น้อยกว่า 44px
- **House Rule Compliance:** ปราศจากเครื่องหมาย em dash (—) และ en dash (–) ในโค้ด ข้อความ และ Commit Message
- **Resilience:** มีระบบ Backoff และ Timeout Handling ทุก Scraper หากเว็บใดมีปัญหาหรือติด Rate Limit ระบบจะข้ามไปทำงานอื่นอัตโนมัติโดยไม่ทำให้ Pipeline ล่ม

---

## 📄 ใบอนุญาต (License)

โครงการนี้พัฒนาขึ้นเพื่อการศึกษาและการค้นหาตำแหน่งงานฝึกงานของนักศึกษา
สงวนลิขสิทธิ์ตามมาตรฐาน Open-Source Educational Project
