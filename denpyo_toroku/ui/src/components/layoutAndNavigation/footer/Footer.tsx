/**
 * Footer component - Reference AgentStudio layout pattern
 * Copyright center + links row, spans full grid width (span3)
 */
import { h } from 'preact';
import { FooterLink } from '../../../types/appTypes';

const footerLinks: FooterLink[] = [
  { name: 'About Oracle', linkId: 'aboutOracle', linkTarget: 'http://www.oracle.com/us/corporate/index.html#menu-about' },
  { name: 'Contact Us', linkId: 'contactUs', linkTarget: 'http://www.oracle.com/us/corporate/contact/index.html' },
  { name: 'Terms Of Use', linkId: 'termsOfUse', linkTarget: 'http://www.oracle.com/us/legal/terms/index.html' },
  { name: 'Your Privacy Rights', linkId: 'yourPrivacyRights', linkTarget: 'http://www.oracle.com/us/legal/privacy/index.html' }
];

export function Footer() {
  return (
    <footer id="aaiFooter" role="contentinfo" class="aaiLayout--item aaiLayout--item__span3">
      <div class="aaiFooter--copy">
        Copyright &copy; 2026 Oracle and/or its affiliates. All rights reserved.
      </div>
      <div class="aaiFooter--links">
        {footerLinks.map(link => (
          <a
            key={link.linkId}
            id={link.linkId}
            href={link.linkTarget}
            target="_blank"
            rel="noopener noreferrer"
          >
            {link.name}
          </a>
        ))}
      </div>
    </footer>
  );
}
