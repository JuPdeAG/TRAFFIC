import { useState, useEffect } from 'react';
import { Shield, Key, Users, Server, RefreshCw } from 'lucide-react';
import clsx from 'clsx';
import PageContainer from '../components/ui/PageContainer';
import Card from '../components/ui/Card';
import Button from '../components/ui/Button';
import api from '../api/client';

interface InputFieldProps { label: string; value: string; type?: string; disabled?: boolean; }

function InputField({ label, value, type = 'text', disabled = false }: InputFieldProps) {
  return (
    <div className="flex flex-col gap-1.5">
      <label className="text-[11px] font-medium text-[#5E6A7A] tracking-[0.01em] uppercase">{label}</label>
      <input type={type} defaultValue={value} disabled={disabled}
        className={clsx('bg-[#111820] border border-[#1E2A3A] rounded-lg px-3 py-2 text-[13px] text-[#F4F5F7] outline-none transition-all duration-150 ease-in-out',
          disabled ? 'opacity-50 cursor-not-allowed' : 'focus:border-[#D4915E]')} />
    </div>
  );
}

type HealthStatus = 'healthy' | 'degraded' | 'down';

interface HealthItemProps { label: string; status: HealthStatus; detail: string; }

function HealthItem({ label, status, detail }: HealthItemProps) {
  const statusColors = { healthy: 'text-[#4EA86A]', degraded: 'text-[#D4915E]', down: 'text-[#E85D5D]' };
  const dotColors = { healthy: 'bg-[#4EA86A]', degraded: 'bg-[#D4915E]', down: 'bg-[#E85D5D]' };
  return (
    <div className="flex items-center justify-between py-3 border-b border-[#1E2A3A]/50 last:border-0">
      <div className="flex items-center gap-2">
        <span className={clsx('w-2 h-2 rounded-full', dotColors[status])} />
        <span className="text-[13px] text-[#F4F5F7]">{label}</span>
      </div>
      <div className="flex items-center gap-3">
        <span className="text-[11px] text-[#5E6A7A]">{detail}</span>
        <span className={clsx('text-[11px] font-medium capitalize', statusColors[status])}>{status}</span>
      </div>
    </div>
  );
}

interface ReadinessResponse {
  status: string;
  checks: Record<string, string>;
}

function checkToStatus(val: string): HealthStatus {
  if (val === 'ok') return 'healthy';
  if (val === 'not initialised' || val === 'not ready') return 'degraded';
  return 'down';
}

const deploymentTiers = ['Starter', 'Professional', 'Enterprise'];

