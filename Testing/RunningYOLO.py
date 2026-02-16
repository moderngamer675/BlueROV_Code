from ultralytics import YOLO
import cv2

# Load the model
model = YOLO('../YOLO_Weights/yolov8m.pt')

# 1. Run detection, but set show=False (We will show it ourselves)
results = model("cars.png", show=False)

# 2. Get the image with the boxes drawn on it
# results[0] is the first result (since we only gave one image)
# .plot() creates the numpy array with the boxes drawn
final_image = results[0].plot()

# 3. Open the window manually
cv2.imshow("My Detection", final_image)

# 4. Wait forever (0) until a key is pressed
cv2.waitKey(0)
cv2.destroyAllWindows()