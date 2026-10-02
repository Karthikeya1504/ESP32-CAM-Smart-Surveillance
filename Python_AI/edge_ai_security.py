import cv2
import time
import math
import threading
import base64
import requests
import pyttsx3 # type: ignore
import sqlite3
import csv
import os
from collections import deque
from datetime import datetime
from ultralytics import YOLO

# ==========================================
# 1. TELEGRAM BOT & SYSTEM CONFIGURATION
# ==========================================
TELEGRAM_BOT_TOKEN = "YOUR_TELEGRAM_BOT_TOKEN"
TELEGRAM_CHAT_ID = "YOUR_TELEGRAM_CHAT_ID"

# ESP32-CAM IP address
ESP32_IP = "YOUR_ESP32_IP" 

model = YOLO("yolov8n.pt") 
TARGET_CLASSES = [24, 26, 28, 39, 67] # Backpack, Handbag, Suitcase, Bottle, Phone
PERSON_CLASS = 0
DISTANCE_THRESHOLD = 180 
ALERT_TIMER = 10  

unattended_timers = {}
alert_triggered_for_id = []

# Concurrency lock for Ollama
ollama_lock = threading.Lock()

# Shared state variables
global latest_frame, is_armed, current_telemetry
latest_frame = None
is_armed = True
current_telemetry = {"people": 0, "objects": []}

recent_events = deque(maxlen=5)

# ==========================================
# 2. ZERO-LAG STREAMING ENGINE (AUTO-RECONNECT)
# ==========================================
class FreshestFrame(threading.Thread):
    """Background thread that consumes frames and auto-reconnects on Wi-Fi drops."""
    def __init__(self, stream_url):
        super().__init__(daemon=True)
        self.stream_url = stream_url
        self.capture = cv2.VideoCapture(self.stream_url)
        self.capture.set(cv2.CAP_PROP_BUFFERSIZE, 1)
        self.latest_frame = None
        self.ret = False
        self.running = True
        self.start()

    def run(self):
        while self.running:
            try:
                self.ret, frame = self.capture.read()
                if self.ret:
                    self.latest_frame = frame
                else:
                    print("[WARNING] Wi-Fi Stream dropped. Attempting reconnect...")
                    self.capture.release()
                    time.sleep(1) # Wait before reconnecting
                    self.capture = cv2.VideoCapture(self.stream_url)
                    self.capture.set(cv2.CAP_PROP_BUFFERSIZE, 1)
            except Exception as e:
                print(f"[ERROR] Stream thread failure: {e}")
                time.sleep(1)

    def read(self):
        return self.ret, self.latest_frame

print(f"Connecting to ESP32-CAM stream at {ESP32_IP}...")
fresh_cap = FreshestFrame(f"http://{ESP32_IP}:81/stream")

