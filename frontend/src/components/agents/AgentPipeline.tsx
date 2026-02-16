import { useProjectStore } from '../../store/projectStore';
import AgentCard from './AgentCard';

export default function AgentPipeline() {
  const { agents } = useProjectStore();

  return (
    <div>
      <div className="text-xs font-bold uppercase tracking-wider text-text-light mb-4">
        Agent Pipeline
      </div>
      {agents.map((agent, i) => (
        <div key={agent.id}>
          <AgentCard agent={agent} />
          {i < agents.length - 1 && (
            <div className="w-0.5 h-2.5 bg-border mx-auto" />
          )}
        </div>
      ))}
    </div>
  );
}
