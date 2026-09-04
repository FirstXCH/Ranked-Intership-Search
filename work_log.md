# Work Log - Ranked Internship Search

## ทำไปแล้ว (Done)
- ปรับโครงสร้างแบบ OOP (มี `BaseScraper`)
- รองรับการดึงหลายแหล่ง (Multi-Source): `JobThai`, `JobsDB`, `DekFukngan`, `InternTH`
- ปรับการเชื่อมโยงแต่ละเว็บให้ถูกต้องตามโครงสร้างใหม่ (อ่าน payload, JSON, HTML)
- เพิ่มระบบ Fallback: ค้นหาจังหวัดขอนแก่นก่อน หากได้งานรวมต่ำกว่าเกณฑ์ (default: 100) จะค้นหากรุงเทพฯ มาต่อท้าย
- ยกเลิกเว็บที่ไม่เสถียรหรือไม่เกี่ยวข้อง (เช่น `JobBKK` และ `ThaiJob`)
- ปรับระบบให้คะแนนโดยนำ `description` และ `benefits` มาคิดรวมเป็นคะแนน (Score) ความละเอียด
- คำนวณความใหม่ของโพสต์ (`Days_Ago`)
- จัดอันดับ 100 งานที่ดีที่สุด แล้วเซฟลง `outputs/ranked_internships.csv`
- บันทึกข้อมูลดิบทั้งหมดลง `outputs/raw_internships.csv`
- จัดการไฟล์ใน `.gitignore` ไม่ให้ Commit ไฟล์ผลลัพธ์ (outputs) รวมถึงไฟล์ระบบอย่าง `__pycache__`
- **[New] แก้ไขบั๊ก JobThai Bangkok:** ปรับรหัสจังหวัดกรุงเทพฯ จาก `"1"` เป็น `"01"` (ทำให้สามารถดึงงานกรุงเทพฯ ใน JobThai ได้ถูกต้อง)
- **[New] ระบบดึงหน้าถัดไป (Pagination):** วนลูปดึงข้อมูลหน้าถัดไป (`page=1, 2, 3...`) ในทุก Scraper จนกว่าจะได้งานครบตาม limit หรือหมดหน้า
- **[New] ระบบขจัดงานซ้ำซ้อน (Deduplication):** เปรียบเทียบชื่อบริษัทและชื่อตำแหน่งงาน โดยตัดคำสร้อย (บจก., จำกัด, Co., Ltd.) รวมรายชื่อ `source` เข้าด้วยกัน และเก็บเนื้อหาที่สมบูรณ์ที่สุด
- **[New] รองรับ CLI Parameters:** ปรับเปลี่ยนจังหวัดหลัก, จังหวัดสำรอง, หมวดหมู่, จำนวนงาน, และคีย์เวิร์ดได้ผ่านคำสั่ง CLI
- **[New] ระบบ Custom Keyword Scoring:** รับคีย์เวิร์ดเพิ่มเติมเพื่อบวกคะแนน (คำละ 10 คะแนน) พร้อมบันทึกคำที่ตรวจเจอลงคอลัมน์ `Matched_Keywords`
- **[New] ระบบ Backoff / Retry & Throttling:** ใช้ `urllib3.util.retry.Retry` (Exponential Backoff เมื่อเจอ 429/5xx) และมี Random Delay ป้องกันการถูกแบน

## กำลังใช้งานตอนนี้ (Current Behavior)
- ค้นหาผ่าน URL เป้าหมายในหมวดหมู่ IT ของแต่ละเว็บ:
  - JobThai
  - JobsDB
  - DekFukngan (เด็กฝึกงาน.com)
  - InternTH
