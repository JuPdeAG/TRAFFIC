import { Route as RouteIcon, ShieldAlert, Bell, Camera, TrendingUp, TrendingDown, Minus } from 'lucide-react';
import {
  AreaChart, Area, LineChart, Line,
  XAxis, YAxis, CartesianGrid, Tooltip, Legend,
  ResponsiveContainer,
} from 'recharts';
import { formatDistanceToNow } from 'date-fns';
import PageContainer from '../components/ui/PageContainer';
import StatCard from '../components/ui/StatCard';
import Card from '../components/ui/Card';
import Badge from '../components/ui/Badge';
import RiskGauge from '../components/ui/RiskGauge';
import Table from '../components/ui/Table';
import Spinner from '../components/ui/Spinner';
import { useSegments, useRiskSummary } from '../hooks/useSegments';
import { useIncidents } from '../hooks/useIncidents';
import { useTrafficFlow, useTrafficState, useCongestionTrend } from '../hooks/useMetrics';
import { useCameraStats } from '../hooks/useCameras';
import { sparklineData } from '../data/mock';
import { chartColors } from '../design/tokens';
import type { RiskSummaryItem } from '../api/risk';
import type { Incident } from '../api/alerts';
import type { CityState } from '../api/metrics';

const riskLevelColor: Record<string, string> = {
  critical: '#E85D5D', high: '#E8A44C', medium: '#D4C24E', low: '#4EA86A',
};

// Per-city chart colours
const CITY_COLORS: Record<string, string> = {
  madrid:    '#D4915E',
  valencia:  '#4EA8A6',
  barcelona: '#D4C24E',
  tomtom:    '#9BA3B0',
};

const CITY_LABELS: Record<string, string> = {
  madrid: 'Madrid', valencia: 'Valencia', barcelona: 'Barcelona', tomtom: 'National',
};

const segmentColumns = [
  { key: 'name', header: 'Segment', render: (r: RiskSummaryItem & { name: string }) => <span className="text-[#F4F5F7] font-medium">{r.name}</span> },
  { key: 'level', header: 'Risk', render: (r: RiskSummaryItem) => <Badge level={r.level as 'critical' | 'high' | 'medium' | 'low'} /> },
  { key: 'score', header: 'Score', render: (r: RiskSummaryItem) => <span className="font-semibold" style={{ color: riskLevelColor[r.level] }}>{r.score}</span> },
];

