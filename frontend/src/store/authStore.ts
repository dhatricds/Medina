import { create } from 'zustand';

const BASE = import.meta.env.VITE_API_URL ?? '';

export interface AuthUser {
  id: string;
  email: string;
  name: string;
  tenant_id: string;
  tenant_name: string;
}

interface AuthState {
  user: AuthUser | null;
  isAuthenticated: boolean;
  isLoading: boolean;
  error: string | null;

  login: (email: string, password: string) => Promise<boolean>;
  register: (data: { email: string; password: string; name: string; company_name: string }) => Promise<boolean>;
  logout: () => Promise<void>;
  checkAuth: () => Promise<void>;
  clearError: () => void;
}

export const useAuthStore = create<AuthState>((set) => ({
  user: null,
  isAuthenticated: false,
  isLoading: true, // start true so ProtectedRoute waits for checkAuth
  error: null,

  login: async (email, password) => {
    set({ error: null });
    try {
      const res = await fetch(`${BASE}/api/auth/login`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        credentials: 'include',
        body: JSON.stringify({ email, password }),
      });
      if (!res.ok) {
        const body = await res.json().catch(() => ({ detail: 'Login failed' }));
        set({ error: body.detail ?? 'Login failed' });
        return false;
      }
      const user: AuthUser = await res.json();
      set({ user, isAuthenticated: true, error: null });
      return true;
    } catch {
      set({ error: 'Network error' });
      return false;
    }
  },

  register: async (data) => {
    set({ error: null });
    try {
      const res = await fetch(`${BASE}/api/auth/register`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        credentials: 'include',
        body: JSON.stringify(data),
      });
      if (!res.ok) {
        const body = await res.json().catch(() => ({ detail: 'Registration failed' }));
        set({ error: body.detail ?? 'Registration failed' });
        return false;
      }
      const user: AuthUser = await res.json();
      set({ user, isAuthenticated: true, error: null });
      return true;
    } catch {
      set({ error: 'Network error' });
      return false;
    }
  },

  logout: async () => {
    try {
      await fetch(`${BASE}/api/auth/logout`, {
        method: 'POST',
        credentials: 'include',
      });
    } catch {
      // ignore — we clear local state regardless
    }
    set({ user: null, isAuthenticated: false, error: null });
  },

  checkAuth: async () => {
    set({ isLoading: true });
    try {
      const res = await fetch(`${BASE}/api/auth/me`, { credentials: 'include' });
      if (res.ok) {
        const user: AuthUser = await res.json();
        set({ user, isAuthenticated: true, isLoading: false });
      } else {
        set({ user: null, isAuthenticated: false, isLoading: false });
      }
    } catch {
      set({ user: null, isAuthenticated: false, isLoading: false });
    }
  },

  clearError: () => set({ error: null }),
}));
