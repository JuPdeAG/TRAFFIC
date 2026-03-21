import { useState } from 'react';
import { TrendingUp } from 'lucide-react';
import PageContainer from '../components/ui/PageContainer';
import Card from '../components/ui/Card';
import Button from '../components/ui/Button';
import Badge from '../components/ui/Badge';
import Spinner from '../components/ui/Spinner';
import { useSegments } from '../hooks/useSegments';
import { usePrediction } from '../hooks/usePredictions';
import type { PredictionResult } from '../api/predictions';

type RiskLevel = 'critical' | 'high' | 'medium' | 'low';

const CONGESTION_TO_LEVEL: Record<string, RiskLevel> = {
  free_flow: 'low',
  moderate: 'medium',
  heavy: 'high',
  gridlock: 'critical',
  unknown: 'low',
};

const HORIZONS = [15, 30, 60] as const;

function formatTimestamp(iso: string): string {
  try {
    return new Date(iso).toLocaleString(undefined, {
      year: 'numeric',
      month: 'short',
      day: '2-digit',
      hour: '2-digit',
      minute: '2-digit',
      second: '2-digit',
    });
  } catch {
    return iso;
  }
}

function ResultCard({ result }: { result: PredictionResult }) {
  const level = CONGESTION_TO_LEVEL[result.congestion_level] ?? 'low';
  const confidencePct = Math.round(result.confidence * 100);
  const barColor =
    confidencePct >= 75 ? '#4EA86A' : confidencePct >= 50 ? '#D4C24E' : '#E8A44C';
  const isHeuristic = result.confidence < 0.5;

  return (
    <div className="flex flex-col gap-5">
      {/* Speed */}
      <div className="flex flex-col gap-1">
        <span className="text-[11px] uppercase tracking-[0.06em] text-[#9BA3B0] font-medium">
          Predicted Speed
        </span>
        <div className="flex items-baseline gap-2">
          <span className="text-[48px] font-bold tracking-[-0.03em] text-[#F4F5F7] leading-none">
            {Math.round(result.predicted_speed_kmh)}
          </span>
          <span className="text-[20px] text-[#9BA3B0] font-medium">km/h</span>
        </div>
      </div>

      {/* Congestion level */}
      <div className="flex flex-col gap-1.5">
        <span className="text-[11px] uppercase tracking-[0.06em] text-[#9BA3B0] font-medium">
          Congestion Level
        </span>
        <Badge level={level} />
      </div>

      {/* Confidence bar */}
      <div className="flex flex-col gap-1.5">
        <div className="flex items-center justify-between">
          <span className="text-[11px] uppercase tracking-[0.06em] text-[#9BA3B0] font-medium">
            Model Confidence
          </span>
          <span className="text-[13px] font-semibold text-[#F4F5F7]">{confidencePct}%</span>
        </div>
        <div className="h-2 bg-[#0B0F14] rounded-full overflow-hidden">
          <div
            className="h-full rounded-full transition-all duration-500"
            style={{ width: `${confidencePct}%`, backgroundColor: barColor }}
          />
        </div>
      </div>

      {/* Predicted at */}
      <div className="flex flex-col gap-1">
        <span className="text-[11px] uppercase tracking-[0.06em] text-[#9BA3B0] font-medium">
          Predicted At
        </span>
        <span className="text-[13px] text-[#F4F5F7]">{formatTimestamp(result.predicted_at)}</span>
      </div>

      {/* Horizon */}
      <div className="flex flex-col gap-1">
        <span className="text-[11px] uppercase tracking-[0.06em] text-[#9BA3B0] font-medium">
          Horizon
        </span>
        <span className="text-[13px] text-[#F4F5F7]">{result.horizon_minutes} minutes ahead</span>
      </div>

      {/* Heuristic warning */}
      {isHeuristic && (
        <div className="flex items-start gap-2.5 px-3 py-2.5 rounded-lg bg-[#E8A44C]/10 border border-[#E8A44C]/20">
          <span className="w-1.5 h-1.5 rounded-full bg-[#E8A44C] mt-1.5 shrink-0" />
          <span className="text-[12px] text-[#E8A44C] leading-relaxed">
            Heuristic estimate — train model for better accuracy
          </span>
        </div>
      )}
    </div>
  );
}

