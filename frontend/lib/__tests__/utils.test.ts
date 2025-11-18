import { cn } from '../utils'

describe('cn utility', () => {
  it('merges class names correctly', () => {
    const result = cn('text-red-500', 'bg-blue-500')
    expect(result).toContain('text-red-500')
    expect(result).toContain('bg-blue-500')
  })

  it('handles conditional classes', () => {
    const isActive = true
    const result = cn('base-class', isActive && 'active-class')
    expect(result).toContain('base-class')
    expect(result).toContain('active-class')
  })

  it('handles undefined and null values', () => {
    const result = cn('text-red-500', undefined, null, 'bg-blue-500')
    expect(result).toContain('text-red-500')
    expect(result).toContain('bg-blue-500')
  })

  it('merges conflicting tailwind classes correctly', () => {
    // twMerge should handle conflicting classes
    const result = cn('p-4', 'p-8')
    // The last class should win
    expect(result).toContain('p-8')
    expect(result).not.toContain('p-4')
  })

  it('handles array of classes', () => {
    const result = cn(['text-red-500', 'bg-blue-500'])
    expect(result).toContain('text-red-500')
    expect(result).toContain('bg-blue-500')
  })

  it('handles empty input', () => {
    const result = cn()
    expect(result).toBe('')
  })
})
