#!/usr/bin/env python
"""Download YOLOv8n model"""
from ultralytics import YOLO

print("📥 Downloading YOLOv8n model...")
model = YOLO('yolov8n.pt')
print("✅ YOLOv8n loaded successfully!")
print(f"📊 Model info: {model}")