export default function Dashboard() {
  const { data: segments, isLoading: segLoading } = useSegments();
  const { data: riskSummary, isLoading: riskLoading } = useRiskSummary();
  const { data: incidents, isLoading: incLoading } = useIncidents('active');
  const { data: flowData } = useTrafficFlow(24);
  const { data: cameraStats } = useCameraStats();
  const { data: trafficState } = useTrafficState();
  const { data: congestionTrend } = useCongestionTrend(24);

  const isLoading = segLoading || riskLoading || incLoading;

  const activeSegments = segments?.length ?? 0;
  const avgRisk = riskSummary?.length
    ? Math.round(riskSummary.reduce((s, r) => s + r.score, 0) / riskSummary.length)
    : 0;
  const openAlerts = incidents?.length ?? 0;
  const camerasOnline = cameraStats?.online ?? 0;

  const segmentNameMap = Object.fromEntries((segments ?? []).map((s) => [s.id, s.name ?? s.id]));
  const topRisk = (riskSummary ?? [])
    .slice().sort((a, b) => b.score - a.score).slice(0, 5)
    .map((r) => ({ ...r, name: segmentNameMap[r.segment_id] ?? r.segment_id }));

  const recentAlerts = (incidents ?? []).slice(0, 5);

  if (isLoading) return <PageContainer><Spinner className="h-64" /></PageContainer>;

  return (
    <PageContainer className="flex flex-col gap-6">

      {/* ── Row 1: stat cards ─────────────────────────────────────────── */}
      <div className="grid grid-cols-4 gap-4">
        <StatCard icon={RouteIcon} label="Active Segments"   value={activeSegments} trend={8}  trendDirection="up"   sparkline={sparklineData(activeSegments)} />
        <StatCard icon={ShieldAlert} label="Avg Risk Score"  value={avgRisk}         trend={3}  trendDirection="down" sparkline={sparklineData(avgRisk)} />
        <StatCard icon={Bell}        label="Open Alerts"     value={openAlerts}       trend={12} trendDirection="up"   sparkline={sparklineData(openAlerts)} />
        <StatCard icon={Camera}      label="Cameras Online"  value={cameraStats ? camerasOnline : '—'} trend={0} trendDirection="up" sparkline={sparklineData(camerasOnline)} />
      </div>

      {/* ── Row 2: congestion trend + risk gauge ──────────────────────── */}
      <div className="grid grid-cols-3 gap-4">
        <Card className="col-span-2">
          <div className="flex items-center justify-between mb-4">
            <h2 className="text-[15px] font-semibold tracking-[-0.02em] text-[#F4F5F7]">
              City Congestion — Last 24h
            </h2>
            <div className="flex items-center gap-3">
              {Object.entries(CITY_COLORS).map(([key, color]) => (
                <div key={key} className="flex items-center gap-1.5">
                  <span className="w-3 h-0.5 rounded-full inline-block" style={{ backgroundColor: color }} />
                  <span className="text-[11px] text-[#9BA3B0]">{CITY_LABELS[key]}</span>
                </div>
              ))}
            </div>
          </div>
          {congestionTrend && congestionTrend.length > 0 ? (
            <ResponsiveContainer width="100%" height={240}>
              <LineChart data={congestionTrend}>
                <CartesianGrid strokeDasharray="3 3" stroke={chartColors.grid} vertical={false} />
                <XAxis dataKey="time" tick={{ fill: chartColors.text, fontSize: 11 }} axisLine={false} tickLine={false} interval="preserveStartEnd" />
                <YAxis tick={{ fill: chartColors.text, fontSize: 11 }} axisLine={false} tickLine={false} domain={[0, 100]} unit="%" />
                <Tooltip
                  contentStyle={{ backgroundColor: '#1A2230', border: '1px solid #1E2A3A', borderRadius: '8px', fontSize: '13px' }}
                  labelStyle={{ color: '#9BA3B0' }}
                  formatter={(v: unknown) => v !== null ? [`${(v as number).toFixed(1)}%`] : ['—']}
                />
                {Object.entries(CITY_COLORS).map(([key, color]) => (
                  <Line key={key} type="monotone" dataKey={key} stroke={color} strokeWidth={2}
                    dot={false} name={CITY_LABELS[key]} connectNulls />
                ))}
              </LineChart>
            </ResponsiveContainer>
          ) : (
            /* Fall back to speed area chart while congestion data accumulates */
            <ResponsiveContainer width="100%" height={240}>
              <AreaChart data={flowData ?? []}>
                <defs>
                  <linearGradient id="flowGrad" x1="0" y1="0" x2="0" y2="1">
                    <stop offset="0%" stopColor={chartColors.primary} stopOpacity={0.3} />
                    <stop offset="100%" stopColor={chartColors.primary} stopOpacity={0} />
                  </linearGradient>
                </defs>
                <CartesianGrid strokeDasharray="3 3" stroke={chartColors.grid} vertical={false} />
                <XAxis dataKey="time" tick={{ fill: chartColors.text, fontSize: 11 }} axisLine={false} tickLine={false} />
                <YAxis tick={{ fill: chartColors.text, fontSize: 11 }} axisLine={false} tickLine={false} />
                <Tooltip contentStyle={{ backgroundColor: '#1A2230', border: '1px solid #1E2A3A', borderRadius: '8px', fontSize: '13px' }} labelStyle={{ color: '#9BA3B0' }} />
                <Area type="monotone" dataKey="flow" stroke={chartColors.primary} fill="url(#flowGrad)" strokeWidth={2} dot={false} name="Speed (km/h)" />
              </AreaChart>
            </ResponsiveContainer>
          )}
          {(!congestionTrend || congestionTrend.length === 0) && (
            <p className="text-[11px] text-[#3A4455] mt-2 text-center">
              Showing speed data — congestion trend builds after ~1h of sensor polling
            </p>
          )}
        </Card>

        <Card className="flex flex-col items-center justify-center">
          <h2 className="text-[15px] font-semibold tracking-[-0.02em] text-[#F4F5F7] mb-4">System Risk Score</h2>
          <RiskGauge score={avgRisk} size={220} />
        </Card>
      </div>

      {/* ── Row 3: city status cards ──────────────────────────────────── */}
      {trafficState && trafficState.cities.length > 0 && (
        <div className="grid grid-cols-4 gap-4">
          {trafficState.cities.map((city) => (
            <CityStatusCard key={city.city} city={city} />
          ))}
        </div>
      )}
      {(!trafficState || trafficState.cities.length === 0) && (
        <div className="grid grid-cols-4 gap-4">
          {['madrid', 'valencia', 'barcelona', 'tomtom'].map((city) => (
            <CityStatusCard key={city} city={{ city, label: CITY_LABELS[city], avg_density: null, avg_speed_kmh: null, reading_count: 0, last_updated: null }} />
          ))}
        </div>
      )}

      {/* ── Row 4: tables ─────────────────────────────────────────────── */}
      <div className="grid grid-cols-2 gap-4">
        <Card>
          <h2 className="text-[15px] font-semibold tracking-[-0.02em] text-[#F4F5F7] mb-4">Top Risk Segments</h2>
          {topRisk.length === 0
            ? <p className="text-[13px] text-[#5E6A7A] text-center py-8">No segments yet.</p>
            : <Table columns={segmentColumns} data={topRisk} keyExtractor={(r) => r.segment_id} />
          }
        </Card>
        <Card>
          <h2 className="text-[15px] font-semibold tracking-[-0.02em] text-[#F4F5F7] mb-4">Recent Alerts</h2>
          {recentAlerts.length === 0
            ? <p className="text-[13px] text-[#5E6A7A] text-center py-8">No active alerts.</p>
            : (
              <div className="flex flex-col gap-3">
                {recentAlerts.map((alert: Incident) => (
                  <div key={alert.id} className="flex items-start gap-3 p-3 rounded-lg bg-[#111820] border border-[#1E2A3A]">
                    <Badge level={severityLevel(alert.severity)} />
                    <div className="flex-1 min-w-0">
                      <p className="text-[13px] font-medium text-[#F4F5F7]">{alert.incident_type}</p>
                      <p className="text-[11px] text-[#9BA3B0] mt-0.5 truncate">{alert.description ?? alert.segment_id ?? '—'}</p>
                    </div>
                    <span className="text-[11px] text-[#5E6A7A] whitespace-nowrap">
                      {formatDistanceToNow(new Date(alert.started_at), { addSuffix: true })}
                    </span>
                  </div>
                ))}
              </div>
            )
          }
        </Card>
      </div>
    </PageContainer>
  );
}

