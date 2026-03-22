import { useQuery } from '@tanstack/react-query';
import { fetchTrafficFlow, fetchRiskTrend, fetchTrafficState, fetchCongestionTrend } from '../api/metrics';

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

export function useTrafficState() {
  return useQuery({
    queryKey: ['traffic-state'],
    queryFn: fetchTrafficState,
    staleTime: 30_000,
    refetchInterval: 60_000,
  });
}

export function useCongestionTrend(hours = 24) {
  return useQuery({
    queryKey: ['congestion-trend', hours],
    queryFn: () => fetchCongestionTrend(hours),
    staleTime: 60_000,
    refetchInterval: 120_000,
  });
}
