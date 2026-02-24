import { useEffect, useRef } from 'react';
import { useProjectStore } from '../store/projectStore';
import { getStatusStreamUrl } from '../api/client';

export function useAgentProgress() {
  const sourceRef = useRef<EventSource | null>(null);
  const projectId = useProjectStore((s) => s.projectId);
  const sseActive = useProjectStore((s) => s.sseActive);
  const updateAgent = useProjectStore((s) => s.updateAgent);
  const setAppState = useProjectStore((s) => s.setAppState);
  const setSseActive = useProjectStore((s) => s.setSseActive);
  const fetchResults = useProjectStore((s) => s.fetchResults);

  useEffect(() => {
    if (!projectId || !sseActive) return;

    const url = getStatusStreamUrl(projectId);
    const source = new EventSource(url);
    sourceRef.current = source;

    // ── Agent lifecycle events ──────────────────────────────
    source.addEventListener('running', (e) => {
      const data = JSON.parse((e as MessageEvent).data);
      updateAgent(data.agent_id, { status: 'running' });
    });

    source.addEventListener('completed', (e) => {
      const data = JSON.parse((e as MessageEvent).data);
      updateAgent(data.agent_id, {
        status: 'completed',
        stats: data.stats ?? {},
        time: data.time,
        flags: data.flags,
      });
    });

    // ── Planning events ─────────────────────────────────────
    source.addEventListener('planning', (e) => {
      const data = JSON.parse((e as MessageEvent).data);
      updateAgent(data.agent_id, { planStatus: 'planning' } as any);
    });

    source.addEventListener('plan_ready', (e) => {
      const data = JSON.parse((e as MessageEvent).data);
      updateAgent(data.agent_id, {
        planStatus: 'ready',
        planStrategy: data.strategy,
        planApproach: data.approach,
      } as any);
    });

    // ── COVE verification events ────────────────────────────
    source.addEventListener('cove_running', (e) => {
      const data = JSON.parse((e as MessageEvent).data);
      updateAgent(data.agent_id, { coveStatus: 'running' } as any);
    });

    source.addEventListener('cove_completed', (e) => {
      const data = JSON.parse((e as MessageEvent).data);
      updateAgent(data.agent_id, {
        coveStatus: data.passed ? 'passed' : 'failed',
        coveConfidence: data.confidence,
        coveIssues: (data.issues || []).map((i: any) => i.message || i),
      } as any);
    });

    source.addEventListener('cove_retry', (e) => {
      const data = JSON.parse((e as MessageEvent).data);
      updateAgent(data.agent_id, {
        status: 'running',
        coveStatus: 'running',
      } as any);
    });

    // ── Pipeline completion ─────────────────────────────────
    source.addEventListener('pipeline_complete', () => {
      source.close();
      setSseActive(false);
      fetchResults(projectId);
    });

    source.addEventListener('pipeline_error', (e) => {
      const data = JSON.parse((e as MessageEvent).data);
      source.close();
      setSseActive(false);
      if (data.agent_id) {
        updateAgent(data.agent_id, { status: 'error' });
      }
      setAppState('error');
    });

    source.onerror = () => {
      source.close();
      setSseActive(false);
    };

    return () => {
      source.close();
    };
  }, [projectId, sseActive, updateAgent, setAppState, setSseActive, fetchResults]);
}
