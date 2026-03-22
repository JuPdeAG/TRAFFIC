import api from './client';

export interface FlowPoint {
  time: string;
  flow: number;
  volume: number | null;
}

export interface RiskTrendPoint {
  day: string;
  score: number;
}

export interface CityState {
  city: string;
  label: string;
  avg_density: number | null;
  avg_speed_kmh: number | null;
  reading_count: number;
  last_updated: string | null;
}

export interface TrafficStateResponse {
  cities: CityState[];
  national: {
    avg_congestion: number | null;
    tomtom_points_live: number;
  };
}

export interface CongestionTrendPoint {
  time: string;
  madrid: number | null;
  valencia: number | null;
  barcelona: number | null;
  tomtom: number | null;
}

export async function fetchTrafficFlow(hours = 24, segmentId?: string): Promise<FlowPoint[]> {
  const { data } = await api.get<FlowPoint[]>('/metrics/flow', {
    params: { hours, ...(segmentId ? { segment_id: segmentId } : {}) },
  });
  return data;
}

export async function fetchRiskTrend(days = 30): Promise<RiskTrendPoint[]> {
  const { data } = await api.get<RiskTrendPoint[]>('/metrics/risk-trend', { params: { days } });
  return data;
}

export async function fetchTrafficState(): Promise<TrafficStateResponse> {
  const { data } = await api.get<TrafficStateResponse>('/traffic-state');
  return data;
}

export async function fetchCongestionTrend(hours = 24): Promise<CongestionTrendPoint[]> {
  const { data } = await api.get<CongestionTrendPoint[]>('/metrics/congestion-trend', {
    params: { hours },
  });
  return data;
}
