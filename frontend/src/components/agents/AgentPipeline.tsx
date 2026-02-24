import { useState } from 'react';
import { useProjectStore } from '../../store/projectStore';
import type { AgentInfo } from '../../types';

const statusDot: Record<string, string> = {
  pending: 'bg-slate-300',
  running: 'bg-amber-400 animate-pulse',
  completed: 'bg-green-500',
  error: 'bg-red-500',
};

function CoveBadge({ agent }: { agent: AgentInfo }) {
  if (!agent.coveStatus || agent.coveStatus === 'idle') return null;
  const colors = {
    running: 'bg-purple-100 text-purple-700 border-purple-200',
    passed: 'bg-green-100 text-green-700 border-green-200',
    failed: 'bg-red-100 text-red-700 border-red-200',
  };
  return (
    <span className={`text-[10px] px-1.5 py-0.5 rounded border ${colors[agent.coveStatus]}`}>
      {agent.coveStatus === 'running' ? (
        <span className="animate-pulse">COVE...</span>
      ) : (
        <>COVE {agent.coveConfidence != null ? `${Math.round(agent.coveConfidence * 100)}%` : agent.coveStatus}</>
      )}
    </span>
  );
}

function PlanBadge({ agent }: { agent: AgentInfo }) {
  if (!agent.planStatus || agent.planStatus === 'idle') return null;
  return (
    <span className={`text-[10px] px-1.5 py-0.5 rounded border ${
      agent.planStatus === 'planning'
        ? 'bg-indigo-100 text-indigo-700 border-indigo-200 animate-pulse'
        : 'bg-indigo-50 text-indigo-600 border-indigo-200'
    }`}>
      {agent.planStatus === 'planning' ? 'Planning...' : 'Plan ready'}
    </span>
  );
}

function AgentDot({ agent }: { agent: AgentInfo }) {
  return (
    <div className="flex items-center gap-1.5 group relative">
      <span className={`w-2.5 h-2.5 rounded-full ${statusDot[agent.status]} shrink-0`} />
      <span className={`text-[12px] font-medium ${
        agent.status === 'completed' ? 'text-text-main' :
        agent.status === 'running' ? 'text-amber-700' :
        agent.status === 'error' ? 'text-red-700' :
        'text-text-light'
      }`}>
        {agent.name.replace(' Agent', '')}
        {agent.status === 'running' && <span className="ml-0.5 animate-pulse">...</span>}
      </span>
      {agent.status === 'completed' && agent.time !== undefined && (
        <span className="text-[10px] text-text-light">{agent.time.toFixed(1)}s</span>
      )}
      <CoveBadge agent={agent} />
    </div>
  );
}

