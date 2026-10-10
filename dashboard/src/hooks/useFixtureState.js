import { useEffect, useState } from 'react';
import { loadFixture } from '../fixtures.js';
export default function useFixtureState(selection) {
  const [snapshot, setSnapshot] = useState({ state: {}, status: 'loading', error: '', received: null });
  useEffect(() => {
    let disposed = false;
    loadFixture(selection).then(state => { if (!disposed) setSnapshot({ state, status: 'fixture', error: '', received: null }); })
      .catch(error => { if (!disposed) setSnapshot({ state: {}, status: 'malformed', error: error.message, received: null }); });
    return () => { disposed = true; };
  }, [selection]);
  return { ...snapshot, source: 'fixture', fixtureName: selection.name };
}
