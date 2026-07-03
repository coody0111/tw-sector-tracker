import { describe, it, expect, vi, beforeEach } from 'vitest'
import { renderHook, waitFor } from '@testing-library/react'
import { useSectorData } from './useSectorData'
import type { SectorData } from '../types'

const fakeData: SectorData = {
  date: '2026-07-01',
  market: { avgPct: 1.2, up: 300, down: 200, flat: 40 },
  metaSectors: [],
}

beforeEach(() => {
  globalThis.fetch = vi.fn(() =>
    Promise.resolve({
      ok: true,
      json: () => Promise.resolve(fakeData),
    } as Response),
  )
})

describe('useSectorData', () => {
  it('fetches and returns data.json contents', async () => {
    const { result } = renderHook(() => useSectorData())
    expect(result.current.loading).toBe(true)

    await waitFor(() => expect(result.current.loading).toBe(false))

    expect(result.current.data).toEqual(fakeData)
    expect(result.current.error).toBeNull()
    expect(fetch).toHaveBeenCalledWith('./data.json')
  })

  it('sets error when fetch fails', async () => {
    globalThis.fetch = vi.fn(() => Promise.resolve({ ok: false, status: 404 } as Response))
    const { result } = renderHook(() => useSectorData())

    await waitFor(() => expect(result.current.loading).toBe(false))

    expect(result.current.data).toBeNull()
    expect(result.current.error).toContain('404')
  })
})
