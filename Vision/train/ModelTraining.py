from ultralytics import YOLO

if __name__ == '__main__':
    # 1. Load the pre-trained 'Nano' model (lightweight and fast)
    model = YOLO('yolov8n.pt')

    # 2. Train the model
    # data: path to your yaml file
    # epochs: how many times it reviews the images (50 is good for a start)
    # imgsz: standard image size
    # device: 0 uses your GTX 1650 GPU
    model.train(
    data=r'C:\Users\Shahz\Desktop\VS Code Projects\BlueROV_Code\Vision\data.yaml',
    epochs=50,
    imgsz=640,
    device=0
    )

    print("Training finished! Look in 'runs/detect/train/weights' for best.pt")