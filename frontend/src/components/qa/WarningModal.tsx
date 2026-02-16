import { useProjectStore } from '../../store/projectStore';

interface Props {
  onClose: () => void;
}

export default function WarningModal({ onClose }: Props) {
  const { projectData } = useProjectStore();
  const warnings = projectData?.qa_report?.warnings ?? [];

  return (
    <div
      className="fixed inset-0 bg-black/50 flex items-center justify-center z-[1000]"
      onClick={(e) => { if (e.target === e.currentTarget) onClose(); }}
    >
      <div className="bg-white rounded-xl p-7 max-w-lg w-[90%] shadow-2xl">
        <h3 className="text-base font-bold mb-2">QA Warnings</h3>
        <p className="text-[13px] text-text-light mb-5 leading-relaxed">
          The following items need human review:
        </p>
        {warnings.map((w, i) => (
          <div key={i} className="bg-edit-highlight p-3 rounded-lg text-[13px] mb-3">
            {w}
          </div>
        ))}
        {warnings.length === 0 && (
          <div className="text-[13px] text-text-light">No warnings to display.</div>
        )}
        <div className="flex justify-end gap-2.5 mt-5">
          <button
            className="px-4 py-2 rounded-md text-[13px] font-semibold bg-white text-text-main border border-border hover:bg-bg cursor-pointer"
            onClick={onClose}
          >
            Dismiss
          </button>
          <button
            className="px-4 py-2 rounded-md text-[13px] font-semibold bg-accent text-white hover:bg-accent-hover cursor-pointer"
            onClick={onClose}
          >
            Mark as Reviewed
          </button>
        </div>
      </div>
    </div>
  );
}