// ── City status card ──────────────────────────────────────────────────────────

function CityStatusCard({ city }: { city: CityState }) {
  const density = city.avg_density;
  const color = density === null ? '#3A4455'
    : density < 35 ? '#4EA86A'
    : density < 60 ? '#D4C24E'
    : density < 80 ? '#E8A44C'
    : '#E85D5D';

  const cityColor = CITY_COLORS[city.city] ?? '#9BA3B0';
  const hasData = density !== null && city.reading_count > 0;

  return (
    <Card className="flex flex-col gap-3">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <span className="w-2 h-2 rounded-full flex-shrink-0" style={{ backgroundColor: cityColor }} />
          <span className="text-[13px] font-semibold text-[#F4F5F7]">{city.label}</span>
        </div>
        {hasData && (
          <span className="text-[10px] text-[#5E6A7A]">
            {city.reading_count} readings
          </span>
        )}
      </div>

      {hasData ? (
        <>
          {/* Congestion bar */}
          <div>
            <div className="flex items-center justify-between mb-1">
              <span className="text-[11px] text-[#9BA3B0]">Congestion</span>
              <span className="text-[13px] font-bold" style={{ color }}>{density!.toFixed(0)}%</span>
            </div>
            <div className="h-1.5 rounded-full bg-[#111820] overflow-hidden">
              <div className="h-full rounded-full transition-all duration-500"
                style={{ width: `${density!}%`, backgroundColor: color }} />
            </div>
          </div>

          {city.avg_speed_kmh !== null && (
            <div className="flex items-center justify-between">
              <span className="text-[11px] text-[#9BA3B0]">Avg speed</span>
              <span className="text-[13px] font-medium text-[#F4F5F7]">{city.avg_speed_kmh.toFixed(0)} km/h</span>
            </div>
          )}

          <DensityTrend density={density!} />
        </>
      ) : (
        <div className="flex flex-col items-center justify-center py-4 gap-1">
          <span className="text-[12px] text-[#3A4455]">Waiting for data</span>
          <span className="text-[10px] text-[#2A3445]">polls every 3–5 min</span>
        </div>
      )}
    </Card>
  );
}

function DensityTrend({ density }: { density: number }) {
  if (density < 35) return <div className="flex items-center gap-1 text-[11px] text-[#4EA86A]"><TrendingDown size={12} />Free flow</div>;
  if (density < 60) return <div className="flex items-center gap-1 text-[11px] text-[#D4C24E]"><Minus size={12} />Moderate</div>;
  if (density < 80) return <div className="flex items-center gap-1 text-[11px] text-[#E8A44C]"><TrendingUp size={12} />Heavy</div>;
  return <div className="flex items-center gap-1 text-[11px] text-[#E85D5D]"><TrendingUp size={12} />Congested</div>;
}

function severityLevel(severity: number | null): 'critical' | 'high' | 'medium' | 'low' {
  if (severity === null) return 'medium';
  if (severity >= 5) return 'critical';
  if (severity >= 4) return 'high';
  if (severity >= 3) return 'medium';
  return 'low';
}
