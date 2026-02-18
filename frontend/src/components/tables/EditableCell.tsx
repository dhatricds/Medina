import { useRef, useState } from 'react';

interface Props {
  value: number;
  onChange: (newValue: number) => void;
  onLocate?: () => void;
}

export default function EditableCell({ value, onChange, onLocate }: Props) {
  const [edited, setEdited] = useState(false);
  const cellRef = useRef<HTMLTableCellElement>(null);

  const handleInput = () => {
    if (!cellRef.current) return;
    const text = cellRef.current.textContent ?? '0';
    const parsed = parseInt(text, 10) || 0;
    if (parsed !== value) {
      setEdited(true);
      onChange(parsed);
    }
  };

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter') {
      e.preventDefault();
      cellRef.current?.blur();
    }
  };

  return (
    <td
      ref={cellRef}
      contentEditable
      suppressContentEditableWarning
      onBlur={handleInput}
      onKeyDown={handleKeyDown}
      className={`px-3.5 py-2 text-center border-b border-r border-border cursor-text focus:outline-2 focus:outline-accent focus:bg-white relative group/cell ${
        edited ? '!bg-edit-highlight' : ''
      } ${value === 0 ? 'text-slate-300' : ''}`}
    >
      {value}
      {onLocate && (
        <button
          onClick={(e) => { e.stopPropagation(); onLocate(); }}
          className="absolute right-0.5 top-1/2 -translate-y-1/2 opacity-0 group-hover/cell:opacity-100 transition-opacity bg-accent/80 text-white rounded p-0.5 text-[9px] leading-none hover:bg-accent"
          title="Locate on plan"
          contentEditable={false}
        >
          <svg viewBox="0 0 16 16" fill="currentColor" className="w-3 h-3">
            <path d="M8 1a5 5 0 0 0-5 5c0 3.5 5 9 5 9s5-5.5 5-9a5 5 0 0 0-5-5zm0 7a2 2 0 1 1 0-4 2 2 0 0 1 0 4z" />
          </svg>
        </button>
      )}
    </td>
  );
}
