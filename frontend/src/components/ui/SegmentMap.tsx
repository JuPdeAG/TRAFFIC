import { useState, useCallback } from 'react';
import Map, { Source, Layer, Popup, NavigationControl } from 'react-map-gl/maplibre';
import 'maplibre-gl/dist/maplibre-gl.css';
import type { MapLayerMouseEvent } from 'react-map-gl/maplibre';
import type { GeoJSON, Feature } from 'geojson';
import type { SegmentFeatureProps } from '../../api/geojson';
import { useSegmentsGeoJSON } from '../../hooks/useSegmentMap';
import { useMapData } from '../../hooks/useMapData';
import Spinner from './Spinner';

const MAP_STYLE = 'https://basemaps.cartocdn.com/gl/dark-matter-gl-style/style.json';

const RISK_COLORS: Record<string, string> = {
  critical: '#E85D5D',
  high:     '#E8A44C',
  medium:   '#D4C24E',
  low:      '#4EA86A',
};

// Colour ramp for density 0→100
const DENSITY_COLOR_EXPR = [
  'interpolate', ['linear'], ['get', 'density_score'],
  0,   '#4EA86A',
  40,  '#D4C24E',
  70,  '#E8A44C',
  100, '#E85D5D',
] as unknown as string;

// Colour for incident severity 1–5
const INCIDENT_COLOR_EXPR = [
  'interpolate', ['linear'], ['get', 'severity'],
  1, '#D4C24E',
  3, '#E8A44C',
  5, '#E85D5D',
] as unknown as string;

interface PopupInfo {
  longitude: number;
  latitude: number;
  layer: 'segment' | 'flow' | 'incident';
  properties: Record<string, unknown>;
}

export interface LayerVisibility {
  segments: boolean;
  flow: boolean;
  incidents: boolean;
}

export default function SegmentMap({
  pilot,
  className = '',
  layers = { segments: true, flow: true, incidents: true },
}: {
  pilot?: string;
  className?: string;
  layers?: LayerVisibility;
}) {
  const { data: geojson, isLoading } = useSegmentsGeoJSON(pilot);
  const { data: mapData } = useMapData();
  const [popup, setPopup] = useState<PopupInfo | null>(null);

  const onClick = useCallback((e: MapLayerMouseEvent) => {
    const feature = e.features?.[0] as Feature | undefined;
    if (!feature) return;

    const layerId = feature.layer?.id ?? '';

    if (layerId === 'segments-line' && feature.geometry?.type === 'LineString') {
      const coords = (feature.geometry as GeoJSON.LineString).coordinates;
      const mid = coords[Math.floor(coords.length / 2)];
      setPopup({ longitude: mid[0], latitude: mid[1], layer: 'segment', properties: feature.properties as Record<string, unknown> });
      return;
    }

    if ((layerId === 'flow-circles' || layerId === 'flow-halos') && feature.geometry?.type === 'Point') {
      const [lon, lat] = (feature.geometry as GeoJSON.Point).coordinates;
      setPopup({ longitude: lon, latitude: lat, layer: 'flow', properties: feature.properties as Record<string, unknown> });
      return;
    }

    if ((layerId === 'incident-circles' || layerId === 'incident-halos') && feature.geometry?.type === 'Point') {
      const [lon, lat] = (feature.geometry as GeoJSON.Point).coordinates;
      setPopup({ longitude: lon, latitude: lat, layer: 'incident', properties: feature.properties as Record<string, unknown> });
      return;
    }
  }, []);

  if (isLoading) {
    return (
      <div className={`flex items-center justify-center bg-[#111820] rounded-xl ${className}`}>
        <Spinner />
      </div>
    );
  }

  const lineColor = [
    'match', ['get', 'level'],
    'critical', RISK_COLORS.critical,
    'high',     RISK_COLORS.high,
    'medium',   RISK_COLORS.medium,
    RISK_COLORS.low,
  ] as unknown as string;

  const interactiveIds = [
    ...(layers.segments ? ['segments-line'] : []),
    ...(layers.flow ? ['flow-circles', 'flow-halos'] : []),
    ...(layers.incidents ? ['incident-circles', 'incident-halos'] : []),
  ];

  return (
    <div className={`rounded-xl overflow-hidden ${className}`}>
      <Map
        initialViewState={{ longitude: -3.7038, latitude: 40.4168, zoom: 11 }}
        style={{ width: '100%', height: '100%' }}
        mapStyle={MAP_STYLE}
        interactiveLayerIds={interactiveIds}
        onClick={onClick}
        onMouseLeave={() => setPopup(null)}
      >
        <NavigationControl position="top-right" />

        {/* ── Road segments ──────────────────────────────────────────────── */}
        {layers.segments && geojson && geojson.features.length > 0 && (
          <Source id="segments" type="geojson" data={geojson as unknown as GeoJSON}>
            <Layer id="segments-halo" type="line"
              paint={{ 'line-color': lineColor, 'line-width': 8, 'line-opacity': 0.15 }} />
            <Layer id="segments-line" type="line"
              paint={{ 'line-color': lineColor, 'line-width': 3, 'line-opacity': 0.9 }} />
          </Source>
        )}

        {layers.segments && geojson && geojson.features.length === 0 && (
          <div className="absolute inset-0 flex items-center justify-center pointer-events-none">
            <span className="text-[13px] text-[#5E6A7A] bg-[#111820]/80 px-4 py-2 rounded-lg">
              No segments yet. Add road segments to see them on the map.
            </span>
          </div>
        )}

        {/* ── TomTom flow points ─────────────────────────────────────────── */}
        {layers.flow && mapData?.flow && (
          <Source id="flow" type="geojson" data={mapData.flow as unknown as GeoJSON}>
            {/* Glow */}
            <Layer id="flow-halos" type="circle"
              paint={{
                'circle-radius': 28,
                'circle-color': DENSITY_COLOR_EXPR,
                'circle-opacity': 0.18,
                'circle-blur': 1,
              }}
            />
            {/* Main circle — grey when no data yet */}
            <Layer id="flow-circles" type="circle"
              paint={{
                'circle-radius': 12,
                'circle-color': [
                  'case',
                  ['==', ['get', 'has_data'], true],
                  DENSITY_COLOR_EXPR,
                  '#3A4455',
                ] as unknown as string,
                'circle-opacity': 0.9,
                'circle-stroke-color': '#1A2230',
                'circle-stroke-width': 1.5,
              }}
            />
          </Source>
        )}

        {/* ── Incidents ──────────────────────────────────────────────────── */}
        {layers.incidents && mapData?.incidents && (
          <Source id="incidents" type="geojson" data={mapData.incidents as unknown as GeoJSON}>
            <Layer id="incident-halos" type="circle"
              paint={{
                'circle-radius': 22,
                'circle-color': INCIDENT_COLOR_EXPR,
                'circle-opacity': 0.2,
                'circle-blur': 0.8,
              }}
            />
            <Layer id="incident-circles" type="circle"
              paint={{
                'circle-radius': 8,
                'circle-color': INCIDENT_COLOR_EXPR,
                'circle-opacity': 0.85,
                'circle-stroke-color': '#1A2230',
                'circle-stroke-width': 1.5,
              }}
            />
          </Source>
        )}

        {/* ── Popup ──────────────────────────────────────────────────────── */}
        {popup && (
          <Popup
            longitude={popup.longitude}
            latitude={popup.latitude}
            closeButton={false}
            anchor="bottom"
            offset={14}
          >
            <div className="bg-[#1A2230] border border-[#1E2A3A] rounded-lg p-3 min-w-[190px]">
              {popup.layer === 'segment' && <SegmentPopup p={popup.properties} />}
              {popup.layer === 'flow'    && <FlowPopup    p={popup.properties} />}
              {popup.layer === 'incident' && <IncidentPopup p={popup.properties} />}
            </div>
          </Popup>
        )}
      </Map>
    </div>
  );
}

