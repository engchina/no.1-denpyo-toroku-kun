/**
 * Header component - Reference AgentStudio layout pattern
 * Brand icon + application title + user menu
 * Spans full grid width (span3)
 */
import { useState, useCallback, useEffect } from 'preact/hooks';
import { useAppDispatch, useAppSelector } from '../../../redux/store';
import { MenuButton } from '@oracle/oraclejet-preact/UNSAFE_MenuButton';
import { MenuItem } from '@oracle/oraclejet-preact/UNSAFE_Menu';
import { Button } from '@oracle/oraclejet-preact/UNSAFE_Button';
import { HelpCircle, Info, LogOut } from 'lucide-react';
import { setAuthenticated } from '../../../redux/slices/applicationSlice';
import { apiGet } from '../../../utils/apiUtils';
import brandIconUrl from '../../../styles/images/denpyn_login_avatar_no_bg.png';

const HELP_DOC_URL = 'https://docs.oracle.com/en/database/oracle/';
const ABOUT_TITLE = 'お任せ！伝ぴょん';

export function Header() {
  const dispatch = useAppDispatch();
  const userName = useAppSelector(state => state.application.userName);
  const [isMenuOpen, setIsMenuOpen] = useState(false);
  const [isAboutOpen, setIsAboutOpen] = useState(false);
  const [aboutVersion, setAboutVersion] = useState<string>('-');
  const [aboutStatus, setAboutStatus] = useState<string>('-');

  const handleMenuToggle = useCallback(() => {
    setIsMenuOpen(prev => !prev);
  }, []);

  const loadAboutInfo = useCallback(async () => {
    try {
      const info = await apiGet<{ version?: string; status?: string }>('/api/v1/version');
      setAboutVersion(info.version || '-');
      setAboutStatus(info.status || '-');
    } catch {
      setAboutVersion('-');
      setAboutStatus('unavailable');
    }
  }, []);

  useEffect(() => {
    if (!isAboutOpen) {
      return;
    }
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') {
        setIsAboutOpen(false);
      }
    };
    window.addEventListener('keydown', onKeyDown);
    return () => window.removeEventListener('keydown', onKeyDown);
  }, [isAboutOpen]);

  const handleMenuAction = useCallback(async (action: string) => {
    setIsMenuOpen(false);
    switch (action) {
      case 'help':
        window.open(HELP_DOC_URL, '_blank', 'noopener,noreferrer');
        break;
      case 'about':
        setIsAboutOpen(true);
        loadAboutInfo();
        break;
      case 'signout':
        try {
          await fetch('/studio/logout', {
            method: 'POST',
            credentials: 'same-origin'
          });
        } finally {
          dispatch(setAuthenticated(false));
        }
        break;
    }
  }, [dispatch, loadAboutInfo]);

  return (
    <>
      <header role="banner" id="aaiHeader" class="aaiLayout--item aaiLayout--item__span3">
        <div class="oj-flex-bar oj-sm-align-items-center" style={{ marginLeft: '1vw' }}>
          <div
            aria-label="お任せ！伝ぴょん"
            aria-readonly="true"
            tabIndex={0}
            class="oj-flex-bar-middle oj-sm-align-items-center"
          >
            <img
              class="app-brand-icon"
              src={brandIconUrl}
              alt=""
              aria-hidden="true"
            />
            <h1
              title="お任せ！伝ぴょん"
              aria-hidden="true"
              class="oj-sm-only-hide oj-web-applayout-header-title"
            >
              お任せ！伝ぴょん
            </h1>
          </div>
        </div>
        <div class="oj-flex-bar-end" style={{ marginRight: '1vw' }}>
          <MenuButton
            label={userName}
            variant="borderless"
            isMenuOpen={isMenuOpen}
            onToggleMenu={handleMenuToggle}
          >
            <MenuItem
              label="Help"
              startIcon={<span class="ics-btn-icon ics-btn-icon--md"><HelpCircle size={16} /></span>}
              onAction={() => handleMenuAction('help')}
            />
            <MenuItem
              label="About"
              startIcon={<span class="ics-btn-icon ics-btn-icon--md"><Info size={16} /></span>}
              onAction={() => handleMenuAction('about')}
            />
            <MenuItem
              label="Sign Out"
              startIcon={<span class="ics-btn-icon ics-btn-icon--md"><LogOut size={16} /></span>}
              onAction={() => handleMenuAction('signout')}
            />
          </MenuButton>
        </div>
      </header>

      {isAboutOpen && (
        <div class="aaiModalOverlay" role="presentation" onClick={() => setIsAboutOpen(false)}>
          <div
            class="aaiAboutModal"
            role="dialog"
            aria-modal="true"
            aria-label="About"
            onClick={event => event.stopPropagation()}
          >
            <h2 class="aaiAboutModal__title">{ABOUT_TITLE}</h2>
            <p class="aaiAboutModal__line">Version: {aboutVersion}</p>
            <p class="aaiAboutModal__line">Status: {aboutStatus}</p>
            <p class="aaiAboutModal__line">Copyright &copy; 2026 Oracle and/or its affiliates.</p>
            <div class="aaiAboutModal__actions">
              <Button label="Close" size="sm" onAction={() => setIsAboutOpen(false)} />
            </div>
          </div>
        </div>
      )}
    </>
  );
}