- ดึงข้อมูลผ่าน Pagination สูงสุด 5 หน้าจนครบเป้าหมายที่กำหนดต่อเว็บ
- คัดกรองและจับคู่งานตามจังหวัดเป้าหมาย (Default: Khon Kaen -> Fallback: Bangkok)
- ขจัดงานซ้ำซ้อนข้ามเว็บไซต์ และรวมแหล่งที่มาในฟิลด์ `source`
- คำนวณคะแนนแบบ Multi-Level Ranking:
  1. `Custom_Keyword_Score` (มากไปน้อย - ยิ่งตรงคีย์เวิร์ดยิ่งขึ้นก่อน)
  2. `Days_Ago` (น้อยไปมาก - โพสต์สดใหม่ที่สุด)
  3. `Score` (มากไปน้อย - ความละเอียดของเนื้อหา)
- ส่งออกไฟล์ผลลัพธ์พร้อมคอลัมน์ `Custom_Keyword_Score` และ `Matched_Keywords`

## ต้องทำต่อ (Next / Future)
- ปรับปรุงการ Bypass Cloudflare / Bot Protection สำหรับบางเว็บ (เช่น JobsDB) ในกรณีที่ต้องการดึงข้อมูลความถี่สูงมาก
- ขยาย Dictionary การ Normalize คำศัพท์ตำแหน่งงานภาษาไทย-อังกฤษเพิ่มเติม

## ยังขาด/ความเสี่ยง (Gaps & Risks)
- อาศัยโครงสร้างเว็บและ JSON ของผู้ให้บริการ หากเว็บอัปเดตอาจต้องแก้ Parser (เช่น `__NEXT_DATA__` หรือ `window.SEEK_REDUX_DATA`)
- เว็บไซต์ JobsDB มีระบบ Rate Limit (HTTP 429) ค่อนข้างเข้มงวด หากยิงถี่เกินไปจะถูกจำกัดชั่วคราว (แต่ระบบมี Graceful Error Handling ไม่ทำให้สคริปต์หยุดทำงาน)

## วิธีรัน (Usage & CLI Commands)

### 1. รันแบบพื้นฐาน (Default: Khon Kaen -> Fallback Bangkok)
```powershell
.\.venv\Scripts\python.exe main.py
```

### 2. รันพร้อมระบุคีย์เวิร์ดเพื่อบวกคะแนน
```powershell
.\.venv\Scripts\python.exe main.py --keywords "เบี้ยเลี้ยง,ที่พัก,React,Python,WFH"
```

### 3. รันโดยเปลี่ยนจังหวัด และปิด Fallback
```powershell
.\.venv\Scripts\python.exe main.py --province "Bangkok" --no-fallback --limit 30 --keywords "เบี้ยเลี้ยง,Node"
```

### 4. ตัวเลือกทั้งหมด (All Options)
- `--province`: จังหวัดหลักที่ต้องการค้นหา (Default: `"Khon Kaen"`)
- `--fallback-province`: จังหวัดสำรองหากจังหวัดหลักได้งาน < min-jobs (Default: `"Bangkok"`)
- `--no-fallback`: ปิดระบบ Fallback ไม่ดึงจังหวัดสำรอง
- `--min-jobs`: จำนวนงานขั้นต่ำในจังหวัดหลักก่อนดึงสำรอง (Default: `100`)
- `--category`: หมวดหมู่งาน เช่น `it`, `marketing`, `accounting` (Default: `it`)
- `--limit`: จำนวนงานเป้าหมายสูงสุดต่อเว็บไซต์ (Default: `50`)
- `--keywords`, `-k`: คีย์เวิร์ดคั่นด้วยจุลภาค เช่น `"เบี้ยเลี้ยง,ที่พัก,Python"`
- `--top`: จำนวนงานที่ต้องการ Export ลง `ranked_internships.csv` (Default: `100`)

## ไฟล์ผลลัพธ์
- `outputs/raw_internships.csv`: ข้อมูลงานดิบทั้งหมดที่ผ่านการ Deduplicate แล้ว
- `outputs/ranked_internships.csv`: ข้อมูลงานที่จัดอันดับแล้ว พร้อมคะแนนคีย์เวิร์ด
