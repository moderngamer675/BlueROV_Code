from ultralytics import YOLO
import cv2
import cvzone
import math
import torch

# Setup Video
path = "C:/Users/Shahz/Desktop/VS Code Projects/BlueROV_Code/CarsOnRoad.mp4"
vid = cv2.VideoCapture(path)

# Setup Video Writer
w = int(vid.get(cv2.CAP_PROP_FRAME_WIDTH))
h = int(vid.get(cv2.CAP_PROP_FRAME_HEIGHT))
out = cv2.VideoWriter('output_annotated.mp4', cv2.VideoWriter_fourcc(*'mp4v'), 30, (w, h))

# Load Model (Force GPU)
model = YOLO('../YOLO_Weights/yolov8n.pt')
model.to('cuda' if torch.cuda.is_available() else 'cpu')

classNames = ["person", "bicycle", "car", "motorbike", "aeroplane", "bus", "train", "truck", "boat",
              "traffic light", "fire hydrant", "stop sign", "parking meter", "bench", "bird", "cat",
              "dog", "horse", "sheep", "cow", "elephant", "bear", "zebra", "giraffe", "backpack", "umbrella",
              "handbag", "tie", "suitcase", "frisbee", "skis", "snowboard", "sports ball", "kite", "baseball bat",
              "baseball glove", "skateboard", "surfboard", "tennis racket", "bottle", "wine glass", "cup",
              "fork", "knife", "spoon", "bowl", "banana", "apple", "sandwich", "orange", "broccoli",
              "carrot", "hot dog", "pizza", "donut", "cake", "chair", "sofa", "pottedplant", "bed",
              "diningtable", "toilet", "tvmonitor", "laptop", "mouse", "remote", "keyboard", "cell phone",
              "microwave", "oven", "toaster", "sink", "refrigerator", "book", "clock", "vase", "scissors",
              "teddy bear", "hair drier", "toothbrush"]

while True:
    success, img = vid.read()
    if not success: break

    results = model(img, stream=True)

    for r in results:
        boxes = r.boxes
        for box in boxes:
            x1, y1, x2, y2 = boxes.xyxy[0]
            x1, y1, x2, y2 = int(x1), int(y1), int(x2), int(y2)
            cv2.rectangle(img, (x1, y1), (x2, y2), (124, 56, 67), 3)

            conf = math.ceil((box.conf[0] * 100)) / 100
            cls = int(box.cls[0])
            cvzone.putTextRect(img, f'{classNames[cls]} {conf}', (max(0, x1), max(35, y1)), scale=1, thickness=1)

    # Save frame
    out.write(img)

    # Resize for display (70%)
    img_small = cv2.resize(img, (0, 0), fx=0.7, fy=0.7)
    
    cv2.imshow("Image", img_small)

    # Close on 'q' or X button
    if cv2.waitKey(1) & 0xFF == ord('q') or cv2.getWindowProperty("Image", cv2.WND_PROP_VISIBLE) < 1:
        break

vid.release()
out.release()
cv2.destroyAllWindows()