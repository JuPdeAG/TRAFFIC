# ML model loading and inference
from traffic_ai.ml.vehicle_detector import detect_vehicles, get_detector, VehicleDetector
from traffic_ai.ml.congestion_model import predict_congestion, get_predictor, CongestionPredictor

__all__ = [
    "detect_vehicles",
    "get_detector",
    "VehicleDetector",
    "predict_congestion",
    "get_predictor",
    "CongestionPredictor",
]
