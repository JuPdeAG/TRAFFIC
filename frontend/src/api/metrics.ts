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
