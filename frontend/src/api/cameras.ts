import api from './client';

export interface CameraMetric {
  id: string;
  source: 'dgt' | 'madrid' | string;
  road: string;
  vehicle_count: number;
  density_score: number;
  density_level: string;
  camera_online: boolean;
  last_seen: string | null;
}

export interface CameraStats {
  total: number;
  online: number;
  offline: number;
  avg_density_score: number;
}

export async function fetchCameras(source?: string, onlineOnly = false): Promise<CameraMetric[]> {
  const { data } = await api.get<CameraMetric[]>('/cameras', {
    params: { ...(source ? { source } : {}), online_only: onlineOnly, limit: 200 },
  });
  return data;
}

export async function fetchCameraStats(): Promise<CameraStats> {
  const { data } = await api.get<CameraStats>('/cameras/stats');
  return data;
}
