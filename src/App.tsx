import { useEffect, useMemo, useState } from 'react';
import { Link, Navigate, Route, Routes, useNavigate, useParams } from 'react-router-dom';
import { api, formatTime, money } from './api';
import type { Booking, Movie, Seat, Show, User } from './api';

type AuthContext = { user: User | null; setSession: (token: string, user: User) => void; logout: () => void };

function App() {
  const [user, setUser] = useState<User | null>(() => {
    const saved = localStorage.getItem('user');
    return saved ? JSON.parse(saved) as User : null;
  });
  const navigate = useNavigate();
  const auth: AuthContext = {
    user,
    setSession: (token, nextUser) => { localStorage.setItem('token', token); localStorage.setItem('user', JSON.stringify(nextUser)); setUser(nextUser); },
    logout: () => { const token = localStorage.getItem('token'); if (token) void api('/auth/logout', { method: 'POST' }).catch(() => undefined); localStorage.removeItem('token'); localStorage.removeItem('user'); setUser(null); navigate('/'); },
  };
  return <div className="app-shell">
    <header className="topbar"><Link to="/" className="brand"><span className="brand-mark">Y</span> YOZIGO</Link><nav>
      <Link to="/">Movies</Link>{user && <Link to="/bookings">My bookings</Link>}{user?.role === 'admin' && <Link to="/admin">Manage</Link>}
    </nav><div className="account">{user ? <><span className="user-name">{user.name}</span><button className="quiet-button" onClick={auth.logout}>Log out</button></> : <><Link className="quiet-button" to="/login">Log in</Link><Link className="small-button" to="/register">Sign up</Link></>}</div></header>
    <main><Routes>
      <Route path="/" element={<Home />} />
      <Route path="/movie/:movieId" element={<MovieDetails />} />
      <Route path="/show/:showId" element={<Protected user={user}><ShowPage user={user} /></Protected>} />
      <Route path="/login" element={user ? <Navigate to="/" /> : <AuthPage mode="login" auth={auth} />} />
      <Route path="/register" element={user ? <Navigate to="/" /> : <AuthPage mode="register" auth={auth} />} />
      <Route path="/bookings" element={<Protected user={user}><BookingsPage /></Protected>} />
      <Route path="/admin" element={user?.role === 'admin' ? <AdminPage /> : <Navigate to="/" />} />
      <Route path="*" element={<EmptyState title="Page not found" text="That page is not available." />} />
    </Routes></main>
    <footer><span>YOZIGO CINEMA</span><span>One screen · Seats for everyone</span></footer>
  </div>;
}

function Protected({ user, children }: { user: User | null; children: React.ReactNode }) {
  return user ? <>{children}</> : <Navigate to="/login" replace />;
}

function Home() {
  const [movies, setMovies] = useState<Movie[]>([]); const [error, setError] = useState(''); const [loading, setLoading] = useState(true);
  useEffect(() => { api<Movie[]>('/movies').then(setMovies).catch((e: Error) => setError(e.message)).finally(() => setLoading(false)); }, []);
  return <><section className="hero"><div className="hero-copy"><p className="eyebrow">THE BIG SCREEN IS CALLING</p><h1>Stories worth<br /><em>showing up for.</em></h1><p>Find your next favorite, choose your seats, and we’ll save them for you.</p><a href="#now-showing" className="primary-button">Explore movies <span>↓</span></a></div><div className="hero-art"><div className="film-orbit orbit-one"/><div className="film-orbit orbit-two"/><div className="hero-ticket"><span>TONIGHT’S<br />FEATURE</span><b>YOUR<br />SEAT<br />AWAITS</b><i>✳</i></div><div className="hero-caption">A little escape, a lot of feeling.</div></div></section>
    <section className="section" id="now-showing"><div className="section-heading"><div><p className="eyebrow">NOW PLAYING</p><h2>On the big screen</h2></div><span>{movies.length} films</span></div>
      {loading ? <Loading text="Finding what’s showing…" /> : error ? <Notice kind="error">{error}</Notice> : movies.length === 0 ? <EmptyState title="The screen is quiet" text="There are no movies listed right now." /> : <div className="movie-grid">{movies.map((movie, i) => <MovieCard key={movie.id} movie={movie} index={i} />)}</div>}
    </section></>;
}

