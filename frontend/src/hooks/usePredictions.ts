import { useMutation } from '@tanstack/react-query';
import { fetchPrediction, type PredictionRequest } from '../api/predictions';

export function usePrediction() {
  return useMutation({
    mutationFn: (req: PredictionRequest) => fetchPrediction(req),
  });
}
