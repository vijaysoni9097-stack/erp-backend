import { useRef, useState } from 'react';
import { api } from '../services/api';

export default function ReceiveStock({ onReceived }) {
  const dialog = useRef(null);
  const lock = useRef(false);
  const request = useRef(null);
  const [orders, setOrders] = useState([]);
  const [order, setOrder] = useState(null);
  const [quantities, setQuantities] = useState({});
  const [closeOrder, setCloseOrder] = useState(false);
  const [busy, setBusy] = useState(false);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const [uncertain, setUncertain] = useState(false);
  async function load() {
    setLoading(true); setError('');
    try { const { data } = await api.get('/purchase-orders/pending-receipt'); setOrders(data); }
    catch { setError('Could not load pending orders. Please retry.'); }
    finally { setLoading(false); }
  }
  function open() {
    setOrder(null); setUncertain(false); request.current = null;
    dialog.current.showModal(); load();
  }
  function selectOrder(value) {
    const selected = orders.find(item => item.id === Number(value));
    setOrder(selected || null); setCloseOrder(false); setError(''); request.current = null;
    setQuantities(Object.fromEntries((selected?.items || []).map(item => [item.id, String(item.remaining_quantity)])));
  }
  async function submit(event) {
    event.preventDefault();
    if (lock.current || !order) return;
    const items = order.items.map(item => ({ order_item_id: item.id, quantity: Number(quantities[item.id]) }));
    if (items.some(item => !Number.isInteger(item.quantity) || item.quantity < 0 || item.quantity > 2147483647) || !items.some(item => item.quantity > 0)) {
      setError('Enter whole quantities of zero or more, with at least one unit received.'); return;
    }
    request.current ||= { request_id: crypto.randomUUID(), items, close_order: closeOrder };
    lock.current = true; setBusy(true); setError('');
    try {
      await api.post(`/purchase-orders/${order.id}/receipts`, request.current);
      dialog.current.close(); onReceived(`Stock received against PO #${order.id}. Medicine quantities updated.`);
    } catch (err) {
      const detail = err.response?.data?.detail;
      setUncertain(true);
      setError(typeof detail === 'string' ? detail : 'Receipt could not be confirmed. Retry the same receipt safely, or close and refresh before starting another.');
    } finally { lock.current = false; setBusy(false); }
  }
  return <><button className="primary-btn" onClick={open}>+ Add Stock</button>
    <dialog ref={dialog} className="stock-adjust-dialog" aria-labelledby="receive-stock-title" onCancel={event => { if (lock.current) event.preventDefault(); }}>
      <form onSubmit={submit}><h2 id="receive-stock-title">Add Stock from Purchase Order</h2>
        {loading ? <p role="status">Loading pending orders…</p> : <label>Pending purchase order<select value={order?.id || ''} disabled={busy || uncertain} onChange={event => selectOrder(event.target.value)}><option value="">Select a PO</option>{orders.map(item => <option key={item.id} value={item.id}>PO #{item.id} · {item.supplier_name}</option>)}</select></label>}
        {!loading && !orders.length && !error && <p>No purchase orders are pending receipt.</p>}
        {order && <><p>Enter quantities received in this delivery. Use zero for undelivered items.</p><div style={{ overflowX: 'auto' }}><table className="inventory-table"><thead><tr><th>Medicine / batch</th><th>Ordered</th><th>Already received</th><th>Receive now</th></tr></thead><tbody>{order.items.map(item => <tr key={item.id}><td>{item.medicine_name}<small style={{ display: 'block' }}>{item.sku} · {item.batch_number}</small></td><td>{item.quantity}</td><td>{item.received_quantity}</td><td><input aria-label={`Receive ${item.medicine_name}`} type="number" min="0" max="2147483647" step="1" required value={quantities[item.id] ?? ''} disabled={busy || uncertain} onChange={event => { request.current = null; setQuantities(previous => ({ ...previous, [item.id]: event.target.value })); }} /></td></tr>)}</tbody></table></div><label><input type="checkbox" checked={closeOrder} disabled={busy || uncertain} onChange={event => { request.current = null; setCloseOrder(event.target.checked); }} /> Final delivery — close any remaining quantities</label></>}
        {error && <p role="alert">{error}</p>}
        {!order && error && <button type="button" onClick={load} disabled={loading}>Retry loading</button>}
        <div className="stock-adjust-actions"><button type="button" className="secondary-btn" disabled={busy} onClick={() => dialog.current.close()}>Cancel</button><button type="submit" className="primary-btn" disabled={busy || loading || !order}>{busy ? 'Adding…' : uncertain ? 'Retry same receipt' : 'Add Stock'}</button></div>
      </form>
    </dialog></>;
}
