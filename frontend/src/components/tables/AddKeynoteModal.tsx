import { useState } from 'react';
import { useProjectStore } from '../../store/projectStore';

interface Props {
  onClose: () => void;
}

export default function AddKeynoteModal({ onClose }: Props) {
  const { projectData } = useProjectStore();
  const [keynoteNumber, setKeynoteNumber] = useState('');
  const [keynoteText, setKeynoteText] = useState('');
  const [plan, setPlan] = useState(projectData?.lighting_plans[0] ?? '');
  const [count, setCount] = useState(1);

  const plans = projectData?.lighting_plans ?? [];

  // Check if keynote number already exists
  const existing = projectData?.keynotes.find(
    (k) => String(k.keynote_number) === keynoteNumber.trim()
  );

  const handleSubmit = () => {
    const num = keynoteNumber.trim();
    if (!num || !plan) return;

    const { projectId, addCorrection } = useProjectStore.getState();
    if (!projectId || !projectData) return;

    // Add keynote to local state
    useProjectStore.setState((s) => {
      if (!s.projectData) return {};
      const existingKn = s.projectData.keynotes.find(
        (k) => String(k.keynote_number) === num
      );
      let updatedKeynotes;
      if (existingKn) {
        // Update existing keynote's count on this plan
        updatedKeynotes = s.projectData.keynotes.map((k) => {
          if (String(k.keynote_number) !== num) return k;
          const newCounts = { ...k.counts_per_plan, [plan]: (k.counts_per_plan[plan] ?? 0) + count };
          return { ...k, counts_per_plan: newCounts, total: Object.values(newCounts).reduce((a, b) => a + b, 0) };
        });
      } else {
        // Add brand new keynote
        updatedKeynotes = [
          ...s.projectData.keynotes,
          {
            keynote_number: num,
            keynote_text: keynoteText.trim(),
            counts_per_plan: { [plan]: count },
            total: count,
            fixture_references: [],
          },
        ];
      }
      return { projectData: { ...s.projectData, keynotes: updatedKeynotes } };
    });

    // Track correction
    addCorrection({ type: 'keynote', identifier: num, sheet: plan, original: 0, corrected: count });

    // Submit feedback to backend
    import('../../api/client').then(({ submitFeedback }) => {
      submitFeedback(projectId, {
        action: 'keynote_count_override',
        fixture_code: `KN-${num}`,
        reason: 'missing_keynote',
        reason_detail: `Added keynote #${num} on ${plan} with count ${count}`,
        fixture_data: {
          sheet: plan,
          corrected: count,
          original: 0,
          keynote_number: num,
          keynote_text: keynoteText.trim(),
        },
      }).then(() => {
        useProjectStore.setState((s) => ({ feedbackCount: s.feedbackCount + 1 }));
      }).catch(() => {});
    });

    onClose();
  };

  return (
    <div className="fixed inset-0 bg-black/40 flex items-center justify-center z-50" onClick={onClose}>
      <div
        className="bg-white rounded-lg shadow-xl w-[380px] max-h-[80vh] overflow-auto"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="px-5 py-4 border-b border-border">
          <h3 className="text-base font-bold text-text-main">Add Keynote</h3>
          <p className="text-xs text-text-light mt-1">Add a keynote the pipeline missed</p>
        </div>

        <div className="px-5 py-4 space-y-3.5">
          {/* Keynote Number */}
          <div>
            <label className="block text-xs font-semibold text-text-main mb-1">
              Keynote Number <span className="text-error">*</span>
            </label>
            <input
              type="text"
              value={keynoteNumber}
              onChange={(e) => setKeynoteNumber(e.target.value)}
              placeholder="e.g. 5"
              className="w-full px-3 py-2 border border-border rounded-md text-sm focus:outline-none focus:ring-2 focus:ring-accent/40 focus:border-accent"
              autoFocus
            />
            {existing && (
              <p className="text-[10px] text-warning mt-1">
                Keynote #{keynoteNumber} already exists — count will be added to existing entry
              </p>
            )}
          </div>

          {/* Keynote Text */}
          <div>
            <label className="block text-xs font-semibold text-text-main mb-1">Keynote Text</label>
            <textarea
              value={keynoteText}
              onChange={(e) => setKeynoteText(e.target.value)}
              placeholder="e.g. CONNECT TO EXISTING CIRCUIT"
              rows={2}
              className="w-full px-3 py-2 border border-border rounded-md text-sm focus:outline-none focus:ring-2 focus:ring-accent/40 focus:border-accent resize-none"
            />
          </div>

          {/* Plan */}
          <div>
            <label className="block text-xs font-semibold text-text-main mb-1">
              Plan <span className="text-error">*</span>
            </label>
            <select
              value={plan}
              onChange={(e) => setPlan(e.target.value)}
              className="w-full px-3 py-2 border border-border rounded-md text-sm focus:outline-none focus:ring-2 focus:ring-accent/40 focus:border-accent bg-white"
            >
              {plans.map((p) => (
                <option key={p} value={p}>{p}</option>
              ))}
            </select>
          </div>

          {/* Count */}
          <div>
            <label className="block text-xs font-semibold text-text-main mb-1">Count</label>
            <input
              type="number"
              value={count}
              onChange={(e) => setCount(Math.max(0, parseInt(e.target.value) || 0))}
              min={0}
              className="w-24 px-3 py-2 border border-border rounded-md text-sm focus:outline-none focus:ring-2 focus:ring-accent/40 focus:border-accent"
            />
          </div>
        </div>

        <div className="px-5 py-3.5 border-t border-border flex justify-end gap-2.5">
          <button
            className="px-4 py-2 rounded-md text-xs font-semibold bg-white text-text-main border border-border hover:bg-bg cursor-pointer transition-all"
            onClick={onClose}
          >
            Cancel
          </button>
          <button
            className="px-4 py-2 rounded-md text-xs font-semibold bg-accent text-white hover:bg-accent-hover cursor-pointer transition-all disabled:opacity-50 disabled:cursor-not-allowed"
            onClick={handleSubmit}
            disabled={!keynoteNumber.trim() || !plan}
          >
            Add Keynote
          </button>
        </div>
      </div>
    </div>
  );
}
