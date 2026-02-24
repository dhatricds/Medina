import { useRef, useState } from 'react';

interface Props {
  value: number;
  onChange: (newValue: number) => void;
  onLocate?: () => void;
  /** Previous count before reprocess — shown as diff indicator when present. */
  previousCount?: number;
}

export default function EditableCell({ value, onChange, onLocate, previousCount }: Props) {
  const [editing, setEditing] = useState(false);
  const cellRef = useRef<HTMLTableCellElement>(null);

  const hasDiff = previousCount !== undefined && previousCount !== value;
  const diffAmount = hasDiff ? value - previousCount! : 0;
  const diffUp = diffAmount > 0;
  const diffDown = diffAmount < 0;

  const handleInput = () => {
    if (!cellRef.current) return;
    const text = cellRef.current.textContent ?? '0';
    const parsed = parseInt(text, 10) || 0;
    if (parsed !== value) {
      onChange(parsed);
    }
    setEditing(false);
  };

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter') {
      e.preventDefault();
      cellRef.current?.blur();
    }
    if (e.key === 'Escape') {
      // Reset to original value and blur
      if (cellRef.current) cellRef.current.textContent = String(value);
      cellRef.current?.blur();
      setEditing(false);
    }
  };

  const handleClick = () => {
    if (!editing && onLocate) {
      onLocate();
    }
  };

  const handleDoubleClick = () => {
    setEditing(true);
    // Select the text for easy replacement
    setTimeout(() => {
      if (cellRef.current) {
        const range = document.createRange();
        range.selectNodeContents(cellRef.current);
        const sel = window.getSelection();
        sel?.removeAllRanges();
        sel?.addRange(range);
      }
    }, 0);
  };

  return (
    <td
      ref={cellRef}
      contentEditable={editing}
      suppressContentEditableWarning
      onBlur={handleInput}
      onKeyDown={handleKeyDown}
      onClick={handleClick}
      onDoubleClick={handleDoubleClick}
      className={`px-3.5 py-2 text-center border-b border-r border-border relative group/cell ${
        editing
          ? 'cursor-text outline-2 outline-accent bg-white'
          : onLocate
            ? 'cursor-pointer hover:bg-blue-50 hover:text-accent hover:font-semibold'
            : 'cursor-text'
      } ${value === 0 ? 'text-slate-300' : ''} ${
        diffUp ? 'bg-green-50 font-semibold' : diffDown ? 'bg-red-50 font-semibold' : ''
      }`}
      title={
        hasDiff
          ? `Changed: ${previousCount} → ${value} (${diffUp ? '+' : ''}${diffAmount})`
          : onLocate && !editing
            ? 'Click to locate on plan · Double-click to edit'
            : undefined
      }
    >
      {value}
      {hasDiff && !editing && (
        <span className={`absolute -top-1 -right-1 text-[9px] font-bold px-0.5 rounded ${
          diffUp ? 'text-green-700 bg-green-200' : 'text-red-700 bg-red-200'
        }`}>
          {diffUp ? '+' : ''}{diffAmount}
        </span>
      )}
      {onLocate && !editing && !hasDiff && (
        <span className="absolute right-0.5 top-1/2 -translate-y-1/2 opacity-0 group-hover/cell:opacity-60 text-accent text-[9px] pointer-events-none">
          <svg viewBox="0 0 16 16" fill="currentColor" className="w-2.5 h-2.5">
            <path d="M8 1a5 5 0 0 0-5 5c0 3.5 5 9 5 9s5-5.5 5-9a5 5 0 0 0-5-5zm0 7a2 2 0 1 1 0-4 2 2 0 0 1 0 4z" />
          </svg>
        </span>
      )}
    </td>
  );
}
