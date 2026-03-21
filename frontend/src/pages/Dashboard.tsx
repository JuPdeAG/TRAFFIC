import { Route as RouteIcon, ShieldAlert, Bell, Camera } from 'lucide-react';
import { AreaChart, Area, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer } from 'recharts';
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
import { useTrafficFlow } from '../hooks/useMetrics';
import { sparklineData } from '../data/mock';
import { chartColors } from '../design/tokens';
import type { RiskSummaryItem } from '../api/risk';
import type { Incident } from '../api/alerts';

const riskLevelColor: Record<string, string> = {
  critical: '#E85D5D', high: '#E8A44C', medium: '#D4C24E', low: '#4EA86A',
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

  const isLoading = segLoading || riskLoading || incLoading;

  // Derive stats
  const activeSegments = segments?.length ?? 0;
  const avgRisk = riskSummary?.length
    ? Math.round(riskSummary.reduce((s, r) => s + r.score, 0) / riskSummary.length)
    : 0;
  const openAlerts = incidents?.length ?? 0;
  const systemRisk = avgRisk;

  // Top 5 segments by risk score, enriched with name
  const segmentNameMap = Object.fromEntries((segments ?? []).map((s) => [s.id, s.name ?? s.id]));
  const topRisk = (riskSummary ?? [])
    .slice()
    .sort((a, b) => b.score - a.score)
    .slice(0, 5)
    .map((r) => ({ ...r, name: segmentNameMap[r.segment_id] ?? r.segment_id }));

  const recentAlerts = (incidents ?? []).slice(0, 5);

  if (isLoading) return <PageContainer><Spinner className="h-64" /></PageContainer>;

  return (
    <PageContainer className="flex flex-col gap-6">
      <div className="grid grid-cols-4 gap-4">
        <StatCard icon={RouteIcon} label="Active Segments" value={activeSegments} trend={8} trendDirection="up" sparkline={sparklineData(activeSegments)} />
        <StatCard icon={ShieldAlert} label="Average Risk Score" value={avgRisk} trend={3} trendDirection="down" sparkline={sparklineData(avgRisk)} />
        <StatCard icon={Bell} label="Open Alerts" value={openAlerts} trend={12} trendDirection="up" sparkline={sparklineData(openAlerts)} />
        <StatCard icon={Camera} label="Cameras Online" value="—" trend={0} trendDirection="up" sparkline={sparklineData(0)} />
      </div>

      <div className="grid grid-cols-3 gap-4">
        <Card className="col-span-2">
          <h2 className="text-[15px] font-semibold tracking-[-0.02em] text-[#F4F5F7] mb-4">Traffic Flow — Last 24h</h2>
          <ResponsiveContainer width="100%" height={280}>
            <AreaChart data={flowData ?? []}>
              <defs>
                <linearGradient id="flowGrad" x1="0" y1="0" x2="0" y2="1">
                  <stop offset="0%" stopColor={chartColors.primary} stopOpacity={0.3} />
                  <stop offset="100%" stopColor={chartColors.primary} stopOpacity={0} />
                </linearGradient>
                <linearGradient id="predGrad" x1="0" y1="0" x2="0" y2="1">
                  <stop offset="0%" stopColor={chartColors.secondary} stopOpacity={0.15} />
                  <stop offset="100%" stopColor={chartColors.secondary} stopOpacity={0} />
                </linearGradient>
              </defs>
              <CartesianGrid strokeDasharray="3 3" stroke={chartColors.grid} vertical={false} />
              <XAxis dataKey="time" tick={{ fill: chartColors.text, fontSize: 11 }} axisLine={false} tickLine={false} />
              <YAxis tick={{ fill: chartColors.text, fontSize: 11 }} axisLine={false} tickLine={false} />
              <Tooltip contentStyle={{ backgroundColor: '#1A2230', border: '1px solid #1E2A3A', borderRadius: '8px', fontSize: '13px' }} labelStyle={{ color: '#9BA3B0' }} />
              <Area type="monotone" dataKey="predicted" stroke={chartColors.secondary} fill="url(#predGrad)" strokeWidth={1.5} dot={false} name="Predicted" />
              <Area type="monotone" dataKey="flow" stroke={chartColors.primary} fill="url(#flowGrad)" strokeWidth={2} dot={false} name="Actual" />
            </AreaChart>
          </ResponsiveContainer>
        </Card>
        <Card className="flex flex-col items-center justify-center">
          <h2 className="text-[15px] font-semibold tracking-[-0.02em] text-[#F4F5F7] mb-4">System Risk Score</h2>
          <RiskGauge score={systemRisk} size={220} />
        </Card>
      </div>

      <div className="grid grid-cols-2 gap-4">
        <Card>
          <h2 className="text-[15px] font-semibold tracking-[-0.02em] text-[#F4F5F7] mb-4">Top Risk Segments</h2>
          {topRisk.length === 0
            ? <p className="text-[13px] text-[#5E6A7A] text-center py-8">No segments yet. Add road segments to get started.</p>
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

function severityLevel(severity: number | null): 'critical' | 'high' | 'medium' | 'low' {
  if (severity === null) return 'medium';
  if (severity >= 5) return 'critical';
  if (severity >= 4) return 'high';
  if (severity >= 3) return 'medium';
  return 'low';
}
