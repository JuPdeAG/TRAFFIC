import { useQuery } from '@tanstack/react-query';
import { fetchTrafficFlow, fetchRiskTrend } from '../api/metrics';

export function useTrafficFlow(hours = 24, segmentId?: string) {
  return useQuery({
    queryKey: ['traffic-flow', hours, segmentId],
    queryFn: () => fetchTrafficFlow(hours, segmentId),
    staleTime: 60_000,
    refetchInterval: 120_000,
  });
}

export function useRiskTrend(days = 30) {
  return useQuery({
    queryKey: ['risk-trend', days],
    queryFn: () => fetchRiskTrend(days),
    staleTime: 5 * 60_000,
    refetchInterval: 10 * 60_000,
  });
}
