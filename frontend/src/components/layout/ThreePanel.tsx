import type { ReactNode } from 'react';

interface Props {
  left: ReactNode;
  right: ReactNode;
}

export default function ThreePanel({ left, right }: Props) {
  return (
    <div className="flex-1 flex overflow-hidden">
      <div className="w-[55%] min-w-[400px] bg-pdf-bg flex flex-col overflow-hidden border-r border-border">
        {left}
      </div>
      <div className="flex-1 flex flex-col overflow-hidden">
        {right}
      </div>
    </div>
  );
}