function MovieCard({ movie, index }: { movie: Movie; index: number }) {
  return <Link className={`movie-card poster-tone-${index % 4}`} to={`/movie/${movie.id}`}><div className="poster-frame">{movie.poster_url ? <img src={movie.poster_url} alt={`${movie.title} poster`} /> : <div className="poster-placeholder"><span>YOZIGO<br />PICTURES</span><b>{movie.title.split(' ').map((word) => word[0]).slice(0, 3).join('')}</b><small>NOW SHOWING</small></div>}<span className="rating-pill">{movie.rating}</span><span className="poster-arrow">↗</span></div><div className="movie-card-info"><h3>{movie.title}</h3><span>{movie.language} <i>·</i> {Math.floor(movie.duration_minutes / 60)}h {movie.duration_minutes % 60}m</span></div></Link>;
}

function MovieDetails() {
  const { movieId = '' } = useParams(); const [data, setData] = useState<{ movie: Movie; shows: Show[] } | null>(null); const [error, setError] = useState('');
  useEffect(() => { api<{ movie: Movie; shows: Show[] }>(`/movies/${movieId}`).then(setData).catch((e: Error) => setError(e.message)); }, [movieId]);
  if (error) return <Notice kind="error">{error}</Notice>; if (!data) return <Loading text="Loading film details…" />;
  const groups = data.shows.reduce<Record<string, Show[]>>((result, show) => { const date = new Date(show.starts_at).toLocaleDateString('en-CA'); (result[date] ??= []).push(show); return result; }, {});
  return <div className="detail-layout"><Link className="back-link" to="/">← All movies</Link><section className="detail-film"><div className="detail-poster poster-placeholder"><span>YOZIGO<br />PICTURES</span><b>{data.movie.title.split(' ').map((word) => word[0]).slice(0, 3).join('')}</b><small>NOW SHOWING</small></div><div className="detail-copy"><p className="eyebrow">FEATURE PRESENTATION</p><h1>{data.movie.title}</h1><p className="metadata">{data.movie.rating} <i>·</i> {data.movie.language} <i>·</i> {data.movie.duration_minutes} min</p><p className="description">{data.movie.description || 'Settle in, take a breath, and enjoy the show.'}</p><div className="show-list"><div className="show-list-head"><h2>Choose a showtime</h2><span>80 seats · One screen</span></div>{Object.keys(groups).length === 0 ? <p className="muted">No upcoming shows are scheduled.</p> : Object.entries(groups).map(([day, shows]) => <div className="show-day" key={day}><div className="day-label"><b>{new Date(`${day}T12:00:00`).toLocaleDateString('en-IN', { weekday: 'short' }).toUpperCase()}</b><span>{new Date(`${day}T12:00:00`).toLocaleDateString('en-IN', { day: 'numeric', month: 'short' })}</span></div><div className="times">{shows.map((show) => <Link to={`/show/${show.id}`} className="show-time" key={show.id}><b>{new Date(show.starts_at).toLocaleTimeString('en-IN', { hour: 'numeric', minute: '2-digit' })}</b><span>{money(show.ticket_price)} <i>·</i> {show.available_seats} left</span></Link>)}</div></div>)}</div></div></section></div>;
}

