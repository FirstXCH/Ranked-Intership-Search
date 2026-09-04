"""
Local HTTP Server สำหรับ Ranked Internship Search
ให้บริการ Dashboard และ REST API สำหรับควบคุมการดึงข้อมูลสด (Live Scraping)
พร้อมรายงานสถานะแบบละเอียด (Real-time Status Monitoring)
"""

import sys
import json
import time
import threading
import argparse
from pathlib import Path
from http.server import ThreadingHTTPServer, SimpleHTTPRequestHandler
from urllib.parse import urlparse, parse_qs
from typing import Dict, Any, Optional

# ป้องกัน UnicodeEncodeError บน Windows terminal (cp874)
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

# สถานะการทำงานส่วนกลาง (Thread-safe state)
_status_lock = threading.Lock()
_scraper_state: Dict[str, Any] = {
    "running": False,
    "step": "idle",
    "message": "พร้อมทำงาน",
    "source": "",
    "sources": {
        "LinkedIn": {"status": "waiting", "count": 0, "error": None},
        "JobThai": {"status": "waiting", "count": 0, "error": None},
        "JobsDB": {"status": "waiting", "count": 0, "error": None},
        "DekFukngan": {"status": "waiting", "count": 0, "error": None},
        "InternTH": {"status": "waiting", "count": 0, "error": None},
    },
    "start_time": 0.0,
    "elapsed_seconds": 0,
    "is_stuck": False,
    "error": None,
    "last_finished": None,
    "total_jobs": 0,
    "logs": [],
}


def get_status_copy() -> Dict[str, Any]:
    with _status_lock:
        state = dict(_scraper_state)
        state["sources"] = {k: dict(v) for k, v in _scraper_state["sources"].items()}
        state["logs"] = list(_scraper_state["logs"][-30:])
        if state["running"] and state["start_time"] > 0:
            elapsed = int(time.time() - state["start_time"])
            state["elapsed_seconds"] = elapsed
            # หากขั้นตอนดึงข้อมูลใช้เวลานานเกิน 25 วินาที ให้เตือนสถานะ
            state["is_stuck"] = elapsed > 25 and state["step"] in ["scraping", "fallback"]
        return state


def update_status(updates: Dict[str, Any]) -> None:
    with _status_lock:
        for k, v in updates.items():
            if k == "sources" and isinstance(v, dict):
                for sk, sv in v.items():
                    if sk in _scraper_state["sources"]:
                        _scraper_state["sources"][sk].update(sv)
                    else:
                        _scraper_state["sources"][sk] = sv
            else:
                _scraper_state[k] = v


def add_log(message: str) -> None:
    timestamp = time.strftime("%H:%M:%S")
    entry = f"[{timestamp}] {message}"
    with _status_lock:
        _scraper_state["logs"].append(entry)
        if len(_scraper_state["logs"]) > 50:
            _scraper_state["logs"].pop(0)


