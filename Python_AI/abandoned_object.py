import cv2
import time
import math
from ultralytics import YOLO

# 1. Load the YOLOv8 Nano model
model = YOLO("yolov8n.pt")

# 2. COCO Dataset Class IDs
PERSON_CLASS = 0
# Target objects to monitor: Backpack (24), Handbag (26), Suitcase (28), Bottle (39), Phone (67)
TARGET_CLASSES = [24, 26, 28, 39, 67] 

# Distance threshold (in pixels) to decide if a person is "near" an object
DISTANCE_THRESHOLD = 180 

# Time threshold (in seconds) before flagging an object as abandoned
ALERT_TIMER = 5  # Set to 5 seconds for easy testing

# Dictionary to store start time for unattended objects: {object_id: start_timestamp}
unattended_timers = {}

def calculate_distance(p1, p2):
    """Calculates Euclidean distance between two center points."""
    return math.sqrt((p1[0] - p2[0])**2 + (p1[1] - p2[1])**2)

cap = cv2.VideoCapture(0)

print("Starting Abandoned Object Tracking... Press 'q' to exit.")

while True:
    ret, frame = cap.read()
    if not ret:
        print("Error reading frame from webcam.")
        break

    # Run YOLOv8 object tracking (persist=True maintains IDs across frames)
    results = model.track(frame, persist=True, verbose=False)
    
    people_centers = []
    current_objects = [] # Stores (object_id, class_name, center_x, center_y, box_coords)

    for r in results:
        boxes = r.boxes
        if boxes is None or len(boxes) == 0:
            continue

        for box in boxes:
            cls_id = int(box.cls[0])
            x1, y1, x2, y2 = map(int, box.xyxy[0])
            cx, cy = int((x1 + x2) / 2), int((y1 + y2) / 2) # Object center point

            # If it's a Person
            if cls_id == PERSON_CLASS:
                people_centers.append((cx, cy))
                cv2.rectangle(frame, (x1, y1), (x2, y2), (255, 0, 0), 2)
                cv2.putText(frame, "Person", (x1, y1 - 10), 
                            cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 0, 0), 2)

            # If it's a Target Object and has a valid tracking ID
            elif cls_id in TARGET_CLASSES and box.id is not None:
                obj_id = int(box.id[0])
                class_name = model.names[cls_id]
                current_objects.append((obj_id, class_name, cx, cy, (x1, y1, x2, y2)))

    # Evaluate each tracked object
    for obj_id, class_name, cx, cy, (x1, y1, x2, y2) in current_objects:
        is_person_near = False

        # Check distance between this object and every person in frame
        for px, py in people_centers:
            if calculate_distance((cx, cy), (px, py)) < DISTANCE_THRESHOLD:
                is_person_near = True
                cv2.line(frame, (cx, cy), (px, py), (0, 255, 0), 2) # Draw connection line
                break

        if is_person_near:
            # Person is nearby -> Object is safe -> Reset timer
            if obj_id in unattended_timers:
                del unattended_timers[obj_id]
            
            cv2.rectangle(frame, (x1, y1), (x2, y2), (0, 255, 0), 2)
            cv2.putText(frame, f"SAFE: {class_name} #{obj_id}", (x1, y1 - 10), 
                        cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 0), 2)
        else:
            # No person nearby!
            if obj_id not in unattended_timers:
                unattended_timers[obj_id] = time.time() # Start clock

            elapsed_time = int(time.time() - unattended_timers[obj_id])

            if elapsed_time >= ALERT_TIMER:
                # Timer limit exceeded -> RED ALERT
                color = (0, 0, 255)
                status_text = f"ALERT: ABANDONED {class_name.upper()} ({elapsed_time}s)"
                cv2.putText(frame, "WARNING: UNATTENDED OBJECT!", (x1, y2 + 25), 
                            cv2.FONT_HERSHEY_SIMPLEX, 0.6, color, 2)
            else:
                # Timer counting down -> ORANGE WARNING
                color = (0, 165, 255)
                status_text = f"Unattended: {elapsed_time}s / {ALERT_TIMER}s"

            cv2.rectangle(frame, (x1, y1), (x2, y2), color, 2)
            cv2.putText(frame, status_text, (x1, y1 - 10), 
                        cv2.FONT_HERSHEY_SIMPLEX, 0.5, color, 2)

    cv2.imshow("Edge AI Security Tracker", frame)

    if cv2.waitKey(1) & 0xFF == ord('q'):
        break

cap.release()
cv2.destroyAllWindows()