function ShowPage({ user }: { user: User | null }) {
  const { showId = '' } = useParams(); const navigate = useNavigate();
  const [data, setData] = useState<{ show: Show & { title: string }; seats: Seat[] } | null>(null);
  const [selected, setSelected] = useState<string[]>([]); const [hold, setHold] = useState<{ id: string; seats: string[]; expires_at: string; total: number } | null>(null);
  const [confirmed, setConfirmed] = useState<Booking | null>(null); const [error, setError] = useState(''); const [busy, setBusy] = useState(false); const [now, setNow] = useState(Date.now());
  const refresh = () => api<{ show: Show & { title: string }; seats: Seat[] }>(`/shows/${showId}/seats`).then(setData).catch((e: Error) => setError(e.message));
  useEffect(() => { void refresh(); }, [showId]);
  useEffect(() => { const interval = window.setInterval(() => { void refresh(); }, 3000); return () => window.clearInterval(interval); }, [showId]);
  useEffect(() => { const timer = window.setInterval(() => setNow(Date.now()), 1000); return () => window.clearInterval(timer); }, []);
  const remaining = hold ? Math.max(0, Math.ceil((new Date(hold.expires_at).getTime() - now) / 1000)) : 0;
  useEffect(() => { if (hold && remaining === 0) { setHold(null); setError('Your seat hold expired. Select your seats again.'); void refresh(); } }, [remaining]);
  const toggle = (seat: Seat) => {
    setError(''); if (hold || seat.status !== 'available') return;
    if (selected.includes(seat.label)) setSelected(selected.filter((label) => label !== seat.label));
    else if (selected.length >= 6) setError('You can choose up to 6 seats per booking.');
    else setSelected([...selected, seat.label]);
  };
  const continueToHold = async () => {
    if (!user) { navigate('/login'); return; } setBusy(true); setError('');
    try { const created = await api<{ id: string; seats: string[]; expires_at: string; total: number }>(`/shows/${showId}/holds`, { method: 'POST', body: JSON.stringify({ seats: selected }) }); setHold(created); await refresh(); }
    catch (e) { setError((e as Error).message); setSelected([]); await refresh(); }
    finally { setBusy(false); }
  };
  const pay = async (outcome: 'success' | 'failure') => {
    if (!hold) return; setBusy(true); setError('');
    try { const response = await api<{ booking?: Booking; status?: string; message?: string }>(`/holds/${hold.id}/payment`, { method: 'POST', body: JSON.stringify({ outcome }) }); if (response.booking) { setConfirmed(response.booking); setHold(null); } else setError(response.message ?? 'Payment failed. Try again.'); await refresh(); }
    catch (e) { setError((e as Error).message); if ((e as Error).message.includes('expired')) { setHold(null); setSelected([]); } await refresh(); }
    finally { setBusy(false); }
  };
  if (!data) return <Loading text="Opening the seat map…" />;
  if (confirmed) return <section className="confirmation-card"><div className="success-mark">✓</div><p className="eyebrow">YOU’RE ALL SET</p><h1>It’s a date.</h1><p>Your seats are booked. We can’t wait to see you.</p><div className="confirmation-details"><div><span>BOOKING ID</span><b>{confirmed.id.toUpperCase()}</b></div><div><span>MOVIE</span><b>{data.show.title}</b></div><div><span>SHOWTIME</span><b>{formatTime(data.show.starts_at)}</b></div><div><span>SEATS</span><b>{confirmed.seats}</b></div><div><span>TOTAL PAID</span><b>{money(confirmed.amount)}</b></div></div><Link className="primary-button" to="/bookings">View my bookings <span>→</span></Link></section>;
  return <div className="booking-layout"><Link className="back-link" to={`/movie/${data.show.movie_id}`}>← Back to showtimes</Link><div className="booking-heading"><div><p className="eyebrow">PICK YOUR SEATS</p><h1>{data.show.title}</h1><p>{formatTime(data.show.starts_at)} <i>·</i> {money(data.show.ticket_price)} per seat</p></div><span className="seat-count">{data.seats.filter((seat) => seat.status === 'available').length} seats left</span></div><div className="seat-panel"><div className="screen-label"><span/><b>SCREEN THIS WAY</b><span/></div><div className="seat-grid" aria-label="Seat map">{Array.from('ABCDEFGH').map((row) => <div className="seat-row" key={row}><span className="row-letter">{row}</span>{Array.from({ length: 10 }, (_, index) => { const label = `${row}${index + 1}`; const seat = data.seats.find((item) => item.label === label)!; const isSelected = selected.includes(label) || hold?.seats.includes(label); return <button key={label} aria-label={`${label} ${seat.status}`} title={`${label} · ${seat.status}`} disabled={seat.status !== 'available' || Boolean(hold)} onClick={() => toggle(seat)} className={`seat ${isSelected ? 'selected' : seat.status}`} />; })}<span className="row-letter">{row}</span></div>)}</div><div className="seat-legend"><span><i className="legend-seat"/> Available</span><span><i className="legend-seat legend-held"/> Held</span><span><i className="legend-seat legend-booked"/> Booked</span><span><i className="legend-seat legend-selected"/> Selected</span></div></div>
    <aside className="seat-summary"><div><p className="eyebrow">YOUR SELECTION</p><h2>{hold ? 'Seats held for you' : selected.length ? `${selected.length} seat${selected.length > 1 ? 's' : ''} selected` : 'Choose your seats'}</h2><div className="selected-labels">{hold?.seats.join(', ') ?? (selected.length ? selected.join(', ') : <span className="muted">Tap an available seat to begin</span>)}</div></div>{hold && <div className={`hold-timer ${remaining < 60 ? 'urgent' : ''}`}><div><span>TIME LEFT</span><b>{String(Math.floor(remaining / 60)).padStart(2, '0')}:{String(remaining % 60).padStart(2, '0')}</b></div><span>Your seats are saved while you pay.</span></div>}<div className="summary-total"><span>Total</span><b>{money(hold?.total ?? selected.length * data.show.ticket_price)}</b></div>{error && <Notice kind="error">{error}</Notice>}{hold ? <div className="payment-actions"><button className="primary-button full" disabled={busy || !remaining} onClick={() => void pay('success')}>{busy ? 'Processing…' : 'Payment success'}</button><button className="secondary-button full" disabled={busy || !remaining} onClick={() => void pay('failure')}>Payment failure</button><p className="payment-note">This is a simulated payment. Both outcomes are available for testing.</p></div> : <button className="primary-button full" disabled={!selected.length || busy} onClick={() => void continueToHold()}>{busy ? 'Saving your seats…' : 'Continue'} <span>→</span></button>}</aside></div>;
}

