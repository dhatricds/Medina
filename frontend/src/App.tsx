import { useEffect } from 'react';
import TopBar from './components/layout/TopBar';
import BottomBar from './components/layout/BottomBar';
import ThreePanel from './components/layout/ThreePanel';
import UploadZone from './components/pdf/UploadZone';
import PdfViewer from './components/pdf/PdfViewer';
import AgentPipeline from './components/agents/AgentPipeline';
import TabContainer from './components/tables/TabContainer';
import DashboardView from './components/dashboard/DashboardView';
import DashboardDetail from './components/dashboard/DashboardDetail';
import { useProjectStore } from './store/projectStore';
import { useAgentProgress } from './hooks/useAgentProgress';

export default function App() {
  const { view, appState, loadSources, loadDashboard } = useProjectStore();

  // Activate SSE listener for agent progress events
  useAgentProgress();

  // Load dashboard + sources on mount
  useEffect(() => {
    loadDashboard();
    loadSources();
  }, [loadDashboard, loadSources]);

  const showPdfViewer = appState === 'processing' || appState === 'complete';

  if (view === 'dashboard') {
    return (
      <div className="h-screen flex flex-col overflow-hidden bg-bg text-text-main">
        <TopBar />
        <DashboardView />
      </div>
    );
  }

  if (view === 'dashboard_detail') {
    return (
      <div className="h-screen flex flex-col overflow-hidden bg-bg text-text-main">
        <TopBar />
        <DashboardDetail />
      </div>
    );
  }

  return (
    <div className="h-screen flex flex-col overflow-hidden bg-bg text-text-main">
      <TopBar />
      <AgentPipeline />
      <ThreePanel
        left={showPdfViewer ? <PdfViewer /> : <UploadZone />}
        right={<TabContainer />}
      />
      <BottomBar />
    </div>
  );
}
