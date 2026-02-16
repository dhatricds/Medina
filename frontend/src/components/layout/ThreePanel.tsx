import type { ReactNode } from 'react';

interface Props {
  left: ReactNode;
  center: ReactNode;
  right: ReactNode;
}

export default function ThreePanel({ left, center, right }: Props) {
  return (
    <div className="flex-1 flex overflow-hidden">
      <div className="w-[35%] min-w-[300px] bg-pdf-bg flex flex-col border-r border-border">
        {left}
      </div>
      <div className="w-[240px] min-w-[220px] bg-card border-r border-border overflow-y-auto p-4">
        {center}
      </div>
      <div className="flex-1 flex flex-col overflow-hidden">
        {right}
      </div>
    </div>
  );
}
