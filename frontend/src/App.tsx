import { useEffect } from 'react';
import TopBar from './components/layout/TopBar';
import BottomBar from './components/layout/BottomBar';
import ThreePanel from './components/layout/ThreePanel';
import UploadZone from './components/pdf/UploadZone';
import PdfViewer from './components/pdf/PdfViewer';
import AgentPipeline from './components/agents/AgentPipeline';
import TabContainer from './components/tables/TabContainer';
import { useProjectStore } from './store/projectStore';
import { useAgentProgress } from './hooks/useAgentProgress';

export default function App() {
  const { appState, loadSources } = useProjectStore();

  // Activate SSE listener for agent progress events
  useAgentProgress();

  // Load available data sources on mount
  useEffect(() => {
    loadSources();
  }, [loadSources]);

  const showPdfViewer = appState === 'processing' || appState === 'complete';

  return (
    <div className="h-screen flex flex-col overflow-hidden bg-bg text-text-main">
      <TopBar />
      <ThreePanel
        left={showPdfViewer ? <PdfViewer /> : <UploadZone />}
        center={<AgentPipeline />}
        right={<TabContainer />}
      />
      <BottomBar />
    </div>
  );
}
