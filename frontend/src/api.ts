export type User = { id: string; name: string; email: string; role: 'customer' | 'admin' };
export type Movie = { id: string; title: string; poster_url: string; language: string; duration_minutes: number; rating: 'U' | 'UA' | 'A'; description: string };
export type Show = { id: string; movie_id: string; starts_at: string; ticket_price: number; duration_minutes: number; available_seats: number; title?: string };
export type Seat = { label: string; status: 'available' | 'held' | 'booked' };
export type Booking = { id: string; amount: number; status: string; starts_at: string; title: string; seats: string; customer_name?: string };

const API_URL = import.meta.env.VITE_API_URL ?? '/api';
export async function api<T>(path: string, options: RequestInit = {}): Promise<T> {
  const token = localStorage.getItem('token');
  const response = await fetch(`${API_URL}${path}`, {
    ...options,
    headers: {
      'Content-Type': 'application/json',
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
      ...options.headers,
    },
  });
  if (!response.ok) {
    const body = await response.json().catch(() => null) as { detail?: string } | null;
    throw new Error(body?.detail ?? `Request failed (${response.status})`);
  }
  if (response.status === 204) return undefined as T;
  return response.json() as Promise<T>;
}

export function money(paise: number): string {
  return new Intl.NumberFormat('en-IN', { style: 'currency', currency: 'INR', maximumFractionDigits: 0 }).format(paise / 100);
}

export function formatTime(value: string, options?: Intl.DateTimeFormatOptions): string {
  return new Date(value).toLocaleString('en-IN', options ?? { weekday: 'short', day: 'numeric', month: 'short', hour: 'numeric', minute: '2-digit' });
}
