import React from 'react';
import EmployeeProfile from './EmployeeProfile';
import { Navigate, useLocation, useNavigate } from 'react-router-dom';
import '../styles/Settings.css';

const settingsTabs = [
  { key: 'profile', label: 'Profile Settings', path: '/settings/profile', icon: 'fa-user-gear' },
  { key: 'password', label: 'Change Password', path: '/settings/password', icon: 'fa-lock' },
  { key: 'prescription', label: 'Prescription Preferences', path: '/settings/prescription-preferences', icon: 'fa-prescription' },
  { key: 'inventory', label: 'Inventory Preferences', path: '/settings/inventory-preferences', icon: 'fa-boxes-stacked', paths: ['/inventory-preferences', '/settings/inventory-preferences'] },
  { key: 'printer', label: 'Printer Settings', path: '/settings/printer', icon: 'fa-print' },
  { key: 'notifications', label: 'Notifications', path: '/settings/notifications', icon: 'fa-bell' },
  { key: 'security', label: 'Security', path: '/settings/security', icon: 'fa-shield-halved' },
];

const renderToggleRow = (title, description, checked = true) => (
  <div className="switch-item" key={title}>
    <div className="switch-copy">
      <strong>{title}</strong>
      <span>{description}</span>
    </div>
    <label className="switch" aria-label={title}>
      <input type="checkbox" defaultChecked={checked} />
      <span className="slider" />
    </label>
  </div>
);

