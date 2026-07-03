import { useEffect, useState } from 'react'
import type { SectorData } from '../types'

interface UseSectorDataResult {
  data: SectorData | null
  loading: boolean
  error: string | null
}

export function useSectorData(): UseSectorDataResult {
  const [data, setData] = useState<SectorData | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    fetch('./data.json')
      .then((res) => {
        if (!res.ok) {
          throw new Error(`Failed to load data.json: ${res.status}`)
        }
        return res.json()
      })
      .then((json: SectorData) => {
        setData(json)
        setLoading(false)
      })
      .catch((err: Error) => {
        setError(err.message)
        setLoading(false)
      })
  }, [])

  return { data, loading, error }
}
