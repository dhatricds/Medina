import { useState } from 'react';
import type { CorrectionReason } from '../../types';

interface Props {
  fixtureCode: string;
  onSubmit: (reason: CorrectionReason, detail: string) => void;
  onClose: () => void;
}

const REASONS: { value: CorrectionReason; label: string }[] = [
  { value: 'extra_fixture', label: 'Extra / wrong fixture' },
  { value: 'wrong_fixture_code', label: 'Wrong fixture code' },
  { value: 'vlm_misread', label: 'VLM misread' },
  { value: 'other', label: 'Other' },
];

export default function ReasonModal({ fixtureCode, onSubmit, onClose }: Props) {
  const [reason, setReason] = useState<CorrectionReason>('extra_fixture');
  const [detail, setDetail] = useState('');

  return (
    <div className="fixed inset-0 bg-black/40 flex items-center justify-center z-50" onClick={onClose}>
      <div
        className="bg-white rounded-lg shadow-xl w-[340px]"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="px-5 py-3.5 border-b border-border">
          <h3 className="text-sm font-bold text-text-main">Remove "{fixtureCode}"</h3>
          <p className="text-xs text-text-light mt-0.5">Why should this fixture be removed?</p>
        </div>

        <div className="px-5 py-4 space-y-3">
          <div>
            <label className="block text-xs font-semibold text-text-main mb-1">Reason</label>
            <select
              value={reason}
              onChange={(e) => setReason(e.target.value as CorrectionReason)}
              className="w-full px-3 py-2 border border-border rounded-md text-sm focus:outline-none focus:ring-2 focus:ring-accent/40 focus:border-accent bg-white"
            >
              {REASONS.map((r) => (
                <option key={r.value} value={r.value}>{r.label}</option>
              ))}
            </select>
          </div>
          <div>
            <label className="block text-xs font-semibold text-text-main mb-1">Note (optional)</label>
            <input
              type="text"
              value={detail}
              onChange={(e) => setDetail(e.target.value)}
              placeholder="Brief explanation..."
              className="w-full px-3 py-2 border border-border rounded-md text-sm focus:outline-none focus:ring-2 focus:ring-accent/40 focus:border-accent"
            />
          </div>
        </div>

        <div className="px-5 py-3 border-t border-border flex justify-end gap-2.5">
          <button
            className="px-3.5 py-1.5 rounded-md text-xs font-semibold bg-white text-text-main border border-border hover:bg-bg cursor-pointer transition-all"
            onClick={onClose}
          >
            Skip
          </button>
          <button
            className="px-3.5 py-1.5 rounded-md text-xs font-semibold bg-error text-white hover:bg-red-600 cursor-pointer transition-all"
            onClick={() => { onSubmit(reason, detail); onClose(); }}
          >
            Remove
          </button>
        </div>
      </div>
    </div>
  );
}
