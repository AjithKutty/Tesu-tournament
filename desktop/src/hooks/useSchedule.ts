import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import * as api from '../api/endpoints'

export function useConfig() {
  return useQuery({ queryKey: ['config'], queryFn: api.getConfig })
}

export function useSchedule() {
  return useQuery({ queryKey: ['schedule'], queryFn: api.getSchedule })
}

export function useGenerateSchedule() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (keepPinned: boolean) => api.generateSchedule(keepPinned),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ['schedule'] }) },
  })
}

export function useMoveMatch() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({ matchId, court, timeMinute }: { matchId: string; court: number; timeMinute: number }) =>
      api.moveMatch(matchId, court, timeMinute),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ['schedule'] }) },
  })
}

export function useSwapMatches() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({ a, b }: { a: string; b: string }) => api.swapMatches(a, b),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ['schedule'] }) },
  })
}

export function useUpdateResult() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({ matchId, score }: { matchId: string; score: string }) =>
      api.updateResult(matchId, score),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ['schedule'] }) },
  })
}

export function useSetConfig() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: api.setConfig,
    onSuccess: () => { qc.invalidateQueries({ queryKey: ['config'] }) },
  })
}

export function useSetDivisionMap() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: api.setDivisionMap,
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['config'] })
      qc.invalidateQueries({ queryKey: ['schedule'] })
    },
  })
}
