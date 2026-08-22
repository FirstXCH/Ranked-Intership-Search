# Work Log - FreshIntern Ranker

## ทำไปแล้ว (Done)
- วางโครง ETL ใน [main.py](d:/learnCode/Ranked-Internship-Search/main.py)
- ดึงข้อมูลจาก JobThai ด้วย `requests`
- แกะ `__NEXT_DATA__` เพื่ออ่านรายการงานจาก payload
- ดึงข้อมูลรายละเอียดงานรายโพสต์ (description, benefits, updated_at)
- บันทึกข้อมูลดิบไปที่ `outputs/raw_internships.csv`
- เพิ่มการให้คะแนนคีย์เวิร์ดผู้ใช้ (`Custom_Keyword_Score`)
- เพิ่มการคำนวณความใหม่ของโพสต์ (`Days_Ago`)
- จัดเรียงอันดับตาม:
  1. `Custom_Keyword_Score` มาก -> น้อย
  2. `Days_Ago` น้อย -> มาก
- ส่งออกผลลัพธ์ไปที่ `outputs/ranked_khonkaen_internships.csv`
- เพิ่มไฟล์คะแนนก่อนกรองที่ `outputs/scored_all_internships.csv`
- จัดระบบไฟล์ CSV ไปไว้โฟลเดอร์ `outputs/`
- ปรับ `.gitignore` ให้ ignore โฟลเดอร์ outputs และไฟล์ CSV ที่ generate
- ปรับ filter ขอนแก่นให้เช็คด้วย `province_id=06` เพื่อให้แม่นยำ

## กำลังใช้งานตอนนี้ (Current Behavior)
- ค่าเริ่มต้นค้นหาจาก:
  - `https://www.jobthai.com/th/jobs?jobtype=7&subjobtype=52&province=06`
- รับคีย์เวิร์ดเพิ่มจากผู้ใช้ตอนรัน
- ถ้าไม่กรอกคีย์เวิร์ด คะแนนจะเป็น 0 ทุกแถว (ตาม logic ปัจจุบัน)

## ต้องทำต่อ (Next)
- รองรับการดึงหลายหน้า (page 1..N)
- เพิ่ม fallback ถ้าเว็บเปลี่ยนโครงสร้าง payload
- เพิ่ม config แยกสำหรับหลายแหล่งข้อมูล (multi-source)
- เพิ่ม deduplication งานซ้ำ (เช่นซ้ำจากลิงก์หรือ company+title)
- เพิ่มพารามิเตอร์ CLI:
  - จังหวัดเป้าหมาย
  - jobtype/subjobtype
  - จำนวนหน้าที่จะดึง
  - รายการคีย์เวิร์ด

## ยังขาด/ความเสี่ยง (Gaps & Risks)
- พึ่งพาโครงสร้าง `__NEXT_DATA__` ของเว็บเป้าหมาย
- ตอนนี้รันแค่หน้าเดียว (อาจพลาดงานที่อยู่หน้าถัดไป)
- ไม่มี unit tests สำหรับ parser/filter/ranking
- ยังไม่รองรับ retry/backoff เมื่อ request ล้มเหลวชั่วคราว
- คะแนน keyword ยังเป็นแบบนับคำตรงตัว (exact substring) เท่านั้น

## วิธีรัน (Quick Run)
```powershell
.\.venv\Scripts\python.exe main.py
```

## ไฟล์ผลลัพธ์
- `outputs/raw_internships.csv`
- `outputs/scored_all_internships.csv`
- `outputs/ranked_khonkaen_internships.csv`