export default function Settings() {
  const [health, setHealth] = useState<ReadinessResponse | null>(null);
  const [healthLoading, setHealthLoading] = useState(false);
  const [lastChecked, setLastChecked] = useState<Date | null>(null);

  async function loadHealth() {
    setHealthLoading(true);
    try {
      const { data } = await api.get<ReadinessResponse>('/ready');
      setHealth(data);
      setLastChecked(new Date());
    } catch {
      setHealth({ status: 'down', checks: { api: 'unreachable' } });
    } finally {
      setHealthLoading(false);
    }
  }

  useEffect(() => { loadHealth(); }, []);

  const checks = health?.checks ?? {};

  // Map infrastructure checks to display labels
  const healthItems: { label: string; key: string }[] = [
    { label: 'API Gateway', key: 'api' },
    { label: 'PostgreSQL Database', key: 'postgres' },
    { label: 'Redis Cache', key: 'redis' },
    { label: 'InfluxDB Time-Series', key: 'influxdb' },
  ];

  return (
    <PageContainer className="flex flex-col gap-6 max-w-4xl">
      <Card>
        <div className="flex items-center gap-3 mb-5">
          <div className="w-9 h-9 rounded-lg bg-[#D4915E]/10 flex items-center justify-center">
            <Shield size={18} className="text-[#D4915E]" />
          </div>
          <h2 className="text-[18px] font-semibold tracking-[-0.02em] text-[#F4F5F7]">Profile Configuration</h2>
        </div>
        <div className="grid grid-cols-2 gap-4 mb-5">
          <InputField label="Organization Name" value="Traffic AI Platform" />
          <InputField label="Deployment Region" value="Madrid, Spain" />
          <InputField label="Admin Email" value="admin@traffic-ai.local" type="email" />
          <InputField label="Notification Webhook" value="" />
        </div>
        <div className="mb-5">
          <label className="text-[11px] font-medium text-[#5E6A7A] tracking-[0.01em] uppercase mb-2 block">Deployment Tier</label>
          <div className="flex items-center gap-3">
            {deploymentTiers.map((tier) => {
              const isActive = tier === 'Starter';
              return (
                <button key={tier} className={clsx(
                  'px-4 py-2.5 rounded-lg text-[13px] font-medium border transition-all duration-150 ease-in-out',
                  isActive
                    ? 'border-[#D4915E] bg-[#D4915E]/10 text-[#D4915E]'
                    : 'border-[#1E2A3A] text-[#5E6A7A] hover:border-[#2A3A4E] hover:text-[#9BA3B0]',
                )}>
                  {tier}
                </button>
              );
            })}
          </div>
        </div>
        <Button>Save Changes</Button>
      </Card>

      <Card>
        <div className="flex items-center gap-3 mb-5">
          <div className="w-9 h-9 rounded-lg bg-[#D4915E]/10 flex items-center justify-center">
            <Key size={18} className="text-[#D4915E]" />
          </div>
          <h2 className="text-[18px] font-semibold tracking-[-0.02em] text-[#F4F5F7]">API Keys</h2>
        </div>
        <div className="grid grid-cols-2 gap-4 mb-5">
          <InputField label="AEMET Spain API Key" value="" type="password" />
          <InputField label="NOAA Weather Station IDs" value="" />
          <InputField label="S3 / Cloudflare R2 Bucket" value="" />
          <InputField label="Analytics Endpoint" value="http://localhost:8000/api/v1" disabled />
        </div>
        <p className="text-[11px] text-[#5E6A7A] mt-1">
          Configure these values in the <code className="text-[#9BA3B0]">.env</code> file and restart the server.
        </p>
      </Card>

      <Card>
        <div className="flex items-center gap-3 mb-5">
          <div className="w-9 h-9 rounded-lg bg-[#D4915E]/10 flex items-center justify-center">
            <Users size={18} className="text-[#D4915E]" />
          </div>
          <h2 className="text-[18px] font-semibold tracking-[-0.02em] text-[#F4F5F7]">User Management</h2>
        </div>
        <div className="flex flex-col gap-3">
          <div className="p-3 rounded-lg bg-[#111820] border border-[#1E2A3A]">
            <p className="text-[12px] text-[#5E6A7A]">
              To create users, run the seed script or use the registration endpoint:
            </p>
            <code className="text-[11px] text-[#9BA3B0] block mt-1">
              POST /api/v1/auth/register · python scripts/seed_demo_data.py
            </code>
            <p className="text-[12px] text-[#5E6A7A] mt-2">
              Demo admin: <span className="text-[#9BA3B0]">admin@traffic-ai.local</span> / <span className="text-[#9BA3B0]">Traffic2024!</span>
            </p>
          </div>
        </div>
      </Card>

      <Card>
        <div className="flex items-center justify-between mb-5">
          <div className="flex items-center gap-3">
            <div className="w-9 h-9 rounded-lg bg-[#D4915E]/10 flex items-center justify-center">
              <Server size={18} className="text-[#D4915E]" />
            </div>
            <div>
              <h2 className="text-[18px] font-semibold tracking-[-0.02em] text-[#F4F5F7]">System Health</h2>
              {lastChecked && (
                <p className="text-[11px] text-[#5E6A7A] mt-0.5">
                  Last checked {lastChecked.toLocaleTimeString()}
                </p>
              )}
            </div>
          </div>
          <button
            onClick={loadHealth}
            disabled={healthLoading}
            className="p-2 rounded-lg text-[#5E6A7A] hover:text-[#9BA3B0] hover:bg-[#1A2230] transition-all duration-150 disabled:opacity-50"
          >
            <RefreshCw size={15} className={healthLoading ? 'animate-spin' : ''} />
          </button>
        </div>

        <div className="flex flex-col">
          {/* API gateway status — derive from whether we got a response */}
          <HealthItem
            label="API Gateway"
            status={health ? 'healthy' : 'down'}
            detail={health ? `Status: ${health.status}` : 'Unreachable'}
          />
          {healthItems.slice(1).map(({ label, key }) => {
            const val = checks[key] ?? 'unknown';
            const status = checkToStatus(val);
            const detail = val === 'ok' ? 'Connected' : val;
            return <HealthItem key={key} label={label} status={status} detail={detail} />;
          })}
          <HealthItem
            label="Celery Workers"
            status="degraded"
            detail="Run: celery -A traffic_ai.celery_app worker"
          />
          <HealthItem
            label="ML Models"
            status="degraded"
            detail="Run: python scripts/train_congestion_model.py"
          />
        </div>
      </Card>
    </PageContainer>
  );
}
