import { useState } from 'react';
import { useAuthStore } from '../../store/authStore';

type Tab = 'login' | 'register';

export default function LoginPage() {
  const { login, register, error, clearError, isLoading } = useAuthStore();
  const [tab, setTab] = useState<Tab>('login');
  const [submitting, setSubmitting] = useState(false);

  // Form fields
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [name, setName] = useState('');
  const [companyName, setCompanyName] = useState('');

  const switchTab = (t: Tab) => {
    setTab(t);
    clearError();
  };

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setSubmitting(true);
    if (tab === 'login') {
      await login(email, password);
    } else {
      await register({ email, password, name, company_name: companyName });
    }
    setSubmitting(false);
  };

  return (
    <div className="min-h-screen bg-bg flex items-center justify-center p-4">
      <div className="w-full max-w-md">
        {/* Logo / header */}
        <div className="text-center mb-8">
          <div className="inline-flex items-center gap-2.5 text-2xl font-bold text-white tracking-tight">
            <svg viewBox="0 0 28 28" fill="none" className="w-8 h-8">
              <rect width="28" height="28" rx="6" fill="#e8942e" />
              <path d="M7 14h14M14 7v14M9 9l10 10M19 9L9 19" stroke="white" strokeWidth="1.5" strokeLinecap="round" />
            </svg>
            Blueprint Estimation System
          </div>
          <p className="mt-2 text-sm text-text-muted">
            Lighting fixture inventory extraction for electrical contractors
          </p>
        </div>

        {/* Card */}
        <div className="bg-panel rounded-lg shadow-xl border border-border overflow-hidden">
          {/* Tab toggle */}
          <div className="flex border-b border-border">
            <button
              type="button"
              className={`flex-1 py-3 text-sm font-semibold transition-colors cursor-pointer ${
                tab === 'login'
                  ? 'text-accent border-b-2 border-accent bg-panel'
                  : 'text-text-muted hover:text-text-main'
              }`}
              onClick={() => switchTab('login')}
            >
              Sign In
            </button>
            <button
              type="button"
              className={`flex-1 py-3 text-sm font-semibold transition-colors cursor-pointer ${
                tab === 'register'
                  ? 'text-accent border-b-2 border-accent bg-panel'
                  : 'text-text-muted hover:text-text-main'
              }`}
              onClick={() => switchTab('register')}
            >
              Register
            </button>
          </div>

          {/* Form */}
          <form onSubmit={handleSubmit} className="p-6 space-y-4">
            {tab === 'register' && (
              <>
                <div>
                  <label className="block text-xs font-medium text-text-muted mb-1.5">
                    Full Name
                  </label>
                  <input
                    type="text"
                    value={name}
                    onChange={(e) => setName(e.target.value)}
                    required
                    className="w-full px-3 py-2.5 rounded-md bg-bg border border-border text-sm text-text-main placeholder-text-muted focus:outline-none focus:border-accent focus:ring-1 focus:ring-accent"
                    placeholder="Jane Smith"
                  />
                </div>
                <div>
                  <label className="block text-xs font-medium text-text-muted mb-1.5">
                    Company Name
                  </label>
                  <input
                    type="text"
                    value={companyName}
                    onChange={(e) => setCompanyName(e.target.value)}
                    required
                    className="w-full px-3 py-2.5 rounded-md bg-bg border border-border text-sm text-text-main placeholder-text-muted focus:outline-none focus:border-accent focus:ring-1 focus:ring-accent"
                    placeholder="ACME Electric"
                  />
                </div>
              </>
            )}

            <div>
              <label className="block text-xs font-medium text-text-muted mb-1.5">
                Email
              </label>
              <input
                type="email"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                required
                className="w-full px-3 py-2.5 rounded-md bg-bg border border-border text-sm text-text-main placeholder-text-muted focus:outline-none focus:border-accent focus:ring-1 focus:ring-accent"
                placeholder="you@company.com"
              />
            </div>

            <div>
              <label className="block text-xs font-medium text-text-muted mb-1.5">
                Password
              </label>
              <input
                type="password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                required
                minLength={6}
                className="w-full px-3 py-2.5 rounded-md bg-bg border border-border text-sm text-text-main placeholder-text-muted focus:outline-none focus:border-accent focus:ring-1 focus:ring-accent"
                placeholder="Min 6 characters"
              />
            </div>

            {error && (
              <div className="text-red-400 text-xs bg-red-500/10 border border-red-500/20 rounded-md px-3 py-2">
                {error}
              </div>
            )}

            <button
              type="submit"
              disabled={submitting}
              className="w-full py-2.5 rounded-md text-sm font-semibold bg-accent text-white hover:bg-accent-hover transition-colors cursor-pointer disabled:opacity-50"
            >
              {submitting
                ? 'Please wait...'
                : tab === 'login'
                  ? 'Sign In'
                  : 'Create Account'}
            </button>
          </form>
        </div>
      </div>
    </div>
  );
}