// ── Popup sub-components ──────────────────────────────────────────────────────

function SegmentPopup({ p }: { p: Record<string, unknown> }) {
  const props = p as SegmentFeatureProps;
  return (
    <>
      <p className="text-[13px] font-semibold text-white mb-1">{props.name}</p>
      <div className="flex items-center gap-2 mb-2">
        <span className="text-[11px] font-medium px-2 py-0.5 rounded capitalize"
          style={{ backgroundColor: RISK_COLORS[props.level] + '25', color: RISK_COLORS[props.level] }}>
          {props.level}
        </span>
        <span className="text-[13px] font-bold" style={{ color: RISK_COLORS[props.level] }}>
          {props.score}
        </span>
      </div>
      <div className="text-[11px] text-[#9BA3B0] space-y-0.5">
        {props.speed_limit_kmh && <p>Limit: {props.speed_limit_kmh} km/h</p>}
        {props.lanes && <p>Lanes: {props.lanes}</p>}
        {props.length_m && <p>Length: {((props.length_m as number) / 1000).toFixed(1)} km</p>}
      </div>
    </>
  );
}

function FlowPopup({ p }: { p: Record<string, unknown> }) {
  const hasData = p.has_data as boolean;
  const density = p.density_score as number;
  const color = density < 0 ? '#9BA3B0'
    : density < 40 ? '#4EA86A'
    : density < 70 ? '#D4C24E'
    : '#E85D5D';

  return (
    <>
      <p className="text-[13px] font-semibold text-white mb-1">{p.label as string}</p>
      {hasData ? (
        <div className="text-[11px] text-[#9BA3B0] space-y-0.5">
          <p>Speed: <span className="text-white font-medium">{(p.current_speed as number).toFixed(0)} km/h</span>
            <span className="ml-1 text-[#5E6A7A]">/ {(p.free_flow_speed as number).toFixed(0)} free-flow</span>
          </p>
          <p>Congestion: <span style={{ color }} className="font-medium">{density.toFixed(0)}%</span></p>
          {(p.road_closure as boolean) && <p className="text-[#E85D5D] font-medium">Road closed</p>}
        </div>
      ) : (
        <p className="text-[11px] text-[#5E6A7A]">Waiting for first TomTom poll…</p>
      )}
      <p className="text-[10px] text-[#3A4455] mt-1.5">Source: TomTom Flow</p>
    </>
  );
}

function IncidentPopup({ p }: { p: Record<string, unknown> }) {
  const sev = p.severity as number;
  const color = sev >= 4 ? '#E85D5D' : sev >= 3 ? '#E8A44C' : '#D4C24E';
  return (
    <>
      <p className="text-[13px] font-semibold text-white mb-1 capitalize">
        {(p.incident_type as string).replace(/_/g, ' ')}
      </p>
      <div className="flex items-center gap-2 mb-1.5">
        <span className="text-[11px] font-medium px-2 py-0.5 rounded"
          style={{ backgroundColor: color + '25', color }}>
          Severity {sev}
        </span>
        {p.source && <span className="text-[10px] text-[#5E6A7A] capitalize">{p.source as string}</span>}
      </div>
      {p.description && <p className="text-[11px] text-[#9BA3B0]">{p.description as string}</p>}
    </>
  );
}
