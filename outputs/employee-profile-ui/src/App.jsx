import React, { useEffect, useState } from 'react'
import { Navigate, Route, Routes } from 'react-router-dom'
import { api, AUTH_EXPIRED_EVENT, SESSION_KEY, clearSession, readSession } from './services/api'
import Navbar from './components/Navbar'
import Sidebar from './components/Sidebar'
import Dashboard from './pages/Dashboard'
import Medicines from './pages/Medicines'
import Orders from './pages/Orders'
import StockManagement from './pages/StockManagement'
import ExpiryAlerts from './pages/ExpiryAlerts'
import Suppliers from './pages/Suppliers'
import PurchaseOrders from './pages/PurchaseOrders'
import Transfers from './pages/Transfers'
import Messages from './pages/Messages'
import Machines from './pages/Machines'
import Setting from './pages/Setting'
import Login from './pages/Login'
import 'bootstrap/dist/css/bootstrap.min.css'
import '@fortawesome/fontawesome-free/css/all.min.css'
import './App.css'

function App() {
  const [sidebarOpen, setSidebarOpen] = useState(false)
  const [profile, setProfile] = useState(null)
  const [checking, setChecking] = useState(true)
  const [sessionError, setSessionError] = useState('')
  const [retry, setRetry] = useState(0)
  const authenticated = Boolean(profile)

  useEffect(() => {
    let cancelled = false
    setChecking(true)
    setSessionError('')
    if (!readSession()) {
      clearSession()
      setChecking(false)
      return
    }
    api.get('/auth/me').then(({ data }) => {
      if (!cancelled) setProfile(data)
    }).catch((error) => {
      if (!cancelled && error.response?.status !== 401) {
        setSessionError('Cannot reach the local pharmacy service. Start the backend and retry.')
      }
    }).finally(() => { if (!cancelled) setChecking(false) })
    return () => { cancelled = true }
  }, [retry])

  useEffect(() => {
    const profileUpdated = (event) => setProfile(event.detail)
    window.addEventListener('erp:profile-updated', profileUpdated)
    const expire = () => { setProfile(null); setSessionError('') }
    const changed = (event) => {
      if (event.key === SESSION_KEY || event.key === null) {
        setProfile(null)
        setRetry((value) => value + 1)
      }
    }
    window.addEventListener(AUTH_EXPIRED_EVENT, expire)
    window.addEventListener('storage', changed)
    return () => {
      window.removeEventListener('erp:profile-updated', profileUpdated)
      window.removeEventListener(AUTH_EXPIRED_EVENT, expire)
      window.removeEventListener('storage', changed)
    }
  }, [])

  useEffect(() => {
    if (!profile) return
    const session = readSession()
    const timer = setTimeout(() => {
      clearSession()
      setProfile(null)
    }, session ? Math.max(0, Date.parse(session.expires_at) - Date.now()) : 0)
    return () => clearTimeout(timer)
  }, [profile])

  const handleToggleSidebar = () => {
    setSidebarOpen(!sidebarOpen)
  }

  const handleLogin = (data) => {
    setSessionError('')
    setProfile(data.profile)
  }

  const handleLogout = async () => {
    try {
      await api.post('/auth/logout')
      clearSession()
      setProfile(null)
    } catch (error) {
      if (error.response?.status !== 401) {
        setSessionError('Logout could not reach the local service. Please retry to revoke your session.')
      }
    }
  }

  if (checking) return <main className="login-page"><p role="status">Checking your session…</p></main>
  if (sessionError && !authenticated) return <main className="login-page"><section>
    <p role="alert">{sessionError}</p>
    <button onClick={() => setRetry((value) => value + 1)}>Retry connection</button>
    <button onClick={() => { clearSession(); setSessionError('') }}>Back to sign in</button>
  </section></main>

  if (!authenticated) {
    return (
      <Routes>
        <Route path="/login" element={<Login onLogin={handleLogin} />} />
        <Route path="*" element={<Navigate to="/login" replace />} />
      </Routes>
    )
  }

  return (
    <div className="app">
      <Navbar profile={profile} onToggleSidebar={handleToggleSidebar} onLogout={handleLogout} />
      {sessionError && <p role="alert">{sessionError}</p>}
      <div className="app-body">
        <Sidebar isOpen={sidebarOpen} />
        <main className="main-content">
          <Routes>
            <Route path="/" element={<Navigate to="/dashboard" replace />} />
            <Route path="/login" element={<Navigate to="/dashboard" replace />} />
            <Route path="/dashboard" element={<Dashboard />} />
            <Route path="/medicines" element={<Medicines />} />
            <Route path="/orders" element={<Orders />} />
            <Route path="/stock-management" element={<StockManagement />} />
            <Route path="/expiry-alerts" element={<ExpiryAlerts />} />
            <Route path="/suppliers" element={<Suppliers />} />
            <Route path="/purchase-orders" element={<PurchaseOrders />} />
            <Route path="/transfers" element={<Transfers />} />
            <Route path="/machines" element={<Machines />} />
            <Route path="/messages" element={<Messages />} />
            <Route path="/settings" element={<Navigate to="/settings/profile" replace />} />
            <Route path="/settings/profile" element={<Setting onLogout={handleLogout} />} />
            <Route path="/settings/password" element={<Setting onLogout={handleLogout} />} />
            <Route path="/settings/prescription-preferences" element={<Setting onLogout={handleLogout} />} />
            <Route path="/settings/inventory-preferences" element={<Setting onLogout={handleLogout} />} />
            <Route path="/inventory-preferences" element={<Setting onLogout={handleLogout} />} />
            <Route path="/settings/printer" element={<Setting onLogout={handleLogout} />} />
            <Route path="/settings/notifications" element={<Setting onLogout={handleLogout} />} />
            <Route path="/settings/security" element={<Setting onLogout={handleLogout} />} />
          </Routes>
        </main> 
      </div>
    </div>
  )
}

export default App
