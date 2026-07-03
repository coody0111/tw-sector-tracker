import { describe, it, expect, vi } from 'vitest'
import { render, screen, fireEvent } from '@testing-library/react'
import { SearchBar } from './SearchBar'

describe('SearchBar', () => {
  it('calls onSearch with the typed value', () => {
    const onSearch = vi.fn()
    render(<SearchBar onSearch={onSearch} />)
    fireEvent.change(screen.getByPlaceholderText('搜尋族群或股票代號/名稱'), {
      target: { value: '辛耘' },
    })
    expect(onSearch).toHaveBeenCalledWith('辛耘')
  })
})
