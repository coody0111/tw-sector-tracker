interface SearchBarProps {
  onSearch: (query: string) => void
}

export function SearchBar({ onSearch }: SearchBarProps) {
  return (
    <input
      className="search-bar"
      type="text"
      placeholder="搜尋族群或股票代號/名稱"
      onChange={(e) => onSearch(e.target.value)}
    />
  )
}
