import { useEffect, useRef, useState } from 'react';
import { api } from '../services/api';
import '../styles/Settings.css';

const emptyUser = { first_name: '', last_name: '', email: '', license_number: '', pharmacy_name: '', role: 'pharmacist', password: '' };
const requestOptions = { timeout: 90000 };
const roles = ['doctor', 'superadmin', 'admin', 'pharmacist', 'nurse', 'receptionist'];
const fields = [['first_name', 'First Name', 100], ['last_name', 'Last Name', 100], ['email', 'Email', 150], ['license_number', 'Professional License Number', 100], ['pharmacy_name', 'Pharmacy Name', 150], ['password', 'Initial Password', 128]];
function message(error) {
  if (error.code === 'ECONNABORTED' || error.code === 'ETIMEDOUT') return 'The service took too long to respond. Refresh the user list before retrying a change; it may already have been saved.';
  if (error.response?.status >= 500) return 'The service is temporarily unavailable. Refresh the user list before retrying a change.';
  const detail = error.response?.data?.detail;
  return typeof detail === 'string' ? detail : Array.isArray(detail) ? detail.map((item) => item.msg).join(' ') : 'Unable to reach the service. Please retry.';
}

export default function Users({ profile }) {
  const deleteDialog = useRef(null);
  const actionLock = useRef(false);
  const [users, setUsers] = useState([]);
  const [draft, setDraft] = useState(emptyUser);
  const [selected, setSelected] = useState(null);
  const [password, setPassword] = useState('');
  const [confirmation, setConfirmation] = useState('');
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');
  const [retry, setRetry] = useState(0);
  useEffect(() => {
    let active = true;
    setLoading(true);
    api.get('/users', requestOptions).then(({ data }) => { if (active) setUsers(data); })
      .catch((err) => { if (active) setError(message(err)); })
      .finally(() => { if (active) setLoading(false); });
    return () => { active = false; };
  }, [retry]);

  useEffect(() => {
    if (selected?.action === 'delete') deleteDialog.current?.showModal();
    else deleteDialog.current?.close();
  }, [selected]);

  function cancelAction() {
    if (actionLock.current) return;
    setSelected(null); setPassword(''); setConfirmation(''); setError('');
  }

  async function create(event) {
    event.preventDefault();
    if (busy) return;
    setBusy(true); setError(''); setNotice('');
    try {
      const { data } = await api.post('/users', draft, requestOptions);
      setUsers((current) => [...current, data]);
      setDraft(emptyUser);
      const delivery = { sent: 'Welcome email sent, with the configured address copied.', partial: 'Welcome email delivery was incomplete. Check the recipient and CC addresses.', failed: 'Welcome email could not be sent. The account is saved; do not create it again.', not_configured: 'Welcome email is not configured on this server.' };
      setNotice(`User ${data.email} created. ${delivery[data.welcome_email_status] || ''}`);
    } catch (err) { setError(message(err)); }
    finally { setBusy(false); }
  }
  function select(user, action) {
    if (busy || actionLock.current) return;
    if (String(user.id) === String(profile.id)) { setError('You cannot delete or reset your own account here.'); return; }
    setSelected({ user, action }); setPassword(''); setConfirmation(''); setError(''); setNotice('');
  }
  async function perform(event) {
    event.preventDefault();
    if (busy || actionLock.current || !selected) return;
    if (String(selected.user.id) === String(profile.id)) { setError('You cannot delete your own account.'); return; }
    setError(''); setNotice('');
    if (selected.action === 'reset' && password !== confirmation) { setError('Passwords must match.'); return; }
    actionLock.current = true; setBusy(true);
    try {
      if (selected.action === 'delete') {
        await api.delete(`/users/${selected.user.id}`, requestOptions);
        setUsers((current) => current.filter((user) => user.id !== selected.user.id));
        setNotice(`User ${selected.user.email} deleted.`);
      } else {
        await api.post(`/users/${selected.user.id}/reset-password`, { new_password: password, confirm_password: confirmation }, requestOptions);
        setNotice(`Password reset for ${selected.user.email}. Their existing sessions have been revoked.`);
      }
      setSelected(null); setPassword(''); setConfirmation('');
    } catch (err) { setError(message(err)); }
    finally { actionLock.current = false; setBusy(false); }
  }
  return <div className="settings-page">
    <div className="settings-header"><h1>User Management</h1></div>
    {error && <p role="alert" className="login-error">{error}</p>}
    {notice && <p role="status">{notice}</p>}
    <section className="settings-card mb-4"><form onSubmit={create} className="w-100">
      <h2>Create User</h2>
      <fieldset disabled={busy || loading}>
        <div className="settings-row">
          {fields.map(([key, label, maxLength]) => <div className="field-group" key={key}>
            <label htmlFor={`user-${key}`}>{label}</label>
            <input id={`user-${key}`} type={key === 'password' ? 'password' : key === 'email' ? 'email' : 'text'}
              autoComplete={key === 'password' ? 'new-password' : 'off'} required maxLength={maxLength}
              minLength={key === 'password' ? 12 : 1} value={draft[key]} onChange={(event) => setDraft((current) => ({ ...current, [key]: event.target.value }))} />
          </div>)}
          <div className="field-group"><label htmlFor="user-role">Role</label><select id="user-role" value={draft.role} onChange={(event) => setDraft((current) => ({ ...current, role: event.target.value }))}>{roles.map((role) => <option key={role} value={role}>{role}</option>)}</select></div>
        </div>
        <p className="inline-note mt-3">Passwords must contain 12–128 characters. New users receive a welcome email after creation. Share their initial password separately.</p>
        <div className="form-actions"><button type="submit" className="primary-button">{busy ? 'Please wait…' : 'Create User'}</button></div>
      </fieldset>
    </form></section>
    {selected?.action === 'reset' && <section className="settings-card mb-4"><form className="w-100" onSubmit={perform}>
      <h2>{selected.action === 'delete' ? 'Delete user' : 'Reset password'}: {selected.user.email}</h2>
      {selected.action === 'delete' ? <p>This permanently deletes this account and revokes its sessions.</p> : <div className="settings-row">
        <div className="field-group"><label htmlFor="admin-password">New Password</label><input id="admin-password" type="password" autoComplete="new-password" required minLength={12} maxLength={128} disabled={busy} value={password} onChange={(event) => setPassword(event.target.value)} /></div>
        <div className="field-group"><label htmlFor="admin-confirmation">Confirm Password</label><input id="admin-confirmation" type="password" autoComplete="new-password" required minLength={12} maxLength={128} disabled={busy} value={confirmation} onChange={(event) => setConfirmation(event.target.value)} /></div>
      </div>}
      <div className="form-actions"><button type="button" className="secondary-button" disabled={busy} onClick={() => { setSelected(null); setPassword(''); setConfirmation(''); }}>Cancel</button><button type="submit" className="primary-button" disabled={busy}>{busy ? 'Please wait…' : selected.action === 'delete' ? 'Confirm Delete' : 'Reset Password'}</button></div>
    </form></section>}
    <dialog ref={deleteDialog} className="user-delete-dialog" aria-labelledby="delete-user-title" aria-describedby="delete-user-description" onCancel={event => { event.preventDefault(); cancelAction(); }}>
      {selected?.action === 'delete' && <form onSubmit={perform} aria-busy={busy}>
        <h2 id="delete-user-title">Delete user?</h2>
        <p id="delete-user-description">Are you sure you want to delete <strong>{selected.user.email}</strong>? This permanently deletes the account and signs them out. This cannot be undone.</p>
        {error && <p role="alert" className="login-error">{error}</p>}
        <div className="form-actions"><button autoFocus type="button" className="secondary-button" disabled={busy} onClick={cancelAction}>Cancel</button><button type="submit" className="primary-button" disabled={busy}>{busy ? 'Deleting…' : 'Delete User'}</button></div>
      </form>}
    </dialog>
    <section className="settings-card"><div className="w-100">
      <h2>Users</h2>
      {loading ? <p role="status">Loading users… The testing service may take up to 90 seconds to respond.</p> : <div className="table-responsive"><table className="table align-middle"><thead><tr><th>Name</th><th>Email</th><th>Role</th><th>Actions</th></tr></thead><tbody>
        {users.map((user) => <tr key={user.id}><td>{user.first_name} {user.last_name}</td><td>{user.email}</td><td>{user.role}</td><td>{String(user.id) === String(profile.id) ? 'Your account' : <div className="d-flex gap-2"><button type="button" className="secondary-button" disabled={busy} onClick={() => select(user, 'reset')}>Reset Password</button>{user.role !== 'superadmin' && <button type="button" className="secondary-button" disabled={busy} onClick={() => select(user, 'delete')}>Delete</button>}</div>}</td></tr>)}
      </tbody></table></div>}
      <button type="button" className="secondary-button" disabled={busy || loading} onClick={() => { setError(''); setRetry((value) => value + 1); }}>Refresh users</button>
    </div></section>
  </div>;
}
