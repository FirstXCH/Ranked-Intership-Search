# Project Name: FreshIntern Ranker (MVP)
**Description:** ระบบ Automated Data Pipeline (ETL) ขนาดย่อม เขียนด้วย Python เพื่อดึงข้อมูลเว็บประกาศรับนักศึกษาฝึกงานสาย IT จัดอันดับด้วย Rule-based scoring (Keyword Match + Time-Decay) และ Export เป็นไฟล์ CSV โดยไม่ใช้ AI API ในการประมวลผลผลลัพธ์(สามารถเสนอจุดที่ต้องใช้งานได้ถ้าง่ายกว่ามี gemini api free)

## 📌 1. Project Goal & Tech Stack
- **Goal:** สร้าง Python script 1 ไฟล์ที่ทำงานแบบ End-to-End (Extract -> Transform -> Load)
- **Primary Language:** Python
- **Required Libraries:** `requests`, `beautifulsoup4`, `pandas`, `datetime`
- **Output:** `ranked_internships.csv`

## 🚀 2. Execution Plan (แผนการทำงานทีละสเตป)
เราจะทำตามสเตปต่อไปนี้อย่างเคร่งครัด ห้ามข้ามขั้น:
- **Step 1 (Extract):** เขียนโค้ดดึง HTML จากหน้าเว็บเป้าหมายเดียว และใช้ `beautifulsoup4` สกัดข้อมูล (ชื่อตำแหน่ง, ชื่อบริษัท, วันที่โพสต์, ลิงก์)
- **Step 2 (Transform - Recency):** แปลงวันที่โพสต์เป็น Date object และคำนวณจำนวนวันที่ผ่านมา จากนั้นเข้าสมการหักคะแนนความใหม่ (Time-Decay)
- **Step 3 (Transform - Keyword):** สแกนหา Keyword ภาษาไทยและอังกฤษในเนื้อหาเพื่อคิดคะแนนความเกี่ยวข้อง แล้วนำมาคำนวณเป็น Total Score
- **Step 4 (Load):** นำข้อมูลเข้า Pandas DataFrame สั่งเรียงลำดับ (Sort) และ Export เป็นไฟล์ `.csv`

## 🛑 3. AI Constraints & Rules (ข้อกำหนดและข้อห้ามอย่างเคร่งครัด)

1. **Focus & No Off-Topic:** โฟกัสการตอบคำถามเฉพาะสเตปที่กำลังทำอยู่เท่านั้น ห้ามนอกเรื่อง ห้ามเสนอสถาปัตยกรรมที่เกินความจำเป็นสำหรับ MVP (เช่น ห้ามพูดถึง Docker, Database, หรือ Cloud Deployment ในตอนนี้)
2. **Teach for Reverse Engineering:** ห้ามโยนโค้ดสำเร็จรูปมาให้ทั้งหมดในรอบเดียว แต่สามารถให้โครงและบอกมาประกอบกันได้ให้เขียน โครงสร้างหรือลอจิกทีละบล็อก พร้อมอธิบายการทำงานเชิงตรรกะให้ชัดเจน เพื่อให้ฉันสามารถแกะโค้ด (Reverse Engineer) และทำความเข้าใจเพื่อนำไปเขียนต่อเองได้
3. **No AI API Services:** ห้ามเสนอให้ใช้ OpenAI API, Gemini API หรือ LLM ใดๆ ในขั้นตอน Transform ข้อมูล ต้องใช้ Programmatic Logic (Rule-based) ถ้า ai ง่ายกว่าก็เสนอได้
4. **Code Quality:** โค้ดที่สร้างขึ้นต้องสะอาด ใช้ชื่อตัวแปรที่สื่อความหมาย (Descriptive Variables) และต้องมี Comment กำกับลอจิกที่ซับซ้อนเป็นภาษาไทย
5. **Clarification First:** หากคำสั่งของฉันกำกวมหรือไม่ชัดเจน ให้ตั้งคำถามสั้นๆ เพื่อขอความชัดเจนก่อนเริ่มสร้างโค้ดเสมอ