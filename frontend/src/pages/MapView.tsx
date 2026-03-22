import { useState } from 'react';
import PageContainer from '../components/ui/PageContainer';
import SegmentMap from '../components/ui/SegmentMap';
import type { LayerVisibility } from '../components/ui/SegmentMap';
import { useRiskSummary } from '../hooks/useSegments';
import { useMapData } from '../hooks/useMapData';

const RISK_COLORS = { critical: '#E85D5D', high: '#E8A44C', medium: '#D4C24E', low: '#4EA86A' };

const LAYER_LABELS: Record<keyof LayerVisibility, string> = {
  segments: 'Segments',
  flow:     'TomTom Flow',
  incidents: 'Incidents',
};

export default function MapView() {
  const { data: riskSummary } = useRiskSummary();
  const { data: mapData } = useMapData();

  const [layers, setLayers] = useState<LayerVisibility>({
    segments: true,
    flow: true,
    incidents: true,
  });

  const toggle = (key: keyof LayerVisibility) =>
    setLayers(prev => ({ ...prev, [key]: !prev[key] }));

  const counts = { critical: 0, high: 0, medium: 0, low: 0 };
  (riskSummary ?? []).forEach((r) => {
    const l = r.level as keyof typeof counts;
    if (l in counts) counts[l]++;
  });

  const flowCount = mapData?.flow?.features?.filter(f => f.properties?.has_data).length ?? 0;
  const incidentCount = mapData?.incidents?.features?.length ?? 0;

  return (
    <PageContainer className="flex flex-col gap-4 h-full">
      {/* Header */}
      <div className="flex items-center justify-between flex-wrap gap-3">
        <div>
          <h2 className="text-[22px] font-semibold tracking-[-0.02em] text-[#F4F5F7]">Network Map</h2>
          <p className="text-[13px] text-[#5E6A7A] mt-0.5">Live traffic overlay — segments, flow & incidents</p>
        </div>

        {/* Risk legend */}
        <div className="flex items-center gap-4">
          {Object.entries(RISK_COLORS).map(([level, color]) => (
            <div key={level} className="flex items-center gap-1.5">
              <span className="w-3 h-1.5 rounded-full" style={{ backgroundColor: color }} />
              <span className="text-[11px] text-[#9BA3B0] capitalize">
                {level} ({counts[level as keyof typeof counts]})
              </span>
            </div>
          ))}
        </div>
      </div>

      {/* Layer toggles + stats */}
      <div className="flex items-center gap-3 flex-wrap">
        {(Object.keys(layers) as (keyof LayerVisibility)[]).map(key => (
          <button
            key={key}
            onClick={() => toggle(key)}
            className={`flex items-center gap-2 px-3 py-1.5 rounded-lg text-[12px] font-medium border transition-colors ${
              layers[key]
                ? 'bg-[#1E2A3A] border-[#2A3A4A] text-[#F4F5F7]'
                : 'bg-transparent border-[#1E2A3A] text-[#5E6A7A]'
            }`}
          >
            <span className={`w-2 h-2 rounded-full ${layers[key] ? 'opacity-100' : 'opacity-30'}`}
              style={{ backgroundColor:
                key === 'flow' ? '#4EA86A' :
                key === 'incidents' ? '#E85D5D' : '#D4C24E'
              }} />
            {LAYER_LABELS[key]}
            {key === 'flow' && flowCount > 0 && (
              <span className="text-[10px] text-[#5E6A7A]">({flowCount})</span>
            )}
            {key === 'incidents' && incidentCount > 0 && (
              <span className="text-[10px] text-[#5E6A7A]">({incidentCount})</span>
            )}
          </button>
        ))}

        <span className="text-[11px] text-[#3A4455] ml-auto">
          Click any element for details
        </span>
      </div>

      {/* Map */}
      <SegmentMap className="flex-1 min-h-[500px]" layers={layers} />
    </PageContainer>
  );
}
