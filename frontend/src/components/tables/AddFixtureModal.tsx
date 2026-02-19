import { useState } from 'react';
import type { FixtureFeedback, CorrectionReason } from '../../types';

interface Props {
  onSubmit: (item: FixtureFeedback) => void;
  onClose: () => void;
}

const REASONS: { value: CorrectionReason; label: string }[] = [
  { value: 'missed_embedded_schedule', label: 'Missed from embedded schedule' },
  { value: 'missing_fixture', label: 'Missing fixture type' },
  { value: 'vlm_misread', label: 'VLM failed to read' },
  { value: 'other', label: 'Other' },
];

export default function AddFixtureModal({ onSubmit, onClose }: Props) {
  const [code, setCode] = useState('');
  const [description, setDescription] = useState('');
  const [reason, setReason] = useState<CorrectionReason>('missed_embedded_schedule');
  const [detail, setDetail] = useState('');
  const [showSpecs, setShowSpecs] = useState(false);
  const [voltage, setVoltage] = useState('');
  const [mounting, setMounting] = useState('');
  const [lumens, setLumens] = useState('');
  const [cct, setCct] = useState('');
  const [dimming, setDimming] = useState('');
  const [maxVa, setMaxVa] = useState('');

  const handleSubmit = () => {
    if (!code.trim()) return;
    onSubmit({
      action: 'add',
      fixture_code: code.trim().toUpperCase(),
      reason,
      reason_detail: detail,
      fixture_data: {
        description,
        fixture_style: description.toUpperCase(),
        voltage,
        mounting,
        lumens,
        cct,
        dimming,
        max_va: maxVa,
      },
    });
    onClose();
  };

  return (
    <div className="fixed inset-0 bg-black/40 flex items-center justify-center z-50" onClick={onClose}>
      <div
        className="bg-white rounded-lg shadow-xl w-[420px] max-h-[80vh] overflow-auto"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="px-5 py-4 border-b border-border">
          <h3 className="text-base font-bold text-text-main">Add Missing Fixture</h3>
          <p className="text-xs text-text-light mt-1">Add a fixture type that the pipeline missed</p>
        </div>

        <div className="px-5 py-4 space-y-3.5">
          {/* Code */}
          <div>
            <label className="block text-xs font-semibold text-text-main mb-1">
              Fixture Code <span className="text-error">*</span>
            </label>
            <input
              type="text"
              value={code}
              onChange={(e) => setCode(e.target.value)}
              placeholder="e.g. G18"
              className="w-full px-3 py-2 border border-border rounded-md text-sm focus:outline-none focus:ring-2 focus:ring-accent/40 focus:border-accent"
              autoFocus
            />
          </div>

          {/* Description */}
          <div>
            <label className="block text-xs font-semibold text-text-main mb-1">Description</label>
            <input
              type="text"
              value={description}
              onChange={(e) => setDescription(e.target.value)}
              placeholder="e.g. 2x2 LED troffer"
              className="w-full px-3 py-2 border border-border rounded-md text-sm focus:outline-none focus:ring-2 focus:ring-accent/40 focus:border-accent"
            />
          </div>

          {/* Reason */}
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

          {/* Detail */}
          <div>
            <label className="block text-xs font-semibold text-text-main mb-1">Details (optional)</label>
            <textarea
              value={detail}
              onChange={(e) => setDetail(e.target.value)}
              placeholder="Additional context..."
              rows={2}
              className="w-full px-3 py-2 border border-border rounded-md text-sm focus:outline-none focus:ring-2 focus:ring-accent/40 focus:border-accent resize-none"
            />
          </div>

          {/* More Specs Toggle */}
          <button
            type="button"
            className="text-xs text-accent font-semibold hover:underline cursor-pointer"
            onClick={() => setShowSpecs(!showSpecs)}
          >
            {showSpecs ? '- Hide specs' : '+ More specs'}
          </button>

          {showSpecs && (
            <div className="grid grid-cols-2 gap-3">
              {[
                { label: 'Voltage', value: voltage, set: setVoltage, placeholder: '120/277' },
                { label: 'Mounting', value: mounting, set: setMounting, placeholder: 'RECESSED' },
                { label: 'Lumens', value: lumens, set: setLumens, placeholder: '5000 LUM' },
                { label: 'CCT', value: cct, set: setCct, placeholder: '4000K' },
                { label: 'Dimming', value: dimming, set: setDimming, placeholder: '0-10V' },
                { label: 'Max VA', value: maxVa, set: setMaxVa, placeholder: '50 VA' },
              ].map(({ label, value, set, placeholder }) => (
                <div key={label}>
                  <label className="block text-[10px] font-semibold text-text-light mb-0.5">{label}</label>
                  <input
                    type="text"
                    value={value}
                    onChange={(e) => set(e.target.value)}
                    placeholder={placeholder}
                    className="w-full px-2.5 py-1.5 border border-border rounded text-xs focus:outline-none focus:ring-2 focus:ring-accent/40 focus:border-accent"
                  />
                </div>
              ))}
            </div>
          )}
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
            disabled={!code.trim()}
          >
            Add Fixture
          </button>
        </div>
      </div>
    </div>
  );
}
