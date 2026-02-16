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
      });
    });

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
