import { useRef, useState } from 'react';

interface Props {
  value: number;
  onChange: (newValue: number) => void;
}

export default function EditableCell({ value, onChange }: Props) {
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
      className={`px-3.5 py-2 text-center border-b border-r border-border cursor-text focus:outline-2 focus:outline-accent focus:bg-white ${
        edited ? '!bg-edit-highlight' : ''
      } ${value === 0 ? 'text-slate-300' : ''}`}
    >
      {value}
    </td>
  );
}
