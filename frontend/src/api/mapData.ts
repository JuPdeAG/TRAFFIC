import api from './client';
import type { FeatureCollection } from 'geojson';

export interface MapData {
  flow: FeatureCollection;
  incidents: FeatureCollection;
}

export async function fetchMapData(): Promise<MapData> {
  const { data } = await api.get<MapData>('/map-data');
  return data;
}