def progress_callback_handler(stage: str, data: Dict[str, Any]) -> None:
    """
    รับความคืบหน้าจาก main.run_pipeline และอัปเดต state
    """
    if stage == "start":
        prov = data.get("province", "Khon Kaen")
        update_status({
            "step": "scraping",
            "message": f"กำลังเริ่มดึงข้อมูลงานใน {prov}...",
            "source": "เริ่มต้นระบบ",
        })
        add_log(f"เริ่มต้นกวาดข้อมูล: {prov}")

    elif stage == "source_start":
        src = data.get("source", "")
        prov = data.get("province", "")
        update_status({
            "step": "scraping",
            "source": src,
            "message": f"กำลังดึงข้อมูลจาก {src} ({prov})...",
            "sources": {src: {"status": "running", "count": 0, "error": None}},
        })
        add_log(f"เริ่มดึงจาก {src} ({prov})")

    elif stage == "source_done":
        src = data.get("source", "")
        count = data.get("count", 0)
        err = data.get("error")
        status = "error" if err else "done"
        update_status({
            "sources": {src: {"status": status, "count": count, "error": err}},
            "message": f"{src}: เสร็จสิ้น (ได้ {count} งาน)",
        })
        if err:
            add_log(f"{src} พบปัญหา: {err} (ข้ามอัตโนมัติ)")
        else:
            add_log(f"{src} ได้รับ {count} ตำแหน่งงาน")

    elif stage == "fallback_start":
        fb_prov = data.get("fallback_province", "Bangkok")
        update_status({
            "step": "fallback",
            "message": f"งานในจังหวัดหลักน้อยกว่าเกณฑ์: กำลังดึงสำรองจาก {fb_prov}...",
        })
        add_log(f"ดึงข้อมูลสำรองจาก {fb_prov}")

    elif stage == "dedup":
        raw = data.get("total_raw", 0)
        deduped = data.get("deduped", 0)
        removed = data.get("removed", 0)
        update_status({
            "step": "dedup",
            "message": f"ตรวจสอบและขจัดงานซ้ำ: พบงานซ้ำ {removed} รายการ (เหลือ {deduped} งาน)",
        })
        add_log(f"ขจัดงานซ้ำออก {removed} รายการ (รวมเหลืองานเด่น {deduped} รายการ)")

    elif stage == "filtering":
        dropped = data.get("dropped_seniors", 0)
        remaining = data.get("remaining", 0)
        update_status({
            "step": "filtering",
            "message": f"คัดกรองเฉพาะงานฝึกงานแท้จริง (กรองงานระดับ Senior ออก {dropped} รายการ)",
        })
        add_log(f"กรองงานระดับ Senior/Manager ออก {dropped} รายการ (เหลืองานฝึกงาน {remaining} รายการ)")

    elif stage == "ranking":
        top = data.get("total_ranked", 0)
        update_status({
            "step": "ranking",
            "message": f"จัดอันดับงาน {top} อันดับแรกตามพื้นที่และคีย์เวิร์ด...",
        })
        add_log(f"จัดอันดับความตรงเป้าหมายเรียบร้อย ({top} อันดับแรก)")

    elif stage == "complete":
        total = data.get("total_jobs", 0)
        update_status({
            "running": False,
            "step": "idle",
            "message": f"ดึงข้อมูลและจัดอันดับสำเร็จ! รวม {total} ตำแหน่งงาน",
            "total_jobs": total,
            "last_finished": time.strftime("%d/%m/%Y %H:%M:%S"),
            "is_stuck": False,
        })
        add_log(f"เสร็จสมบูรณ์: บันทึกข้อมูลและอัปเดตหน้า Dashboard แล้ว ({total} งาน)")


def run_pipeline_worker() -> None:
    try:
        from main import run_pipeline, parse_arguments
        args = parse_arguments()
        run_pipeline(args=args, progress_callback=progress_callback_handler)
    except Exception as e:
        update_status({
            "running": False,
            "step": "error",
            "error": str(e),
            "message": f"เกิดข้อผิดพลาดในการดึงข้อมูล: {e}",
            "is_stuck": False,
        })
        add_log(f"ข้อผิดพลาดร้ายแรง: {e}")


