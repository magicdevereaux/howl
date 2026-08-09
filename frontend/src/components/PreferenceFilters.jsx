import React, { useState } from 'react';

const filterSel = {
  width: '100%', padding: '8px 10px', border: 'none',
  borderRadius: '8px', fontSize: '13px', background: 'rgba(255,255,255,0.08)',
  color: 'var(--text-primary)', cursor: 'pointer', outline: 'none',
};
const filterInput = {
  width: '100%', padding: '8px 10px', border: 'none',
  borderRadius: '8px', fontSize: '13px', background: 'rgba(255,255,255,0.08)',
  color: 'var(--text-primary)', outline: 'none', boxSizing: 'border-box',
};

const EMPTY = { lookingFor: '', gender: '', sexuality: '', agePrefMin: '', agePrefMax: '' };

/**
 * The discover preference panel, and the reason it is its own component.
 *
 * It holds *draft* filter values: you change three dropdowns and then press
 * Apply. The saved values live on the user's profile, so the draft has to be
 * seeded from them — and the old implementation seeded it with an effect:
 *
 *     useEffect(() => { if (preferenceFilters) setLocalFilters(preferenceFilters); },
 *               [preferenceFilters?.lookingFor, preferenceFilters?.gender, …]);
 *
 * ESLint flagged the missing `preferenceFilters` dependency, and it must not be
 * added. The prop was a fresh object literal built in App's render, so a new
 * identity arrived on *every* render: depending on it would call setLocalFilters,
 * which re-renders, which mints another object, forever. Listing the five fields
 * individually was a workaround for that, not a fix — and the linter's suggested
 * useReducer would not have helped either, since the churn is in the source of
 * the value, not in how the update is applied.
 *
 * The fix is to stop syncing. Seeding state from a prop is what a remount does,
 * so the parent passes a `key` derived from the saved values and React discards
 * this component when they change. No effect, no dependency array, no loop.
 */
export default function PreferenceFilters({ initial = EMPTY, onApply }) {
  const [draft, setDraft] = useState({ ...EMPTY, ...initial });

  const active = !!(
    draft.lookingFor || draft.gender || draft.sexuality || draft.agePrefMin || draft.agePrefMax
  );

  const set = (key) => (e) => setDraft((f) => ({ ...f, [key]: e.target.value }));

  const handleClear = () => {
    setDraft(EMPTY);
    onApply(EMPTY);
  };

  return (
    <div style={{ background: 'rgba(0,0,0,0.3)', borderRadius: '14px', padding: '14px 16px', marginBottom: '18px' }}>
      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr 1fr', gap: '8px', marginBottom: '8px' }}>
        <div>
          <p style={{ color: 'var(--text-disabled)', fontSize: '10px', fontWeight: '600', textTransform: 'uppercase', letterSpacing: '0.05em', margin: '0 0 4px' }}>Looking for</p>
          <select value={draft.lookingFor} onChange={set('lookingFor')} style={filterSel} aria-label="Looking for">
            <option value="" style={{ background: '#1A1035' }}>Anyone</option>
            <option value="men" style={{ background: '#1A1035' }}>Men</option>
            <option value="women" style={{ background: '#1A1035' }}>Women</option>
            <option value="non-binary" style={{ background: '#1A1035' }}>Non-binary</option>
            <option value="everyone" style={{ background: '#1A1035' }}>Everyone</option>
          </select>
        </div>
        <div>
          <p style={{ color: 'var(--text-disabled)', fontSize: '10px', fontWeight: '600', textTransform: 'uppercase', letterSpacing: '0.05em', margin: '0 0 4px' }}>Gender</p>
          <select value={draft.gender} onChange={set('gender')} style={filterSel} aria-label="Gender">
            <option value="" style={{ background: '#1A1035' }}>Any</option>
            <option value="man" style={{ background: '#1A1035' }}>Man</option>
            <option value="woman" style={{ background: '#1A1035' }}>Woman</option>
            <option value="non-binary" style={{ background: '#1A1035' }}>Non-binary</option>
            <option value="other" style={{ background: '#1A1035' }}>Other</option>
          </select>
        </div>
        <div>
          <p style={{ color: 'var(--text-disabled)', fontSize: '10px', fontWeight: '600', textTransform: 'uppercase', letterSpacing: '0.05em', margin: '0 0 4px' }}>Sexuality</p>
          <select value={draft.sexuality} onChange={set('sexuality')} style={filterSel} aria-label="Sexuality">
            <option value="" style={{ background: '#1A1035' }}>Any</option>
            <option value="straight" style={{ background: '#1A1035' }}>Straight</option>
            <option value="gay" style={{ background: '#1A1035' }}>Gay</option>
            <option value="lesbian" style={{ background: '#1A1035' }}>Lesbian</option>
            <option value="bisexual" style={{ background: '#1A1035' }}>Bisexual</option>
            <option value="pansexual" style={{ background: '#1A1035' }}>Pansexual</option>
            <option value="other" style={{ background: '#1A1035' }}>Other</option>
          </select>
        </div>
      </div>
      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr 1fr', gap: '8px', marginBottom: '12px' }}>
        <div>
          <p style={{ color: 'var(--text-disabled)', fontSize: '10px', fontWeight: '600', textTransform: 'uppercase', letterSpacing: '0.05em', margin: '0 0 4px' }}>Min age</p>
          <input type="number" value={draft.agePrefMin} onChange={set('agePrefMin')} placeholder="18" min={18} max={120} style={filterInput} aria-label="Minimum age" />
        </div>
        <div>
          <p style={{ color: 'var(--text-disabled)', fontSize: '10px', fontWeight: '600', textTransform: 'uppercase', letterSpacing: '0.05em', margin: '0 0 4px' }}>Max age</p>
          <input type="number" value={draft.agePrefMax} onChange={set('agePrefMax')} placeholder="99" min={18} max={120} style={filterInput} aria-label="Maximum age" />
        </div>
        <div style={{ display: 'flex', flexDirection: 'column', justifyContent: 'flex-end', gap: '6px' }}>
          <button
            onClick={() => onApply(draft)}
            style={{ padding: '8px 0', background: 'var(--accent)', color: 'white', border: 'none', borderRadius: '8px', fontSize: '13px', fontWeight: '700', cursor: 'pointer', width: '100%' }}
          >
            Apply
          </button>
          <button
            onClick={handleClear}
            style={{ padding: '4px 0', background: 'none', color: 'var(--text-disabled)', border: 'none', fontSize: '11px', cursor: 'pointer', textDecoration: 'underline', visibility: active ? 'visible' : 'hidden' }}
          >
            Clear all
          </button>
        </div>
      </div>
      {active && (
        <p style={{ color: 'var(--text-disabled)', fontSize: '11px', margin: 0, textAlign: 'center' }}>
          Filters active — results are narrowed to your preferences
        </p>
      )}
    </div>
  );
}
