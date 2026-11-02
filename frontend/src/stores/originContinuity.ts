import { create } from 'zustand'
import type { ManualControlSide } from '../types'

type Question = { side: ManualControlSide; answer: (unchanged: boolean) => void }
export const useOriginContinuity = create<{ question: Question | null }>(() => ({ question: null }))

export function askOriginContinuity(side: ManualControlSide): Promise<boolean> {
  return new Promise((resolve) => {
    const answer = (unchanged: boolean) => {
      useOriginContinuity.setState({ question: null })
      resolve(unchanged)
    }
    useOriginContinuity.setState({ question: { side, answer } })
  })
}