function AuthPage({ mode, auth }: { mode: 'login' | 'register'; auth: AuthContext }) {
  const navigate = useNavigate(); const [name, setName] = useState(''); const [email, setEmail] = useState(''); const [password, setPassword] = useState(''); const [error, setError] = useState(''); const [busy, setBusy] = useState(false);
  const submit = async (event: React.FormEvent) => { event.preventDefault(); setBusy(true); setError(''); try { const data = await api<{ token: string; user: User }>(`/auth/${mode}`, { method: 'POST', body: JSON.stringify(mode === 'register' ? { name, email, password } : { email, password }) }); auth.setSession(data.token, data.user); navigate('/'); } catch (e) { setError((e as Error).message); } finally { setBusy(false); } };
  return <section className="auth-layout"><div className="auth-illustration"><p className="eyebrow">A NIGHT AT THE MOVIES</p><b>Good stories<br />bring us<br /><em>together.</em></b><span>✳</span></div><div className="auth-form-wrap"><p className="eyebrow">{mode === 'login' ? 'WELCOME BACK' : 'JOIN THE AUDIENCE'}</p><h1>{mode === 'login' ? 'Sign in' : 'Create an account'}</h1><p className="muted">{mode === 'login' ? 'Pick up right where the previews left off.' : 'Your next favorite movie starts here.'}</p><form onSubmit={submit} className="form-stack">{mode === 'register' && <label>Your name<input value={name} onChange={(e) => setName(e.target.value)} minLength={1} required autoComplete="name" /></label>}<label>Email address<input type="email" value={email} onChange={(e) => setEmail(e.target.value)} required autoComplete="email" /></label><label>Password<input type="password" value={password} onChange={(e) => setPassword(e.target.value)} minLength={mode === 'register' ? 8 : undefined} required autoComplete={mode === 'login' ? 'current-password' : 'new-password'} />{mode === 'register' && <small>At least 8 characters</small>}</label>{error && <Notice kind="error">{error}</Notice>}<button className="primary-button full" disabled={busy}>{busy ? 'Please wait…' : mode === 'login' ? 'Log in' : 'Create account'} <span>→</span></button></form><p className="switch-auth">{mode === 'login' ? 'New to Yozigo?' : 'Already have an account?'} <Link to={mode === 'login' ? '/register' : '/login'}>{mode === 'login' ? 'Create an account' : 'Log in'}</Link></p></div></section>;
}

function BookingsPage() {
  const [bookings, setBookings] = useState<Booking[]>([]); const [error, setError] = useState('');
  useEffect(() => { api<Booking[]>('/bookings').then(setBookings).catch((e: Error) => setError(e.message)); }, []);
  const upcoming = useMemo(() => bookings.filter((booking) => new Date(booking.starts_at).getTime() >= Date.now()), [bookings]);
  const past = useMemo(() => bookings.filter((booking) => new Date(booking.starts_at).getTime() < Date.now()), [bookings]);
  return <section className="section page-section"><div className="section-heading"><div><p className="eyebrow">YOUR MOVIE NIGHTS</p><h1>My bookings</h1></div><span>{bookings.length} total</span></div>{error && <Notice kind="error">{error}</Notice>}{!bookings.length && !error ? <EmptyState title="Your next movie night starts here" text="Pick a film and your booking will show up right here." action={<Link className="primary-button" to="/">Browse movies</Link>} /> : <><BookingGroup title="Coming up" items={upcoming} /><BookingGroup title="Past shows" items={past} /></>}</section>;
}

