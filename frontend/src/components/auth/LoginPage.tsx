import { useState } from 'react';
import { useAuthStore } from '../../store/authStore';

type Tab = 'login' | 'register' | 'forgot' | 'reset';

export default function LoginPage() {
  const {
    login, register, error, clearError, isLoading,
    forgotPassword, resetPassword, resetMessage, resetSuccess,
  } = useAuthStore();
  const [tab, setTab] = useState<Tab>('login');
  const [submitting, setSubmitting] = useState(false);

  // Form fields
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [name, setName] = useState('');
  const [companyName, setCompanyName] = useState('');
  const [resetToken, setResetToken] = useState('');
  const [newPassword, setNewPassword] = useState('');
  const [confirmPassword, setConfirmPassword] = useState('');

  const switchTab = (t: Tab) => {
    setTab(t);
    clearError();
  };

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setSubmitting(true);
    if (tab === 'login') {
      await login(email, password);
    } else if (tab === 'register') {
      await register({ email, password, name, company_name: companyName });
    } else if (tab === 'forgot') {
      await forgotPassword(email);
    } else if (tab === 'reset') {
      if (newPassword !== confirmPassword) {
        useAuthStore.setState({ error: 'Passwords do not match' });
        setSubmitting(false);
        return;
      }
      const ok = await resetPassword(resetToken, newPassword);
      if (ok) {
        // Auto-switch to login after successful reset
        setTimeout(() => switchTab('login'), 2000);
      }
    }
    setSubmitting(false);
  };

  return (
    <div className="min-h-screen bg-bg flex items-center justify-center p-4">
      <div className="w-full max-w-md">
        {/* Logo / header */}
        <div className="text-center mb-8">
          <div className="inline-flex items-center gap-2.5 text-2xl font-bold text-primary tracking-tight">
            <img src="/cds-vision-logo.png" className="h-10 w-auto" alt="CDS Vision" />
            Blueprint Estimation System
          </div>
          <p className="mt-2 text-sm text-text-light">
            Lighting fixture inventory extraction for electrical contractors
          </p>
        </div>

        {/* Card */}
        <div className="bg-card rounded-lg shadow-xl border border-border overflow-hidden">
          {/* Tab toggle — only show login/register when on those tabs */}
          {(tab === 'login' || tab === 'register') && (
            <div className="flex border-b border-border">
              <button
                type="button"
                className={`flex-1 py-3 text-sm font-semibold transition-colors cursor-pointer ${
                  tab === 'login'
                    ? 'text-accent border-b-2 border-accent bg-card'
                    : 'text-text-light hover:text-text-main'
                }`}
                onClick={() => switchTab('login')}
              >
                Sign In
              </button>
              <button
                type="button"
                className={`flex-1 py-3 text-sm font-semibold transition-colors cursor-pointer ${
                  tab === 'register'
                    ? 'text-accent border-b-2 border-accent bg-card'
                    : 'text-text-light hover:text-text-main'
                }`}
                onClick={() => switchTab('register')}
              >
                Register
              </button>
            </div>
          )}

          {/* Forgot / Reset header */}
          {tab === 'forgot' && (
            <div className="border-b border-border px-6 py-3">
              <h2 className="text-sm font-semibold text-text-main">Forgot Password</h2>
              <p className="text-xs text-text-light mt-0.5">
                Enter your email to receive a password reset link.
              </p>
            </div>
          )}
          {tab === 'reset' && (
            <div className="border-b border-border px-6 py-3">
              <h2 className="text-sm font-semibold text-text-main">Reset Password</h2>
              <p className="text-xs text-text-light mt-0.5">
                Enter your reset token and choose a new password.
              </p>
            </div>
          )}

          {/* Form */}
          <form onSubmit={handleSubmit} className="p-6 space-y-4">
            {tab === 'register' && (
              <>
                <div>
                  <label className="block text-xs font-medium text-text-light mb-1.5">
                    Full Name
                  </label>
                  <input
                    type="text"
                    value={name}
                    onChange={(e) => setName(e.target.value)}
                    required
                    className="w-full px-3 py-2.5 rounded-md bg-bg border border-border text-sm text-text-main placeholder-text-light focus:outline-none focus:border-accent focus:ring-1 focus:ring-accent"
                    placeholder="Jane Smith"
                  />
                </div>
                <div>
                  <label className="block text-xs font-medium text-text-light mb-1.5">
                    Company Name
                  </label>
                  <input
                    type="text"
                    value={companyName}
                    onChange={(e) => setCompanyName(e.target.value)}
                    required
                    className="w-full px-3 py-2.5 rounded-md bg-bg border border-border text-sm text-text-main placeholder-text-light focus:outline-none focus:border-accent focus:ring-1 focus:ring-accent"
                    placeholder="ACME Electric"
                  />
                </div>
              </>
            )}

            {/* Email — shown on login, register, forgot */}
            {(tab === 'login' || tab === 'register' || tab === 'forgot') && (
              <div>
                <label className="block text-xs font-medium text-text-light mb-1.5">
                  Email
                </label>
                <input
                  type="email"
                  value={email}
                  onChange={(e) => setEmail(e.target.value)}
                  required
                  className="w-full px-3 py-2.5 rounded-md bg-bg border border-border text-sm text-text-main placeholder-text-light focus:outline-none focus:border-accent focus:ring-1 focus:ring-accent"
                  placeholder="you@company.com"
                />
              </div>
            )}

            {/* Password — shown on login and register */}
            {(tab === 'login' || tab === 'register') && (
              <div>
                <label className="block text-xs font-medium text-text-light mb-1.5">
                  Password
                </label>
                <input
                  type="password"
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                  required
                  minLength={6}
                  className="w-full px-3 py-2.5 rounded-md bg-bg border border-border text-sm text-text-main placeholder-text-light focus:outline-none focus:border-accent focus:ring-1 focus:ring-accent"
                  placeholder="Min 6 characters"
                />
                {/* Forgot password link — login only */}
                {tab === 'login' && (
                  <div className="text-right mt-1.5">
                    <button
                      type="button"
                      className="text-xs text-accent hover:text-accent-hover transition-colors cursor-pointer"
                      onClick={() => switchTab('forgot')}
                    >
                      Forgot password?
                    </button>
                  </div>
                )}
              </div>
            )}

            {/* Reset token + new password fields */}
            {tab === 'reset' && (
              <>
                <div>
                  <label className="block text-xs font-medium text-text-light mb-1.5">
                    Reset Token
                  </label>
                  <input
                    type="text"
                    value={resetToken}
                    onChange={(e) => setResetToken(e.target.value)}
                    required
                    className="w-full px-3 py-2.5 rounded-md bg-bg border border-border text-sm text-text-main placeholder-text-light focus:outline-none focus:border-accent focus:ring-1 focus:ring-accent font-mono text-xs"
                    placeholder="Paste token from email / server logs"
                  />
                </div>
                <div>
                  <label className="block text-xs font-medium text-text-light mb-1.5">
                    New Password
                  </label>
                  <input
                    type="password"
                    value={newPassword}
                    onChange={(e) => setNewPassword(e.target.value)}
                    required
                    minLength={6}
                    className="w-full px-3 py-2.5 rounded-md bg-bg border border-border text-sm text-text-main placeholder-text-light focus:outline-none focus:border-accent focus:ring-1 focus:ring-accent"
                    placeholder="Min 6 characters"
                  />
                </div>
                <div>
                  <label className="block text-xs font-medium text-text-light mb-1.5">
                    Confirm Password
                  </label>
                  <input
                    type="password"
                    value={confirmPassword}
                    onChange={(e) => setConfirmPassword(e.target.value)}
                    required
                    minLength={6}
                    className="w-full px-3 py-2.5 rounded-md bg-bg border border-border text-sm text-text-main placeholder-text-light focus:outline-none focus:border-accent focus:ring-1 focus:ring-accent"
                    placeholder="Repeat new password"
                  />
                </div>
              </>
            )}

            {/* Error message */}
            {error && (
              <div className="text-red-600 text-xs bg-red-50 border border-red-200 rounded-md px-3 py-2">
                {error}
              </div>
            )}

            {/* Success / info message (forgot + reset) */}
            {resetMessage && (
              <div className={`text-xs rounded-md px-3 py-2 ${
                resetSuccess
                  ? 'text-green-700 bg-green-50 border border-green-200'
                  : 'text-blue-700 bg-blue-50 border border-blue-200'
              }`}>
                {resetMessage}
              </div>
            )}

            {/* Submit button */}
            <button
              type="submit"
              disabled={submitting}
              className="w-full py-2.5 rounded-md text-sm font-semibold bg-accent text-white hover:bg-accent-hover transition-colors cursor-pointer disabled:opacity-50"
            >
              {submitting
                ? 'Please wait...'
                : tab === 'login'
                  ? 'Sign In'
                  : tab === 'register'
                    ? 'Create Account'
                    : tab === 'forgot'
                      ? 'Send Reset Link'
                      : 'Reset Password'}
            </button>

            {/* Navigation links */}
            {tab === 'forgot' && (
              <div className="text-center space-y-2">
                <button
                  type="button"
                  className="text-xs text-accent hover:text-accent-hover transition-colors cursor-pointer"
                  onClick={() => switchTab('reset')}
                >
                  Already have a reset token?
                </button>
                <div>
                  <button
                    type="button"
                    className="text-xs text-text-light hover:text-text-main transition-colors cursor-pointer"
                    onClick={() => switchTab('login')}
                  >
                    Back to Sign In
                  </button>
                </div>
              </div>
            )}
            {tab === 'reset' && (
              <div className="text-center">
                <button
                  type="button"
                  className="text-xs text-text-light hover:text-text-main transition-colors cursor-pointer"
                  onClick={() => switchTab('login')}
                >
                  Back to Sign In
                </button>
              </div>
            )}
          </form>
        </div>
      </div>
    </div>
  );
}
