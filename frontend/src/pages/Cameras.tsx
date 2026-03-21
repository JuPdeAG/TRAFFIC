import { useState } from 'react';
import { Camera, Grid2x2, Grid3x3, LayoutGrid, RefreshCw } from 'lucide-react';
import clsx from 'clsx';
import { formatDistanceToNow } from 'date-fns';
import PageContainer from '../components/ui/PageContainer';
import Spinner from '../components/ui/Spinner';
import { useCameras } from '../hooks/useCameras';
import type { CameraMetric } from '../api/cameras';

type GridSize = '2x2' | '3x3' | '4x4';
type SourceFilter = 'all' | 'dgt' | 'madrid';

const gridClasses: Record<GridSize, string> = {
  '2x2': 'grid-cols-2',
  '3x3': 'grid-cols-3',
  '4x4': 'grid-cols-4',
};

const gridIcons: { size: GridSize; icon: typeof Grid2x2 }[] = [
  { size: '2x2', icon: Grid2x2 },
  { size: '3x3', icon: Grid3x3 },
  { size: '4x4', icon: LayoutGrid },
];

const densityColors: Record<string, string> = {
  free_flow: '#4EA86A',
  light: '#4EA8A6',
  moderate: '#D4C24E',
  heavy: '#E8A44C',
  gridlock: '#E85D5D',
  unknown: '#5E6A7A',
};

function cameraStatus(cam: CameraMetric): 'online' | 'offline' {
  if (!cam.camera_online) return 'offline';
  if (!cam.last_seen) return 'offline';
  const age = Date.now() - new Date(cam.last_seen).getTime();
  return age < 10 * 60_000 ? 'online' : 'offline';
}

function CameraCard({ cam }: { cam: CameraMetric }) {
  const status = cameraStatus(cam);
  const densityColor = densityColors[cam.density_level] ?? densityColors.unknown;
  const lastSeen = cam.last_seen
    ? formatDistanceToNow(new Date(cam.last_seen), { addSuffix: true })
    : 'No data';

  return (
    <div className="bg-[#1A2230] border border-[#1E2A3A] rounded-xl overflow-hidden transition-all duration-150 ease-in-out hover:border-[#2A3A4E]">
      {/* Camera feed placeholder */}
      <div className="aspect-video bg-[#111820] flex items-center justify-center relative">
        <Camera size={28} className="text-[#232E3F]" />

        {/* Status badge */}
        <div className="absolute top-2.5 left-2.5 flex items-center gap-1.5 bg-[rgba(17,24,32,0.8)] backdrop-blur-sm px-2 py-1 rounded-md">
          <span className={clsx(
            'w-1.5 h-1.5 rounded-full',
            status === 'online' ? 'bg-[#4EA8A6]' : 'bg-[#E85D5D]',
          )} />
          <span className="text-[10px] font-medium text-[#9BA3B0] capitalize">{status}</span>
        </div>

        {/* Density badge */}
        {cam.camera_online && (
          <div
            className="absolute top-2.5 right-2.5 px-2 py-1 rounded-md"
            style={{ backgroundColor: `${densityColor}20`, border: `1px solid ${densityColor}40` }}
          >
            <span className="text-[10px] font-medium" style={{ color: densityColor }}>
              {cam.density_level.replace('_', ' ')}
            </span>
          </div>
        )}

        {/* Vehicle count */}
        {cam.camera_online && cam.vehicle_count > 0 && (
          <div className="absolute bottom-2.5 right-2.5 bg-[rgba(17,24,32,0.8)] px-2 py-1 rounded-md">
            <span className="text-[11px] font-semibold text-[#F4F5F7]">{cam.vehicle_count}</span>
            <span className="text-[10px] text-[#5E6A7A] ml-1">vehicles</span>
          </div>
        )}
      </div>

      {/* Info */}
      <div className="p-3">
        <p className="text-[12px] font-medium text-[#F4F5F7] truncate">{cam.id}</p>
        <div className="flex items-center justify-between mt-1">
          <span className="text-[10px] text-[#5E6A7A] truncate">
            {cam.road || cam.source.toUpperCase()} · {lastSeen}
          </span>
          {cam.camera_online && (
            <span className="text-[10px] font-medium text-[#9BA3B0]">
              {cam.density_score.toFixed(0)}%
            </span>
          )}
        </div>
      </div>
    </div>
  );
}