class ScraperRequestHandler(SimpleHTTPRequestHandler):
    """
    HTTP Request Handler ที่ให้บริการทั้ง Dashboard HTML และ REST API
    """

    def end_headers(self) -> None:
        # ใส่ CORS Headers ทุก Response เพื่อให้เปิดจาก file:// ได้
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.send_header("Cache-Control", "no-cache, no-store, must-revalidate")
        super().end_headers()

    def do_OPTIONS(self) -> None:
        self.send_response(204)
        self.end_headers()

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        path = parsed.path

        if path in ["/", "/index.html", "/dashboard", "/dashboard.html"]:
            dashboard_file = Path("outputs/dashboard.html")
            if not dashboard_file.exists():
                self.send_response(404)
                self.send_header("Content-Type", "text/plain; charset=utf-8")
                self.end_headers()
                self.wfile.write("ไม่พบไฟล์ outputs/dashboard.html กรุณารันการดึงข้อมูลครั้งแรก".encode("utf-8"))
                return

            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write(dashboard_file.read_bytes())
            return

        if path == "/api/status":
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.end_headers()
            status_data = get_status_copy()
            self.wfile.write(json.dumps(status_data, ensure_ascii=False).encode("utf-8"))
            return

        if path == "/api/jobs":
            ranked_csv = Path("outputs/ranked_internships.csv")
            if not ranked_csv.exists():
                self.send_response(200)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.end_headers()
                self.wfile.write(json.dumps([], ensure_ascii=False).encode("utf-8"))
                return

            try:
                import pandas as pd
                df = pd.read_csv(ranked_csv, encoding="utf-8-sig")
                jobs_list = df.to_dict(orient="records")
                self.send_response(200)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.end_headers()
                self.wfile.write(json.dumps(jobs_list, ensure_ascii=False).encode("utf-8"))
            except Exception as ex:
                self.send_response(500)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.end_headers()
                self.wfile.write(json.dumps({"error": str(ex)}, ensure_ascii=False).encode("utf-8"))
            return

        # Static files fallback
        super().do_GET()

    def do_POST(self) -> None:
        parsed = urlparse(self.path)
        path = parsed.path

        if path == "/api/scrape":
            with _status_lock:
                if _scraper_state["running"]:
                    self.send_response(409)
                    self.send_header("Content-Type", "application/json; charset=utf-8")
                    self.end_headers()
                    self.wfile.write(json.dumps({"status": "already_running", "message": "ระบบกำลังดึงข้อมูลอยู่แล้ว"}, ensure_ascii=False).encode("utf-8"))
                    return

                # เริ่มกระบวนการดึงข้อมูลใหม่
                _scraper_state["running"] = True
                _scraper_state["step"] = "starting"
                _scraper_state["message"] = "กำลังเตรียมเริ่มระบบดึงข้อมูล..."
                _scraper_state["start_time"] = time.time()
                _scraper_state["elapsed_seconds"] = 0
                _scraper_state["is_stuck"] = False
                _scraper_state["error"] = None
                for k in _scraper_state["sources"]:
                    _scraper_state["sources"][k] = {"status": "waiting", "count": 0, "error": None}
                _scraper_state["logs"] = []

            add_log("ได้รับคำสั่งดึงข้อมูลสดผ่านเว็บเบราว์เซอร์")

            worker_thread = threading.Thread(target=run_pipeline_worker, daemon=True)
            worker_thread.start()

            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.end_headers()
            self.wfile.write(json.dumps({"status": "started", "message": "เริ่มต้นกวาดข้อมูลเรียบร้อย"}, ensure_ascii=False).encode("utf-8"))
            return

        self.send_response(404)
        self.end_headers()


def start_server(port: int = 8000) -> None:
    server_address = ("", port)
    try:
        httpd = ThreadingHTTPServer(server_address, ScraperRequestHandler)
    except OSError:
        # หากพอร์ต 8000 ไม่ว่าง ให้ขยับไป 8080
        port = 8080
        server_address = ("", port)
        httpd = ThreadingHTTPServer(server_address, ScraperRequestHandler)

    print("=" * 60)
    print(f"[*] Ranked Internship Search Dashboard Server")
    print(f"[*] เปิดดูหน้าเว็บได้ที่: http://localhost:{port}/")
    print(f"[*] มีระบบ REST API พร้อมใช้งานสำหรับการดึงข้อมูลสด")
    print(f"[*] กด Ctrl+C เพื่อหยุดการทำงานของเซิร์ฟเวอร์")
    print("=" * 60)

    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\n[*] ปิดเซิร์ฟเวอร์เรียบร้อย")
        httpd.server_close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Ranked Internship Search HTTP Server")
    parser.add_argument("--port", type=int, default=8000, help="หมายเลข Port (ค่าเริ่มต้น: 8000)")
    args = parser.parse_args()
    start_server(port=args.port)
