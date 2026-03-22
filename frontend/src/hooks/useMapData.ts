import { useQuery } from '@tanstack/react-query';
import { fetchMapData } from '../api/mapData';

export function useMapData() {
  return useQuery({
    queryKey: ['map-data'],
    queryFn: fetchMapData,
    refetchInterval: 60_000,
    staleTime: 30_000,
  });
}
