import { useQuery } from '@tanstack/react-query';
import { fetchCameras, fetchCameraStats } from '../api/cameras';

export function useCameras(source?: string, onlineOnly = false) {
  return useQuery({
    queryKey: ['cameras', source, onlineOnly],
    queryFn: () => fetchCameras(source, onlineOnly),
    staleTime: 30_000,
    refetchInterval: 60_000,
  });
}

export function useCameraStats() {
  return useQuery({
    queryKey: ['camera-stats'],
    queryFn: fetchCameraStats,
    staleTime: 30_000,
    refetchInterval: 60_000,
  });
}
