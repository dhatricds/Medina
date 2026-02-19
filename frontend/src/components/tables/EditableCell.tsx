import { useRef, useState } from 'react';

interface Props {
  value: number;
  onChange: (newValue: number) => void;
  onLocate?: () => void;
}

export default function EditableCell({ value, onChange, onLocate }: Props) {
  const [editing, setEditing] = useState(false);
  const cellRef = useRef<HTMLTableCellElement>(null);

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
      } ${value === 0 ? 'text-slate-300' : ''}`}
      title={onLocate && !editing ? 'Click to locate on plan · Double-click to edit' : undefined}
    >
      {value}
      {onLocate && !editing && (
        <span className="absolute right-0.5 top-1/2 -translate-y-1/2 opacity-0 group-hover/cell:opacity-60 text-accent text-[9px] pointer-events-none">
          <svg viewBox="0 0 16 16" fill="currentColor" className="w-2.5 h-2.5">
            <path d="M8 1a5 5 0 0 0-5 5c0 3.5 5 9 5 9s5-5.5 5-9a5 5 0 0 0-5-5zm0 7a2 2 0 1 1 0-4 2 2 0 0 1 0 4z" />
          </svg>
        </span>
      )}
    </td>
  );
}