function renderSection(activeKey) {
  switch (activeKey) {
    case 'password':
      return (
        <>
          <h2>Change Password</h2>
          <div className="settings-section">
            <div className="settings-row">
              <div className="field-group">
                <label htmlFor="current-password">Current Password</label>
                <input id="current-password" type="password" placeholder="Enter current password" />
              </div>
              <div />
              <div className="field-group">
                <label htmlFor="new-password">New Password</label>
                <input id="new-password" type="password" placeholder="Create a new password" />
              </div>
              <div className="field-group">
                <label htmlFor="confirm-password">Confirm Password</label>
                <input id="confirm-password" type="password" placeholder="Repeat your new password" />
              </div>
            </div>
          </div>

          <div className="settings-section">
            <div className="settings-badges">
              <span className="badge-item">8+ Characters</span>
              <span className="badge-item">Uppercase & lowercase</span>
              <span className="badge-item">At least 1 number</span>
            </div>
          </div>

          <div className="form-actions">
            <button type="button" className="secondary-button">Cancel</button>
            <button type="button" className="primary-button">Update Password</button>
          </div>
        </>
      );

    case 'prescription':
      return (
        <>
          <h2>Prescription Preferences</h2>
          <div className="settings-section">
            <div className="settings-row">
              <div className="field-group">
                <label htmlFor="default-duration">Default Prescription Duration</label>
                <select id="default-duration">
                  <option>7 Days</option>
                  <option>14 Days</option>
                  <option selected>30 Days</option>
                  <option>60 Days</option>
                  <option>90 Days</option>
                </select>
              </div>
              <div className="field-group">
                <label htmlFor="refill-lead">Default Refill Reminder Lead Time</label>
                <select id="refill-lead">
                  <option>3 Days before expiry</option>
                  <option selected>5 Days before expiry</option>
                  <option>7 Days before expiry</option>
                </select>
              </div>
              <div className="field-group">
                <label htmlFor="instructions">Default Medication Instructions</label>
                <input id="instructions" type="text" defaultValue="Take after meals" />
              </div>
              <div className="field-group">
                <label htmlFor="note-template">Note Template</label>
                <input id="note-template" type="text" defaultValue="Follow-up after 7 days" />
              </div>
            </div>
          </div>

          <div className="settings-section">
            <div className="switch-panel">
              {renderToggleRow('Auto-Refill Reminders', 'Send reminder alerts before prescriptions expire.', true)}
              {renderToggleRow('Patient Copy Included', 'Attach a patient copy automatically on printed prescriptions.', true)}
              {renderToggleRow('Tracking Number on Label', 'Include prescription tracking IDs for follow-up', false)}
            </div>
          </div>

          <div className="form-actions">
            <button type="button" className="secondary-button">Reset</button>
            <button type="button" className="primary-button">Save Changes</button>
          </div>
        </>
      );

    case 'inventory':
      return (
        <>
          <h2>Inventory Preferences</h2>
          <div className="settings-section">
            <div className="settings-row">
              <div className="field-group">
                <label htmlFor="low-stock">Low Stock Threshold</label>
                <input id="low-stock" type="text" defaultValue="20%" />
              </div>
              <div className="field-group">
                <label htmlFor="alert-window">Expiry Alert Window</label>
                <input id="alert-window" type="text" defaultValue="90 days" />
              </div>
              <div className="field-group">
                <label htmlFor="vendor-lead">Vendor Lead Time</label>
                <input id="vendor-lead" type="text" defaultValue="5 days" />
              </div>
              <div className="field-group">
                <label htmlFor="restock-schedule">Reorder Schedule</label>
                <select id="restock-schedule">
                  <option>Every Monday</option>
                  <option selected>Every Wednesday</option>
                  <option>Every Friday</option>
                </select>
              </div>
            </div>
          </div>

          <div className="settings-section">
            <div className="switch-panel">
              {renderToggleRow('Auto-reorder suggestions', 'Generate reorder suggestions when stock reaches threshold.', true)}
              {renderToggleRow('Supplier expiry follow-up', 'Notify suppliers about near-expiry batch statuses.', true)}
              {renderToggleRow('Daily stock summary', 'Send daily stock summary email to pharmacy lead.', false)}
            </div>
          </div>

          <div className="form-actions">
            <button type="button" className="secondary-button">Cancel</button>
            <button type="button" className="primary-button">Update Preferences</button>
          </div>
        </>
      );

    case 'printer':
      return (
        <>
          <h2>Printer Settings</h2>
          <div className="settings-section">
            <div className="settings-row">
              <div className="field-group">
                <label htmlFor="printer-name">Default Printer</label>
                <select id="printer-name">
                  <option selected>HP LaserJet Pro MFP</option>
                  <option>Brother DCP-L2540DW</option>
                  <option>Epson TM-T88V</option>
                </select>
              </div>
              <div className="field-group">
                <label htmlFor="paper-size">Paper Size</label>
                <select id="paper-size">
                  <option selected>A4</option>
                  <option>Letter</option>
                  <option>Prescription Slip</option>
                </select>
              </div>
              <div className="field-group">
                <label htmlFor="copies">Copies</label>
                <input id="copies" type="number" defaultValue="2" />
              </div>
              <div className="field-group">
                <label htmlFor="orientation">Print Orientation</label>
                <select id="orientation">
                  <option selected>Portrait</option>
                  <option>Landscape</option>
                </select>
              </div>
            </div>
          </div>

          <div className="settings-section">
            <div className="switch-panel">
              {renderToggleRow('Auto-print prescription copies', 'Print a duplicate after prescription finalization.', true)}
              {renderToggleRow('Print invoice summary', 'Include invoice summary on printed order slips.', true)}
              {renderToggleRow('Secure print', 'Require PIN to release print jobs from the printer.', false)}
            </div>
          </div>

          <div className="form-actions">
            <button type="button" className="secondary-button">Test Print</button>
            <button type="button" className="primary-button">Save Settings</button>
          </div>
        </>
      );

    case 'notifications':
      return (
        <>
          <h2>Notifications</h2>
          <div className="settings-section">
            <div className="switch-panel">
              {renderToggleRow('New Appointment Booking', 'Alert when a new appointment is booked.', true)}
              {renderToggleRow('Prescription Reminders', 'Send refill and follow-up reminder notifications.', true)}
              {renderToggleRow('Inventory Alerts', 'Notify when stock reaches critical threshold.', true)}
              {renderToggleRow('System Maintenance', 'Receive updates about scheduled downtime or maintenance.', false)}
            </div>
          </div>

          <div className="settings-section">
            <div className="settings-row">
              <div className="field-group">
                <label htmlFor="notification-email">Notification Email</label>
                <input id="notification-email" type="email" defaultValue="pharmacist@preclinic.com" />
              </div>
              <div className="field-group">
                <label htmlFor="notification-sms">SMS Number</label>
                <input id="notification-sms" type="text" defaultValue="+1 (555) 123-4567" />
              </div>
            </div>
          </div>

          <div className="form-actions">
            <button type="button" className="secondary-button">Reset</button>
            <button type="button" className="primary-button">Save Preferences</button>
          </div>
        </>
      );

    case 'security':
      return (
        <>
          <h2>Security</h2>
          <div className="settings-section">
            <div className="switch-panel">
              {renderToggleRow('Two-Factor Authentication', 'Require a one-time code during login.', true)}
              {renderToggleRow('Session Timeout', 'Log out inactive users after 15 minutes.', true)}
              {renderToggleRow('Login Alerts', 'Send email if a new device signs in.', true)}
              {renderToggleRow('Biometric sign-in', 'Allow fingerprint or face unlock on trusted devices.', false)}
            </div>
          </div>

          <div className="settings-section">
            <div className="settings-row">
              <div className="field-group">
                <label htmlFor="session-timeout">Session Timeout</label>
                <select id="session-timeout">
                  <option>5 minutes</option>
                  <option selected>15 minutes</option>
                  <option>30 minutes</option>
                  <option>1 hour</option>
                </select>
              </div>
              <div className="field-group">
                <label htmlFor="api-key">API Access Key</label>
                <input id="api-key" type="text" defaultValue="pk_live_5f883b42a9" />
              </div>
            </div>
          </div>

          <div className="form-actions">
            <button type="button" className="secondary-button">Revoke All Sessions</button>
            <button type="button" className="primary-button">Save Security Settings</button>
          </div>
        </>
      );

    case 'profile':
    default:
      return <EmployeeProfile />;
  }
}

function Setting({ onLogout }) {
  const location = useLocation();
  const navigate = useNavigate();

  const normalizedPath = location.pathname.replace(/\/+$/, '');
  const activeTab = settingsTabs.find((tab) => (tab.paths ? tab.paths.includes(normalizedPath) : tab.path === normalizedPath)) || settingsTabs[0];

  if (normalizedPath === '/settings') {
    return <Navigate to="/settings/profile" replace />;
  }

  return (
    <div className="settings-page">
      <div className="settings-header">
        <h1>Settings</h1>
      </div>

      <div className="settings-card">
        <aside className="settings-sidebar">
          {settingsTabs.map((tab) => (
            <button
              key={tab.key}
              type="button"
              className={`settings-nav-button ${activeTab.key === tab.key ? 'active' : ''}`}
              onClick={() => navigate(tab.paths ? tab.paths[0] : tab.path)}
            >
              <i className={`fa-solid ${tab.icon}`} />
              {tab.label}
            </button>
          ))}

          <button type="button" className="settings-logout" onClick={onLogout}>
            <i className="fa-solid fa-right-from-bracket" />
            Log Out
          </button>
        </aside>

        <div className="settings-content">
          <div className="settings-panel">
            {renderSection(activeTab.key)}
          </div>
        </div>
      </div>
    </div>
  );
}

export default Setting;
