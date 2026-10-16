from app.services.detector_factory import create_detector
from app.workers.detection_worker import DetectionWorker

worker = DetectionWorker(detector=create_detector())