export default function Cameras() {
  const [gridSize, setGridSize] = useState<GridSize>('3x3');
  const [sourceFilter, setSourceFilter] = useState<SourceFilter>('all');

  const { data: cameras, isLoading, refetch, isFetching } = useCameras(
    sourceFilter === 'all' ? undefined : sourceFilter,
  );

  const all = cameras ?? [];
  const online = all.filter((c) => cameraStatus(c) === 'online').length;
  const offline = all.length - online;

  return (
    <PageContainer className="flex flex-col gap-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-4 flex-wrap">
          <h2 className="text-[22px] font-semibold tracking-[-0.02em] text-[#F4F5F7]">
            {isLoading ? '—' : all.length} Cameras
          </h2>

          {/* Status counts */}
          <div className="flex items-center gap-3 text-[11px] font-medium">
            <span className="flex items-center gap-1.5">
              <span className="w-1.5 h-1.5 rounded-full bg-[#4EA8A6]" />
              <span className="text-[#9BA3B0]">{online} Online</span>
            </span>
            <span className="flex items-center gap-1.5">
              <span className="w-1.5 h-1.5 rounded-full bg-[#E85D5D]" />
              <span className="text-[#9BA3B0]">{offline} Offline</span>
            </span>
          </div>

          {/* Source filter */}
          <div className="flex items-center gap-1 bg-[#1A2230] rounded-lg p-1 border border-[#1E2A3A]">
            {(['all', 'dgt', 'madrid'] as SourceFilter[]).map((src) => (
              <button
                key={src}
                onClick={() => setSourceFilter(src)}
                className={clsx(
                  'px-3 py-1 rounded-md text-[11px] font-medium transition-all duration-150 uppercase',
                  sourceFilter === src
                    ? 'bg-[#232E3F] text-[#D4915E]'
                    : 'text-[#5E6A7A] hover:text-[#9BA3B0]',
                )}
              >
                {src}
              </button>
            ))}
          </div>
        </div>

        <div className="flex items-center gap-2">
          {/* Refresh */}
          <button
            onClick={() => refetch()}
            disabled={isFetching}
            className="p-2 rounded-lg text-[#5E6A7A] hover:text-[#9BA3B0] hover:bg-[#1A2230] transition-all duration-150 disabled:opacity-50"
          >
            <RefreshCw size={15} className={isFetching ? 'animate-spin' : ''} />
          </button>

          {/* Grid size */}
          <div className="flex items-center gap-1 bg-[#1A2230] rounded-lg p-1 border border-[#1E2A3A]">
            {gridIcons.map(({ size, icon: Icon }) => (
              <button
                key={size}
                onClick={() => setGridSize(size)}
                className={clsx(
                  'p-2 rounded-md transition-all duration-150 ease-in-out',
                  gridSize === size ? 'bg-[#232E3F] text-[#D4915E]' : 'text-[#5E6A7A] hover:text-[#9BA3B0]',
                )}
              >
                <Icon size={15} />
              </button>
            ))}
          </div>
        </div>
      </div>

      {/* Loading */}
      {isLoading && <Spinner className="h-64" />}

      {/* Empty state */}
      {!isLoading && all.length === 0 && (
        <div className="text-center py-20 text-[#5E6A7A] text-[13px]">
          No camera data yet. The DGT and Madrid camera ingestors will populate this page
          once Celery workers start polling.
        </div>
      )}

      {/* Grid */}
      {!isLoading && all.length > 0 && (
        <div className={clsx('grid gap-4', gridClasses[gridSize])}>
          {all.map((cam) => (
            <CameraCard key={`${cam.source}-${cam.id}`} cam={cam} />
          ))}
        </div>
      )}
    </PageContainer>
  );
}