# ==========================================
# 3. DATABASE & AUDIO ENGINE SETUP
# ==========================================
def init_db():
    """Initializes the SQLite database for logging incidents."""
    conn = sqlite3.connect('security_logs.db')
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS incidents
                 (id INTEGER PRIMARY KEY AUTOINCREMENT,
                  timestamp TEXT,
                  object_type TEXT,
                  summary TEXT)''')
    conn.commit()
    conn.close()

init_db()

def speak_warning(object_name):
    """Plays an audible warning safely in a Windows background thread."""
    try:
        import pythoncom  # type: ignore
        pythoncom.CoInitialize()
        engine = pyttsx3.init()
        engine.setProperty('rate', 160)
        engine.say(f"Warning. Unattended {object_name} detected.")
        engine.runAndWait()
    except Exception as e:
        print(f"[AUDIO ERROR] {e}")

def calculate_distance(p1, p2):
    return math.sqrt((p1[0] - p2[0])**2 + (p1[1] - p2[1])**2)

def image_to_base64(image_path):
    with open(image_path, "rb") as image_file:
        return base64.b64encode(image_file.read()).decode('utf-8')

# ==========================================
# 4. CAM FRIEND LISTENER THREAD
# ==========================================
def poll_telegram_commands():
    global is_armed, current_telemetry, latest_frame
    print("[SYSTEM] Cam Friend Listener Active. Awaiting commands & questions...")
    last_update_id = 0
    
    while True:
        try:
            url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/getUpdates?offset={last_update_id}&timeout=5"
            response = requests.get(url, timeout=10).json()
            
            if response.get("ok"):
                for result in response["result"]:
                    last_update_id = result["update_id"] + 1
                    message_text = result.get("message", {}).get("text", "")
                    chat_id = result.get("message", {}).get("chat", {}).get("id")
                    
                    if not message_text or latest_frame is None:
                        continue

                    # COMMAND: /status
                    if message_text == "/status":
                        print("\n[SYSTEM] /status received! Capturing state...")
                        status_img_path = "status_snapshot.jpg"
                        cv2.imwrite(status_img_path, latest_frame)
                        img_b64 = image_to_base64(status_img_path)
                        
                        people_count = current_telemetry["people"]
                        detected_objs = ", ".join(current_telemetry["objects"]) if current_telemetry["objects"] else "None"
                        memory_string = "\n".join(recent_events) if recent_events else "No recent notable security events."
                        
                        prompt = (
                            f"You are a security AI. Camera detects {people_count} person(s) and {detected_objs}. "
                            f"Recent timeline:\n{memory_string}\n"
                            "Provide a factual 2-sentence summary of the scene."
                        )
                        
                        ai_description = "Visual AI processing timed out. Displaying raw telemetry."
                        try:
                            with ollama_lock:
                                moondream_resp = requests.post("http://localhost:11434/api/generate", json={
                                    "model": "moondream", "prompt": prompt, "images": [img_b64], "stream": False
                                }, timeout=90).json()
                                ai_description = moondream_resp.get("response", "Scene captured successfully.")
                                
                                # Catch Moondream coordinate hallucinations on blurry images
                                if ai_description.strip().startswith("ids:"):
                                    ai_description = "The image is too blurry for the AI to generate a clear text description. Please check the raw telemetry above."
                                    
                        except Exception:
                            pass

                        state_icon = "🔴 ARMED" if is_armed else "🟢 DISARMED"
                        caption_text = f"📸 **Status [{state_icon}]**\n👥 People: {people_count}\n📦 Objects: {detected_objs}\n\n🤖 **Summary:**\n{ai_description}"
                        
                        with open(status_img_path, 'rb') as photo:
                            requests.post(f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendPhoto", 
                                          data={'chat_id': chat_id, 'caption': caption_text, 'parse_mode': 'Markdown'}, files={'photo': photo})

                    # COMMAND: /history
                    elif message_text == "/history":
                        print("\n[SYSTEM] /history received! Generating report...")
                        csv_filename = "incidents_report.csv"
                        conn = sqlite3.connect('security_logs.db')
                        c = conn.cursor()
                        c.execute("SELECT timestamp, object_type, summary FROM incidents ORDER BY id DESC LIMIT 50")
                        rows = c.fetchall()
                        conn.close()

                        with open(csv_filename, 'w', newline='', encoding='utf-8') as f:
                            writer = csv.writer(f)
                            writer.writerow(["Timestamp", "Object Type", "AI Summary"])
                            writer.writerows(rows)

                        with open(csv_filename, 'rb') as doc:
                            requests.post(f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendDocument",
                                          data={'chat_id': chat_id, 'caption': '📄 Here is your recent security incident log.'}, files={'document': doc})

                    # COMMAND: /buzzer
                    elif message_text == "/buzzer":
                        print("\n[SYSTEM] /buzzer received! Pinging ESP32-CAM...")
                        try:
                            requests.get(f"http://{ESP32_IP}:82/buzzer", timeout=5)
                            requests.get(f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage", 
                                         params={'chat_id': chat_id, 'text': '🔊 **Buzzer Activated!** Hardware alarm triggered on ESP32-CAM.', 'parse_mode': 'Markdown'})
                        except Exception as e:
                            requests.get(f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage", 
                                         params={'chat_id': chat_id, 'text': f'❌ **Hardware Error:** Could not reach ESP32-CAM at {ESP32_IP}. Ensure it is powered and connected to Wi-Fi.', 'parse_mode': 'Markdown'})

                    # COMMANDS: /arm and /disarm
                    elif message_text == "/disarm":
                        is_armed = False
                        requests.get(f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage?chat_id={chat_id}&text=🟢 **System DISARMED.** Tracking paused.", params={'parse_mode': 'Markdown'})

                    elif message_text == "/arm":
                        is_armed = True
                        requests.get(f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage?chat_id={chat_id}&text=🔴 **System ARMED.** AI tracking active.", params={'parse_mode': 'Markdown'})

                    # FEATURE: Conversational VQA 
                    elif not message_text.startswith("/"):
                        print(f"\n[SYSTEM] Question received: '{message_text}' - Asking Moondream...")
                        vqa_img_path = "vqa_snapshot.jpg"
                        cv2.imwrite(vqa_img_path, latest_frame)
                        img_b64 = image_to_base64(vqa_img_path)

                        try:
                            with ollama_lock:
                                moondream_resp = requests.post("http://localhost:11434/api/generate", json={
                                    "model": "moondream", "prompt": message_text, "images": [img_b64], "stream": False
                                }, timeout=90).json()
                                answer = moondream_resp.get("response", "I could not analyze the image.")
                                
                                # Catch hallucinations here too
                                if answer.strip().startswith("ids:"):
                                    answer = "The image is too blurry for me to see clearly right now."
                        except Exception:
                            answer = "AI Processing Timeout. I am currently overwhelmed."
                        
                        requests.get(f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage", 
                                     params={'chat_id': chat_id, 'text': f"🗣️ **Cam Friend Says:**\n{answer}", 'parse_mode': 'Markdown'})

        except Exception:
            pass
            
        time.sleep(0.5) 

# ==========================================
# 5. LOCAL AI INCIDENT DISPATCH (ALARM & LOG)
# ==========================================
def generate_and_send_report(entry_img_path, abandoned_img_path, object_name):
    print(f"\n[SYSTEM] Unattended {object_name} detected. Analyzing and logging...")
    
    report_text = "⚠️ **AI Processing Timeout**\nLocal AI took too long, but an incident was logged."
    
    try:
        img1_b64 = image_to_base64(entry_img_path)
        img2_b64 = image_to_base64(abandoned_img_path)
        
        prompt = (
            "You are a security AI. Inspect these two sequential frames. "
            "Describe the person who dropped the item, identify the object, "
            "and give a brief 3-bullet incident report."
        )
        
        with ollama_lock:
            response = requests.post("http://localhost:11434/api/generate", json={
                "model": "moondream", "prompt": prompt, "images": [img1_b64, img2_b64], "stream": False
            }, timeout=90)
            if response.status_code == 200:
                report_text = response.json().get("response", report_text)
                
                # Catch hallucinations in alert reports
                if report_text.strip().startswith("ids:"):
                    report_text = "The AI could not generate a clear text summary due to motion blur, but an object was left unattended."
                
    except Exception as e:
        print(f"[WARNING] Local AI timed out: {e}")
        
    # Log to SQLite Database
    try:
        conn = sqlite3.connect('security_logs.db')
        c = conn.cursor()
        timestamp_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        c.execute("INSERT INTO incidents (timestamp, object_type, summary) VALUES (?, ?, ?)",
                  (timestamp_str, object_name, report_text))
        conn.commit()
        conn.close()
    except Exception as e:
        print(f"[ERROR] Failed to save to database: {e}")

    # Send Telegram Alert
    try:
        with open(abandoned_img_path, 'rb') as photo:
            requests.post(f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendPhoto", 
                          data={'chat_id': TELEGRAM_CHAT_ID, 'caption': f"🚨 **UNATTENDED {object_name.upper()}** 🚨\n\n{report_text}", 'parse_mode': 'Markdown'}, 
                          files={'photo': photo})
    except Exception as e:
        print(f"[ERROR] Failed to send Telegram alert: {e}")

# ==========================================
# 6. MAIN EDGE VISION LOOP
# ==========================================
print("Starting Advanced Local Edge AI Security System... Press 'q' to exit.")

threading.Thread(target=poll_telegram_commands, daemon=True).start()

# Use fresh_cap to read from the threaded buffer
ret, baseline_frame = fresh_cap.read()
if ret and baseline_frame is not None:
    cv2.imwrite("baseline_entry.jpg", baseline_frame)

while True:
    ret, frame = fresh_cap.read()
    if not ret or frame is None:
        time.sleep(0.01)
        continue  

    people_centers = []
    current_objects = []
    detected_obj_names = []

    if is_armed:
        results = model.track(frame, persist=True, conf=0.5, verbose=False)

        for r in results:
            boxes = r.boxes
            if boxes is None or len(boxes) == 0:
                continue

            for box in boxes:
                cls_id = int(box.cls[0])
                x1, y1, x2, y2 = map(int, box.xyxy[0])
                cx, cy = int((x1 + x2) / 2), int((y1 + y2) / 2)

                if cls_id == PERSON_CLASS:
                    people_centers.append((cx, cy))
                    cv2.rectangle(frame, (x1, y1), (x2, y2), (255, 0, 0), 2)
                    cv2.putText(frame, "Person", (x1, y1 - 8), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 0, 0), 2)
                
                elif cls_id in TARGET_CLASSES and box.id is not None:
                    obj_id = int(box.id[0])
                    name = model.names[cls_id]
                    detected_obj_names.append(name)
                    current_objects.append((obj_id, name, cx, cy, (x1, y1, x2, y2)))

        for obj_id, class_name, cx, cy, (x1, y1, x2, y2) in current_objects:
            is_person_near = any(calculate_distance((cx, cy), (px, py)) < DISTANCE_THRESHOLD for px, py in people_centers)

            if is_person_near:
                if obj_id in unattended_timers:
                    del unattended_timers[obj_id]
                    timestamp = datetime.now().strftime("%H:%M:%S")
                    recent_events.append(f"[{timestamp}] The {class_name} was attended to by a person.")
                
                cv2.rectangle(frame, (x1, y1), (x2, y2), (0, 255, 0), 2)
                cv2.putText(frame, f"{class_name} (Attended)", (x1, y1 - 8), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 0), 2)
                cv2.imwrite("snapshot_entry.jpg", frame)

            else:
                if obj_id not in unattended_timers:
                    unattended_timers[obj_id] = time.time()
                    timestamp = datetime.now().strftime("%H:%M:%S")
                    recent_events.append(f"[{timestamp}] A {class_name} was left unattended.")

                elapsed_time = int(time.time() - unattended_timers[obj_id])

                if elapsed_time >= ALERT_TIMER and obj_id not in alert_triggered_for_id:
                    cv2.imwrite("snapshot_abandoned.jpg", frame)
                    alert_triggered_for_id.append(obj_id)
                    timestamp = datetime.now().strftime("%H:%M:%S")
                    recent_events.append(f"[{timestamp}] ALARM: {class_name} abandoned!")
                    
                    # TRIGGER 1: Audio Deterrent
                    threading.Thread(target=speak_warning, args=(class_name,), daemon=True).start()
                    
                    # TRIGGER 2: AI Report & DB Logging
                    threading.Thread(target=generate_and_send_report, args=("snapshot_entry.jpg", "snapshot_abandoned.jpg", class_name)).start()

                color = (0, 0, 255) if elapsed_time >= ALERT_TIMER else (0, 165, 255)
                cv2.rectangle(frame, (x1, y1), (x2, y2), color, 2)
                cv2.putText(frame, f"{class_name} {elapsed_time}s Unattended", (x1, y1 - 8), cv2.FONT_HERSHEY_SIMPLEX, 0.5, color, 2)

    else:
        cv2.putText(frame, "SYSTEM DISARMED - AI PAUSED", (10, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 0), 2)

    current_telemetry = {"people": len(people_centers), "objects": detected_obj_names}
    latest_frame = frame.copy()

    cv2.imshow("Security Feed", frame)
    if cv2.waitKey(1) & 0xFF == ord('q'):
        break

fresh_cap.running = False
fresh_cap.capture.release()
cv2.destroyAllWindows()
