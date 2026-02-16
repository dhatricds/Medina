import type { AgentInfo } from '../../types';

interface Props {
  agent: AgentInfo;
}

const statusBadge: Record<string, { cls: string; label: string }> = {
  pending: { cls: 'bg-slate-100 text-slate-500', label: 'Pending' },
  running: { cls: 'bg-amber-100 text-amber-800 animate-pulse', label: 'Running' },
  completed: { cls: 'bg-green-100 text-green-800', label: 'Done' },
  error: { cls: 'bg-red-100 text-red-800', label: 'Error' },
};

const borderColor: Record<string, string> = {
  pending: 'border-l-border',
  running: 'border-l-accent',
  completed: 'border-l-success',
  error: 'border-l-error',
};

export default function AgentCard({ agent }: Props) {
  const badge = statusBadge[agent.status];
  const border = borderColor[agent.status];

  return (
    <div className={`bg-bg rounded-lg p-3 border border-border border-l-[3px] ${border} cursor-pointer hover:border-primary-light transition-all`}>
      <div className="flex items-center justify-between mb-1.5">
        <span className="text-[13px] font-semibold">{agent.id}. {agent.name}</span>
        <span className={`text-[10px] px-2 py-0.5 rounded-full font-semibold ${badge.cls}`}>
          {badge.label}
        </span>
      </div>
      <div className="text-[11px] text-text-light leading-snug">{agent.description}</div>
      {agent.status === 'completed' && Object.keys(agent.stats).length > 0 && (
        <div className="mt-2 pt-2 border-t border-border text-[11px] text-text-light">
          {Object.entries(agent.stats).map(([key, val]) => (
            <div key={key} className="flex justify-between mb-0.5">
              <span>{key}</span>
              <span className="font-semibold text-text-main">{val}</span>
            </div>
          ))}
          {agent.time !== undefined && (
            <div className="flex justify-between mb-0.5">
              <span>Time</span>
              <span className="font-semibold text-text-main">{agent.time.toFixed(1)}s</span>
            </div>
          )}
          {agent.flags && agent.flags.length > 0 && (
            <div className="mt-1.5">
              {agent.flags.map((flag, i) => (
                <div key={i} className="flex items-start gap-1 text-[11px] py-0.5">
                  <span className="text-warning shrink-0">!</span>
                  <span>{flag}</span>
                </div>
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  );
}
