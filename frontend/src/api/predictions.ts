import api from './client';

export interface PredictionRequest {
  segment_id: string;
  horizon_minutes: number;
}

export interface PredictionResult {
  segment_id: string;
  predicted_speed_kmh: number;
  congestion_level: string;
  confidence: number;
  horizon_minutes: number;
  predicted_at: string;
}

export async function fetchPrediction(req: PredictionRequest): Promise<PredictionResult> {
  const { data } = await api.post<PredictionResult>('/predict/congestion', req);
  return data;
}
