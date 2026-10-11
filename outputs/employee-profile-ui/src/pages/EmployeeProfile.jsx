import { useEffect, useRef, useState } from 'react';
import { api } from '../services/api';

const fields = [
  ['first_name', 'First Name', 100, true], ['last_name', 'Last Name', 100, true],
  ['email', 'Email Address', 150, true], ['phone', 'Phone Number', 30],
  ['license_number', 'Professional License Number', 100, true],
  ['qualification', 'Qualification / Specialization', 150],
  ['pharmacy_name', 'Pharmacy Name', 150, true], ['address_line_1', 'Address', 200],
  ['address_line_2', 'Address Line 2', 200], ['city', 'City', 100],
  ['state', 'State', 100], ['country', 'Country', 100], ['postal_code', 'Postal Code', 20],
  ['shift_timing', 'Shift Timing', 50],
];
const editable = [...fields.map(([key]) => key), 'years_experience', 'professional_bio', 'photo_data_url'];
const roles = { doctor: 'Doctor', superadmin: 'Superadmin', admin: 'Admin', pharmacist: 'Pharmacist', nurse: 'Nurse', receptionist: 'Receptionist' };

function errorMessage(error) {
  if (!error.response || error.response.status >= 500) return 'Cannot reach the local service. Your changes have not been saved. Please retry.';
  const detail = error.response.data?.detail;
  if (Array.isArray(detail)) return detail.map((item) => `${item.loc.at(-1)}: ${item.msg}`).join(' ');
  return typeof detail === 'string' ? detail : 'Unable to save your profile.';
}

export default function EmployeeProfile() {
  const [saved, setSaved] = useState(null);
  const [draft, setDraft] = useState(null);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [reading, setReading] = useState(false);
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');
  const [retry, setRetry] = useState(0);
  const photoInput = useRef(null);

  useEffect(() => {
    let active = true;
    setLoading(true);
    setError('');
    api.get('/settings/profile').then(({ data }) => {
      if (active) { setSaved(data); setDraft(data); }
    }).catch((err) => { if (active) setError(errorMessage(err)); })
      .finally(() => { if (active) setLoading(false); });
    return () => { active = false; };
  }, [retry]);

  const change = (key, value) => { setDraft((current) => ({ ...current, [key]: value })); setNotice(''); };
  const choosePhoto = async (event) => {
    const file = event.target.files?.[0];
    event.target.value = '';
    if (!file) return;
    setError(''); setNotice('');
    if (!['image/jpeg', 'image/png', 'image/webp'].includes(file.type) || file.size > 2 * 1024 * 1024) {
      setError('Choose a PNG, JPEG, or WebP photo no larger than 2 MB.'); return;
    }
    setReading(true);
    try {
      const image = await createImageBitmap(file);
      if (image.width > 4096 || image.height > 4096) { image.close(); throw new Error('size'); }
      image.close();
      const data = await new Promise((resolve, reject) => {
        const reader = new FileReader();
        reader.onload = () => resolve(reader.result);
        reader.onerror = reject;
        reader.readAsDataURL(file);
      });
      change('photo_data_url', data);
    } catch { setError('Use a valid photo up to 4096 × 4096 pixels.'); }
    finally { setReading(false); }
  };
  const save = async (event) => {
    event.preventDefault();
    if (saving || reading) return;
    setSaving(true); setError(''); setNotice('');
    const payload = Object.fromEntries(editable.map((key) => [key, draft[key] ?? null]));
    try {
      const { data } = await api.put('/settings/profile', payload);
      setSaved(data); setDraft(data); setNotice('Profile saved.');
      window.dispatchEvent(new CustomEvent('erp:profile-updated', { detail: data }));
    } catch (err) { setError(errorMessage(err)); }
    finally { setSaving(false); }
  };

  if (loading) return <p role="status">Loading your profile…</p>;
  if (!draft) return <><p role="alert">{error}</p><button type="button" onClick={() => setRetry((value) => value + 1)}>Retry</button></>;
  return <form onSubmit={save}>
    <h2>Profile</h2>
    {error && <p role="alert" className="login-error">{error}</p>}
    {notice && <p role="status">{notice}</p>}
    <fieldset disabled={saving || reading} style={{ border: 0, padding: 0, margin: 0, minWidth: 0 }}>
      <div className="settings-section profile-preview">
        <div className="profile-avatar-large" style={{ overflow: 'hidden' }}>
          {draft.photo_data_url ? <img src={draft.photo_data_url} alt="Your profile" style={{ width: '100%', height: '100%', objectFit: 'cover' }} /> : <i className="fa-solid fa-user" />}
        </div>
        <div className="profile-meta"><strong>{draft.first_name} {draft.last_name}</strong><span>{roles[draft.role] || draft.role}</span></div>
        <input ref={photoInput} type="file" accept="image/png,image/jpeg,image/webp" aria-label="Choose profile photo" hidden onChange={choosePhoto} />
        <button type="button" className="secondary-button" onClick={() => photoInput.current.click()}>Upload Photo</button>
        {draft.photo_data_url && <button type="button" className="secondary-button" onClick={() => change('photo_data_url', null)}>Remove Photo</button>}
      </div>
      <p>PNG, JPEG, or WebP · up to 2 MB. Select Save Changes to save your photo.</p>
      <div className="settings-section"><div className="settings-row">
        {fields.map(([key, label, maxLength, required]) => <div className="field-group" key={key}>
          <label htmlFor={`profile-${key}`}>{label}</label>
          <input id={`profile-${key}`} type={key === 'email' ? 'email' : 'text'} maxLength={maxLength} required={required} value={draft[key] ?? ''} onChange={(event) => change(key, event.target.value)} />
        </div>)}
        <div className="field-group"><label htmlFor="profile-years">Years of Experience</label><input id="profile-years" type="number" min="0" max="80" step="1" value={draft.years_experience ?? ''} onChange={(event) => change('years_experience', event.target.value === '' ? null : Number(event.target.value))} /></div>
        <div className="field-group"><label htmlFor="profile-role">Role</label><input id="profile-role" readOnly value={roles[draft.role] || draft.role} /><small>Assigned by your administrator.</small></div>
      </div></div>
      <div className="settings-section field-group"><label htmlFor="profile-bio">Professional Bio</label><textarea id="profile-bio" rows={5} maxLength={5000} value={draft.professional_bio ?? ''} onChange={(event) => change('professional_bio', event.target.value)} /><small>{(draft.professional_bio || '').length}/5000</small></div>
      <div className="form-actions"><button type="button" className="secondary-button" onClick={() => { setDraft(saved); setError(''); setNotice(''); }}>Cancel</button><button type="submit" className="primary-button">{saving ? 'Saving…' : reading ? 'Reading photo…' : 'Save Changes'}</button></div>
    </fieldset>
  </form>;
}