function AgentExpandedRow({ agent }: { agent: AgentInfo }) {
  const [showPlan, setShowPlan] = useState(false);
  const hasStats = agent.status === 'completed' && Object.keys(agent.stats).length > 0;
  return (
    <div className={`flex items-start gap-3 px-4 py-2 rounded-lg ${
      agent.status === 'running' ? 'bg-amber-50 border border-amber-200' :
      agent.status === 'error' ? 'bg-red-50 border border-red-200' :
      agent.status === 'completed' ? 'bg-green-50/50 border border-green-200/50' :
      'bg-slate-50 border border-slate-200/50'
    }`}>
      <span className={`w-2.5 h-2.5 rounded-full mt-1 shrink-0 ${statusDot[agent.status]}`} />
      <div className="flex-1 min-w-0">
        <div className="flex items-center gap-2 flex-wrap">
          <span className="text-[12px] font-semibold">{agent.id}. {agent.name}</span>
          <span className="text-[10px] text-text-light">{agent.description}</span>
          <PlanBadge agent={agent} />
          <CoveBadge agent={agent} />
        </div>

        {/* Plan text (collapsible) */}
        {agent.planStatus === 'ready' && agent.planStrategy && (
          <div className="mt-1">
            <button
              onClick={(e) => { e.stopPropagation(); setShowPlan(!showPlan); }}
              className="text-[10px] text-indigo-600 hover:text-indigo-800 underline"
            >
              {showPlan ? 'Hide plan' : 'Show plan'}
            </button>
            {showPlan && (
              <div className="mt-1 text-[11px] text-indigo-800 bg-indigo-50 rounded px-2 py-1">
                <p className="font-medium">{agent.planStrategy}</p>
                {agent.planApproach && agent.planApproach.length > 0 && (
                  <ul className="list-disc list-inside mt-0.5 space-y-0.5">
                    {agent.planApproach.map((step, i) => (
                      <li key={i}>{step}</li>
                    ))}
                  </ul>
                )}
              </div>
            )}
          </div>
        )}

        {hasStats && (
          <div className="flex flex-wrap gap-x-4 gap-y-0.5 mt-1">
            {Object.entries(agent.stats).map(([key, val]) => (
              <span key={key} className="text-[11px] text-text-light">
                {key}: <span className="font-semibold text-text-main">{val}</span>
              </span>
            ))}
            {agent.time !== undefined && (
              <span className="text-[11px] text-text-light">
                Time: <span className="font-semibold text-text-main">{agent.time.toFixed(1)}s</span>
              </span>
            )}
          </div>
        )}

        {/* COVE issues */}
        {agent.coveIssues && agent.coveIssues.length > 0 && (
          <div className="flex flex-wrap gap-2 mt-1">
            {agent.coveIssues.map((issue, i) => (
              <span key={i} className="text-[10px] text-purple-700 bg-purple-100 px-1.5 py-0.5 rounded">
                {issue}
              </span>
            ))}
          </div>
        )}

        {agent.flags && agent.flags.length > 0 && (
          <div className="flex flex-wrap gap-2 mt-1">
            {agent.flags.map((flag, i) => (
              <span key={i} className="text-[10px] text-amber-700 bg-amber-100 px-1.5 py-0.5 rounded">
                {flag}
              </span>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}

export default function AgentPipeline() {
  const { agents, appState } = useProjectStore();
  const [expanded, setExpanded] = useState(false);

  const isProcessing = appState === 'processing';
  const isComplete = agents.every((a) => a.status === 'completed');
  const hasAnyActivity = agents.some((a) => a.status !== 'pending');
  const runningAgent = agents.find((a) => a.status === 'running');
  const completedCount = agents.filter((a) => a.status === 'completed').length;

  // Auto-expand while processing
  const showExpanded = expanded || isProcessing;

  if (!hasAnyActivity && appState === 'empty') return null;

  return (
    <div className="bg-card border-b border-border">
      {/* Collapsed: single row of dots */}
      <div
        className="flex items-center gap-4 px-5 py-2 cursor-pointer hover:bg-bg/50 transition-all"
        onClick={() => setExpanded(!expanded)}
      >
        <div className="flex items-center gap-1 shrink-0">
          <svg
            width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="3"
            className={`text-text-light transition-transform ${showExpanded ? 'rotate-90' : ''}`}
          >
            <polyline points="9 18 15 12 9 6" />
          </svg>
          <span className="text-[11px] font-bold uppercase tracking-wider text-text-light">
            Pipeline
          </span>
        </div>

        {/* Dot indicators */}
        <div className="flex items-center gap-3">
          {agents.map((agent) => (
            <AgentDot key={agent.id} agent={agent} />
          ))}
        </div>

        {/* Processing status text */}
        <div className="flex-1" />
        {isProcessing && runningAgent && (
          <span className="text-[11px] text-amber-700 font-medium animate-pulse">
            {runningAgent.name}...
          </span>
        )}
        {isComplete && (
          <span className="text-[11px] text-green-700 font-medium">
            All agents complete
          </span>
        )}
        {!isProcessing && !isComplete && completedCount > 0 && (
          <span className="text-[11px] text-text-light">
            {completedCount}/{agents.length} done
          </span>
        )}
      </div>

      {/* Expanded: full agent details */}
      {showExpanded && (
        <div className="px-5 pb-3 flex flex-col gap-1.5">
          {agents.map((agent) => (
            <AgentExpandedRow key={agent.id} agent={agent} />
          ))}
        </div>
      )}
    </div>
  );
}
