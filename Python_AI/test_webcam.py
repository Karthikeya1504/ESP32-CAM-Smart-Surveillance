import cv2
from ultralytics import YOLO

# 1. Load the lightweight YOLOv8 Nano pre-trained model
# On the first run, this will automatically download 'yolov8n.pt' (~6MB)
model = YOLO("yolov8n.pt")

# 2. Connect to the laptop webcam (0 = built-in webcam)
cap = cv2.VideoCapture(0)

if not cap.isOpened():
    print("Error: Could not open webcam.")
    exit()

print("Starting webcam feed... Press 'q' to exit.")

while True:
    ret, frame = cap.read()
    if not ret:
        print("Error: Couldn't read frame from webcam.")
        break

    # 3. Run YOLOv8 detection on the frame
    results = model(frame, stream=True)

    # 4. Draw bounding boxes and labels on the frame
    for r in results:
        annotated_frame = r.plot()

    # 5. Show the live feed in a window
    cv2.imshow("YOLOv8 Webcam Test", annotated_frame)

    # Press 'q' on your keyboard to exit
    if cv2.waitKey(1) & 0xFF == ord('q'):
        break

# Clean up resources
cap.release()
cv2.destroyAllWindows()
