import { useState } from 'react';
import { useProjectStore } from '../../store/projectStore';
import { interpretFixIt, confirmFixIt } from '../../api/client';
import type { FixItAction } from '../../types';

type PanelState = 'input' | 'loading' | 'preview' | 'processing';

export default function FixItPanel() {
  const { projectId, appState, reprocessWithFeedback } = useProjectStore();
  const [state, setState] = useState<PanelState>('input');
  const [text, setText] = useState('');
  const [actions, setActions] = useState<FixItAction[]>([]);
  const [checked, setChecked] = useState<boolean[]>([]);
  const [explanation, setExplanation] = useState('');
  const [clarification, setClarification] = useState('');
  const [error, setError] = useState('');

  const handleInterpret = async () => {
    if (!projectId || !text.trim()) return;
    setState('loading');
    setError('');
    try {
      const result = await interpretFixIt(projectId, text.trim());
      if (result.clarification) {
        setClarification(result.clarification);
      }
      if (result.actions.length > 0) {
        setActions(result.actions);
        setChecked(result.actions.map(() => true));
        setExplanation(result.explanation);
        setState('preview');
      } else {
        setError(result.explanation || 'No actions could be determined from your input.');
        setState('input');
      }
    } catch (e) {
      setError(`Failed to interpret: ${e}`);
      setState('input');
    }
  };

  const handleConfirm = async () => {
    if (!projectId) return;
    const confirmed = actions.filter((_, i) => checked[i]);
    if (confirmed.length === 0) return;

    setState('processing');
    try {
      // Save snapshot for diff tracking
      useProjectStore.getState().savePreReprocessSnapshot();
      await confirmFixIt(projectId, confirmed);
      // Trigger SSE listening for reprocess progress
      useProjectStore.setState({
        appState: 'processing',
        agents: [
          { id: 1, name: 'Search Agent', description: 'Load, discover, classify pages', status: 'pending', stats: {} },
          { id: 2, name: 'Schedule Agent', description: 'Extract fixture specs from schedule', status: 'pending', stats: {} },
          { id: 3, name: 'Count Agent', description: 'Count fixtures on plans', status: 'pending', stats: {} },
          { id: 4, name: 'Keynote Agent', description: 'Extract and count keynotes', status: 'pending', stats: {} },
          { id: 5, name: 'QA Agent', description: 'Validate and generate output', status: 'pending', stats: {} },
        ],
        sseActive: true,
        error: null,
        fixItOpen: false,
      });
      // Reset panel for next use
      setText('');
      setActions([]);
      setChecked([]);
      setState('input');
    } catch (e) {
      setError(`Failed to confirm: ${e}`);
      setState('preview');
    }
  };

  const handleCancel = () => {
    setActions([]);
    setChecked([]);
    setExplanation('');
    setClarification('');
    setError('');
    setState('input');
  };

  const toggleAction = (index: number) => {
    setChecked((prev) => prev.map((v, i) => (i === index ? !v : v)));
  };

  const actionLabel = (a: FixItAction) => {
    switch (a.action) {
      case 'count_override': {
        const sheet = a.fixture_data?.sheet || '?';
        const corrected = a.fixture_data?.corrected ?? '?';
        return `Update ${a.fixture_code} count on ${sheet} to ${corrected}`;
      }
      case 'add':
        return `Add fixture ${a.fixture_code}${a.fixture_data?.description ? ` (${a.fixture_data.description})` : ''}`;
      case 'remove':
        return `Remove fixture ${a.fixture_code}`;
      case 'update_spec': {
        const fields = Object.keys(a.spec_patches).join(', ');
        return `Update ${a.fixture_code} specs: ${fields}`;
      }
      case 'reclassify_page':
        return `Reclassify ${a.fixture_code} as ${a.fixture_data?.new_type || 'lighting plan'}`;
      case 'split_page':
        return `Split ${a.fixture_code} into viewport sub-plans`;
      default:
        return `${a.action} ${a.fixture_code}`;
    }
  };

  const confidenceColor = (c: number) => {
    if (c >= 0.9) return 'text-green-600';
    if (c >= 0.7) return 'text-yellow-600';
    return 'text-red-600';
  };

  return (
    <div className="border-b border-border bg-amber-50/50 px-4 py-3">
      {/* Input state */}
      {state === 'input' && (
        <div>
          <div className="flex gap-2">
            <textarea
              className="flex-1 px-3 py-2 text-sm border border-amber-200 rounded-md bg-white resize-none focus:outline-none focus:ring-1 focus:ring-amber-400 placeholder:text-text-light"
              rows={2}
              placeholder='Describe what needs fixing... (e.g., "B6 count should be 25 not 26 on E200")'
              value={text}
              onChange={(e) => setText(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === 'Enter' && !e.shiftKey) {
                  e.preventDefault();
                  handleInterpret();
                }
              }}
            />
            <button
              className="px-4 py-2 rounded-md text-xs font-semibold bg-amber-500 text-white hover:bg-amber-600 cursor-pointer transition-all disabled:opacity-50 disabled:cursor-not-allowed self-end"
              disabled={!text.trim() || appState === 'processing'}
              onClick={handleInterpret}
            >
              Fix It
            </button>
          </div>
          {error && (
            <p className="text-xs text-red-600 mt-1.5">{error}</p>
          )}
          {clarification && (
            <p className="text-xs text-amber-700 mt-1.5">{clarification}</p>
          )}
        </div>
      )}

      {/* Loading state */}
      {state === 'loading' && (
        <div className="flex items-center gap-2 py-2">
          <div className="w-4 h-4 border-2 border-amber-400/30 border-t-amber-500 rounded-full animate-spin" />
          <span className="text-sm text-amber-700">Interpreting your correction...</span>
        </div>
      )}

      {/* Preview state */}
      {state === 'preview' && (
        <div>
          <p className="text-sm font-medium text-amber-800 mb-2">{explanation}</p>
          <div className="space-y-1.5 mb-3">
            {actions.map((action, i) => (
              <label
                key={i}
                className="flex items-start gap-2 text-sm cursor-pointer hover:bg-amber-100/50 rounded px-1.5 py-1 -mx-1.5"
              >
                <input
                  type="checkbox"
                  checked={checked[i]}
                  onChange={() => toggleAction(i)}
                  className="mt-0.5 accent-amber-500"
                />
                <span className="flex-1">
                  {actionLabel(action)}
                  <span className={`ml-2 text-[10px] ${confidenceColor(action.confidence)}`}>
                    {Math.round(action.confidence * 100)}%
                  </span>
                </span>
              </label>
            ))}
          </div>
          {clarification && (
            <p className="text-xs text-amber-700 mb-2">{clarification}</p>
          )}
          <div className="flex items-center justify-between">
            <button
              className="px-3 py-1.5 rounded-md text-xs font-semibold text-text-light hover:text-text-main cursor-pointer transition-all"
              onClick={handleCancel}
            >
              Cancel
            </button>
            <button
              className="px-4 py-1.5 rounded-md text-xs font-semibold bg-amber-500 text-white hover:bg-amber-600 cursor-pointer transition-all disabled:opacity-50"
              disabled={checked.every((v) => !v)}
              onClick={handleConfirm}
            >
              Confirm & Reprocess
            </button>
          </div>
          {error && (
            <p className="text-xs text-red-600 mt-1.5">{error}</p>
          )}
        </div>
      )}

      {/* Processing state */}
      {state === 'processing' && (
        <div className="flex items-center gap-2 py-2">
          <div className="w-4 h-4 border-2 border-amber-400/30 border-t-amber-500 rounded-full animate-spin" />
          <span className="text-sm text-amber-700">Reprocessing with corrections...</span>
        </div>
      )}
    </div>
  );
}
