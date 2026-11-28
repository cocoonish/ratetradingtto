// DV01 Risk's "Hedge'i işle" (the desk, 28.11.2026: A3 - "DV01 Risk'in hedge önerisini tek tıkla işle"): the hedge
// recommender's suggestion of the user's own position into Günlük İşlemler's "Excel'den yapıştır" on OIS - a line an
// active instrument with a side and a rounded nominal (an outright by its tenor, a forward start as an OIS between its two
// dates), at the curve's rate.  The server writes the paste (/api/dv01/hedge, tto/varrisk.py ``hedge_paste``); the dialog's
// preview and "N satırı kaydet" are its own (blotterentry.js ``openBulk``).  Nothing is saved before that.
import { api } from './api.js';
import { toast, errorToast } from './ui.js';
import { openBulk } from './pages/blotterentry.js';
import { pendingWrites } from './grid.js';

/** Open the paste dialog with the hedge's rows (the inputs typed just now counted first). */
export async function bookHedge(ctx) {
  try { await pendingWrites(); } catch (e) { /* the server reads what it has */ }
  let src;
  try { src = await api.get('/api/dv01/hedge'); } catch (err) { errorToast(err); return null; }
  if (!src.taken) { toast(src.said, 'warn', 7000); return null; }
  return openBulk({ ctx }, { kind: src.kind, text: src.text, said: src.said, title: 'DV01 Risk hedge önerisi → işlem girişi' });
}