function BookingGroup({ title, items }: { title: string; items: Booking[] }) {
  return <div className="booking-group"><h2>{title}<span>{items.length}</span></h2>{items.length === 0 ? <p className="muted">Nothing here yet.</p> : items.map((booking) => <div className="booking-card" key={booking.id}><div className="booking-date"><b>{new Date(booking.starts_at).toLocaleDateString('en-IN', { day: '2-digit' })}</b><span>{new Date(booking.starts_at).toLocaleDateString('en-IN', { month: 'short' }).toUpperCase()}</span></div><div className="booking-info"><h3>{booking.title}</h3><span>{formatTime(booking.starts_at)}</span><span>Seats {booking.seats}</span><span className="booking-reference">Booking ID {booking.id}</span></div><div className="booking-amount"><b>{money(booking.amount)}</b><span className="status-pill">{booking.status}</span></div></div>)}</div>;
}

function AdminPage() {
  const emptyMovie = { title: '', poster_url: '', language: '', duration_minutes: 120, rating: 'UA', description: '' };
  const [movies, setMovies] = useState<Movie[]>([]); const [shows, setShows] = useState<Show[]>([]); const [bookings, setBookings] = useState<Booking[]>([]); const [movie, setMovie] = useState(emptyMovie); const [editingId, setEditingId] = useState(''); const [show, setShow] = useState({ movie_id: '', starts_at: '', ticket_price: 25000 }); const [error, setError] = useState(''); const [message, setMessage] = useState(''); const [busy, setBusy] = useState(false);
  const load = () => { api<Movie[]>('/movies').then((list) => { setMovies(list); setShow((current) => ({ ...current, movie_id: current.movie_id || list[0]?.id || '' })); }).catch((e: Error) => setError(e.message)); api<Show[]>('/admin/shows').then(setShows).catch((e: Error) => setError(e.message)); api<Booking[]>('/admin/bookings').then(setBookings).catch((e: Error) => setError(e.message)); };
  useEffect(load, []);
  const saveMovie = async (event: React.FormEvent) => { event.preventDefault(); setBusy(true); setError(''); setMessage(''); try { await api(editingId ? `/admin/movies/${editingId}` : '/admin/movies', { method: editingId ? 'PUT' : 'POST', body: JSON.stringify({ ...movie, duration_minutes: Number(movie.duration_minutes) }) }); setMovie(emptyMovie); setEditingId(''); setMessage(editingId ? 'Movie updated.' : 'Movie added.'); load(); } catch (e) { setError((e as Error).message); } finally { setBusy(false); } };
  const addShow = async (event: React.FormEvent) => { event.preventDefault(); setBusy(true); setError(''); setMessage(''); try { await api('/admin/shows', { method: 'POST', body: JSON.stringify({ ...show, starts_at: new Date(show.starts_at).toISOString(), ticket_price: Number(show.ticket_price) }) }); setMessage('Show scheduled.'); load(); } catch (e) { setError((e as Error).message); } finally { setBusy(false); } };
  const editMovie = (selected: Movie) => { setEditingId(selected.id); setMovie({ ...selected }); window.scrollTo({ top: 0, behavior: 'smooth' }); };
  const deleteMovie = async (selected: Movie) => { if (!window.confirm(`Delete ${selected.title}? Remove its shows first.`)) return; setError(''); try { await api(`/admin/movies/${selected.id}`, { method: 'DELETE' }); setMessage('Movie deleted.'); load(); } catch (e) { setError((e as Error).message); } };
  const deleteShow = async (selected: Show) => { if (!window.confirm(`Remove the ${formatTime(selected.starts_at)} show? A show with bookings cannot be removed.`)) return; setError(''); try { await api(`/admin/shows/${selected.id}`, { method: 'DELETE' }); setMessage('Show removed.'); load(); } catch (e) { setError((e as Error).message); } };
  return <section className="section page-section admin-section"><div className="section-heading"><div><p className="eyebrow">CINEMA STAFF</p><h1>Manage the screen</h1></div><span>Administrator</span></div>{error && <Notice kind="error">{error}</Notice>}{message && <Notice kind="success">{message}</Notice>}<div className="admin-grid"><form className="admin-card form-stack" onSubmit={saveMovie}><p className="eyebrow">FILM CATALOG</p><h2>{editingId ? 'Edit movie' : 'Add a movie'}</h2><label>Title<input value={movie.title} onChange={(e) => setMovie({ ...movie, title: e.target.value })} required /></label><div className="form-two"><label>Language<input value={movie.language} onChange={(e) => setMovie({ ...movie, language: e.target.value })} required /></label><label>Rating<select value={movie.rating} onChange={(e) => setMovie({ ...movie, rating: e.target.value })}><option>U</option><option>UA</option><option>A</option></select></label></div><div className="form-two"><label>Duration (minutes)<input type="number" min="1" value={movie.duration_minutes} onChange={(e) => setMovie({ ...movie, duration_minutes: Number(e.target.value) })} required /></label><label>Poster image URL<input type="url" value={movie.poster_url} onChange={(e) => setMovie({ ...movie, poster_url: e.target.value })} /></label></div><label>Synopsis<textarea rows={3} value={movie.description} onChange={(e) => setMovie({ ...movie, description: e.target.value })} /></label><div className="inline-actions"><button className="primary-button" disabled={busy}>{editingId ? 'Save changes' : 'Add movie'} <span>→</span></button>{editingId && <button type="button" className="quiet-button" onClick={() => { setEditingId(''); setMovie(emptyMovie); }}>Cancel</button>}</div><div className="admin-list">{movies.map((item) => <div key={item.id}><span><b>{item.title}</b><small>{item.language} · {item.rating}</small></span><span className="inline-actions"><button className="text-action" type="button" onClick={() => editMovie(item)}>Edit</button><button className="text-action danger" type="button" onClick={() => void deleteMovie(item)}>Delete</button></span></div>)}</div></form>
      <div className="admin-right"><form className="admin-card form-stack" onSubmit={addShow}><p className="eyebrow">THE SCHEDULE</p><h2>Add a show</h2><label>Movie<select value={show.movie_id} onChange={(e) => setShow({ ...show, movie_id: e.target.value })} required>{movies.map((item) => <option value={item.id} key={item.id}>{item.title}</option>)}</select></label><label>Start time<input type="datetime-local" value={show.starts_at} onChange={(e) => setShow({ ...show, starts_at: e.target.value })} required /></label><label>Ticket price (₹)<input type="number" min="1" value={show.ticket_price / 100} onChange={(e) => setShow({ ...show, ticket_price: Math.round(Number(e.target.value) * 100) })} required /></label><button className="primary-button" disabled={busy || !movies.length}>Schedule show <span>→</span></button><p className="form-hint">Show times are checked against each film’s runtime so the single screen never overlaps.</p></form><div className="admin-card"><p className="eyebrow">SCHEDULED SHOWS</p><h2>Screen times</h2>{shows.map((item) => <div className="admin-list" key={item.id}><div><span><b>{item.title}</b><small>{formatTime(item.starts_at)} · {money(item.ticket_price)}</small></span><button type="button" className="text-action danger" onClick={() => void deleteShow(item)}>Remove</button></div></div>)}{shows.length === 0 && <p className="muted">No shows are scheduled yet.</p>}</div><div className="admin-card"><p className="eyebrow">BOX OFFICE</p><h2>Bookings</h2>{bookings.length ? bookings.map((item) => <div className="report-row" key={item.id}><span><b>{item.title}</b><small>{item.customer_name} · {formatTime(item.starts_at)}</small><small>Seats {item.seats} · {item.id.slice(0, 8).toUpperCase()}</small></span><b>{money(item.amount)}</b></div>) : <p className="muted">Bookings will appear here as customers reserve seats.</p>}</div></div></div></section>;
}

function Notice({ kind, children }: { kind: 'error' | 'success'; children: React.ReactNode }) { return <div className={`notice ${kind}`} role="alert">{children}</div>; }
function Loading({ text }: { text: string }) { return <div className="loading"><span className="spinner" />{text}</div>; }
function EmptyState({ title, text, action }: { title: string; text: string; action?: React.ReactNode }) { return <div className="empty-state"><span>✳</span><h2>{title}</h2><p>{text}</p>{action}</div>; }

export default App;
