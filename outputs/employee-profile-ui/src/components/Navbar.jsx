import { useEffect, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import "../styles/Navbar.css";

const Navbar = ({ profile, onToggleSidebar, onLogout }) => {
  const navigate = useNavigate();
  const [profileMenuOpen, setProfileMenuOpen] = useState(false);
  const [notificationsEnabled, setNotificationsEnabled] = useState(true);
  const [darkMode, setDarkMode] = useState(() => localStorage.getItem("theme") === "dark");
  const profileMenuRef = useRef(null);
  useEffect(() => {
    document.body.classList.toggle("dark-mode", darkMode);
    localStorage.setItem("theme", darkMode ? "dark" : "light");
  }, [darkMode]);
  useEffect(() => {
    const closeMenu = (event) => {
      if (profileMenuRef.current && !profileMenuRef.current.contains(event.target)) setProfileMenuOpen(false);
    };
    document.addEventListener("mousedown", closeMenu);
    return () => document.removeEventListener("mousedown", closeMenu);
  }, []);
  const logout = () => { onLogout?.(); };
  return <nav className="navbar-top"><div className="navbar-content">
    <button type="button" className="navbar-toggle" onClick={onToggleSidebar} aria-label="Toggle navigation"><i className="fas fa-bars" /></button>
    <div className="navbar-actions">
      <button type="button" className="ai-assistance-btn">AI Assistance <i className="fa-solid fa-sparkles" /></button>
      <button type="button" className="navbar-action-btn" onClick={() => navigate("/settings")} aria-label="Settings"><i className="fas fa-cog" /></button>
      <button type="button" className="navbar-action-btn" onClick={() => setDarkMode((enabled) => !enabled)} aria-label={darkMode ? "Switch to light mode" : "Switch to dark mode"}><i className={`fas fa-${darkMode ? "sun" : "moon"}`} /></button>
      <button type="button" className="navbar-action-btn notification-btn" aria-label="Notifications"><i className="fas fa-bell" />{notificationsEnabled && <span className="notification-badge">1</span>}</button>
      <div className="profile-menu-wrap" ref={profileMenuRef}><button type="button" className="navbar-profile" onClick={() => setProfileMenuOpen((open) => !open)} aria-label="Open profile menu" aria-expanded={profileMenuOpen}><span className="profile-avatar" style={{ display: "grid", placeItems: "center", overflow: "hidden" }}>{profile?.photo_data_url ? <img src={profile.photo_data_url} alt="Your profile" style={{ width: "100%", height: "100%", objectFit: "cover" }} /> : <i className="fa-solid fa-user" />}</span><span className="profile-status" /></button>
      {profileMenuOpen && <div className="profile-dropdown"><div className="profile-dropdown-user"><strong>{profile?.first_name} {profile?.last_name}</strong><span>{profile?.email}</span></div><button type="button" onClick={() => { setProfileMenuOpen(false); navigate("/settings"); }}><i className="fa-regular fa-user" /> Profile Settings</button><button type="button" onClick={() => setNotificationsEnabled((enabled) => !enabled)}><i className="fa-regular fa-bell" /> Notifications <span className={`preference-state ${notificationsEnabled ? "enabled" : "disabled"}`}>{notificationsEnabled ? "On" : "Off"}</span></button><div className="profile-dropdown-divider" /><button type="button" className="logout-option" onClick={logout}><i className="fa-solid fa-arrow-right-from-bracket" /> Logout</button></div>}</div>
    </div>
  </div></nav>;
};
export default Navbar;
