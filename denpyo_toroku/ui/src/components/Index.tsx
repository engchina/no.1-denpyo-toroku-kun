/**
 * Index.tsx - Application entry point
 * Renders the Preact VDOM app into the <app-root> custom element
 */
import { h, render } from 'preact';
import { App } from './App';

const rootElement = document.getElementById('appRoot');
if (rootElement) {
  render(<App />, rootElement);
}