export default function Predictions() {
  const { data: segments, isLoading: segmentsLoading } = useSegments();
  const prediction = usePrediction();

  const [selectedSegmentId, setSelectedSegmentId] = useState<string>('');
  const [horizon, setHorizon] = useState<number>(30);

  const hasSegments = segments && segments.length > 0;

  const handlePredict = () => {
    if (!selectedSegmentId) return;
    prediction.mutate({ segment_id: selectedSegmentId, horizon_minutes: horizon });
  };

  // Set default segment once data loads
  if (hasSegments && !selectedSegmentId) {
    setSelectedSegmentId(segments[0].id);
  }

  return (
    <PageContainer className="flex flex-col gap-6">
      {/* Page header */}
      <div className="flex items-center gap-3">
        <div className="w-9 h-9 rounded-lg bg-[#D4915E]/10 flex items-center justify-center">
          <TrendingUp size={20} className="text-[#D4915E]" />
        </div>
        <div>
          <h1 className="text-[20px] font-semibold tracking-[-0.02em] text-[#F4F5F7]">
            Traffic Predictions
          </h1>
          <p className="text-[13px] text-[#9BA3B0] mt-0.5">
            Congestion forecasts for road segments
          </p>
        </div>
      </div>

      {/* No segments empty state */}
      {!segmentsLoading && !hasSegments && (
        <Card className="flex flex-col items-center justify-center py-20 gap-3">
          <TrendingUp size={32} className="text-[#2A3A4E]" />
          <p className="text-[14px] text-[#5E6A7A] text-center">
            No segments in database. Run the seed script to add demo data.
          </p>
          <code className="text-[12px] text-[#9BA3B0] bg-[#0B0F14] px-3 py-1.5 rounded-md border border-[#1E2A3A]">
            python scripts/seed_demo_data.py
          </code>
        </Card>
      )}

      {/* Main layout — 2 columns */}
      {(segmentsLoading || hasSegments) && (
        <div className="grid grid-cols-2 gap-5 items-start">
          {/* ── Left column: controls ── */}
          <Card className="flex flex-col gap-5">
            <h2 className="text-[15px] font-semibold tracking-[-0.02em] text-[#F4F5F7]">
              Prediction Parameters
            </h2>

            {/* Segment selector */}
            <div className="flex flex-col gap-1.5">
              <label className="text-[11px] uppercase tracking-[0.06em] text-[#9BA3B0] font-medium">
                Road Segment
              </label>
              {segmentsLoading ? (
                <div className="h-9 bg-[#0B0F14] border border-[#1E2A3A] rounded-lg animate-pulse" />
              ) : (
                <select
                  value={selectedSegmentId}
                  onChange={(e) => setSelectedSegmentId(e.target.value)}
                  className="w-full bg-[#0B0F14] border border-[#1E2A3A] rounded-lg px-3 py-2 text-[13px] text-[#F4F5F7] outline-none focus:border-[#D4915E] transition-colors duration-150 appearance-none cursor-pointer"
                >
                  {segments?.map((seg) => (
                    <option key={seg.id} value={seg.id}>
                      {seg.name ?? seg.id}
                    </option>
                  ))}
                </select>
              )}
            </div>

            {/* Horizon selector */}
            <div className="flex flex-col gap-1.5">
              <label className="text-[11px] uppercase tracking-[0.06em] text-[#9BA3B0] font-medium">
                Forecast Horizon
              </label>
              <div className="flex gap-2">
                {HORIZONS.map((h) => (
                  <button
                    key={h}
                    onClick={() => setHorizon(h)}
                    className={[
                      'flex-1 py-2 rounded-lg text-[13px] font-medium border transition-all duration-150',
                      horizon === h
                        ? 'bg-[#D4915E]/10 border-[#D4915E] text-[#D4915E]'
                        : 'bg-transparent border-[#2A3A4E] text-[#9BA3B0] hover:border-[#D4915E]/50 hover:text-[#F4F5F7]',
                    ].join(' ')}
                  >
                    {h} min
                  </button>
                ))}
              </div>
            </div>

            {/* Predict button */}
            <Button
              variant="primary"
              size="lg"
              onClick={handlePredict}
              disabled={!selectedSegmentId || prediction.isPending}
              className="w-full justify-center disabled:opacity-50 disabled:cursor-not-allowed"
            >
              {prediction.isPending ? (
                <>
                  <Spinner className="w-4 h-4" />
                  Predicting…
                </>
              ) : (
                <>
                  <TrendingUp size={16} />
                  Predict
                </>
              )}
            </Button>

            {/* Error state */}
            {prediction.isError && (
              <div className="flex items-start gap-2.5 px-3 py-2.5 rounded-lg bg-[#E85D5D]/10 border border-[#E85D5D]/20">
                <span className="w-1.5 h-1.5 rounded-full bg-[#E85D5D] mt-1.5 shrink-0" />
                <span className="text-[12px] text-[#E85D5D] leading-relaxed">
                  {(prediction.error as Error)?.message ?? 'Prediction request failed. Please try again.'}
                </span>
              </div>
            )}
          </Card>

          {/* ── Right column: result ── */}
          <Card className="min-h-[320px] flex flex-col justify-center">
            {prediction.isPending && (
              <Spinner className="h-48" />
            )}

            {!prediction.isPending && !prediction.data && !prediction.isError && (
              <div className="flex flex-col items-center justify-center h-48 gap-3">
                <TrendingUp size={32} className="text-[#2A3A4E]" />
                <p className="text-[13px] text-[#5E6A7A] text-center">
                  Select a segment and horizon, then click <span className="text-[#9BA3B0]">Predict</span> to see results.
                </p>
              </div>
            )}

            {!prediction.isPending && prediction.isError && (
              <div className="flex flex-col items-center justify-center h-48 gap-3">
                <span className="text-[32px]">⚠</span>
                <p className="text-[13px] text-[#5E6A7A] text-center">
                  Could not retrieve prediction.
                </p>
              </div>
            )}

            {!prediction.isPending && prediction.data && (
              <ResultCard result={prediction.data} />
            )}
          </Card>
        </div>
      )}
    </PageContainer>
  );
}
