"""
CUIC Authentication
===================
Login and logout methods for CUIC.
"""

from . import selectors


def login(worker) -> bool:
    """Login to CUIC (2-stage: username → password + LDAP)."""
    try:
        worker.page.goto(worker.url, wait_until='domcontentloaded', timeout=worker.timeout_nav)
        worker.page.wait_for_timeout(worker.timeout_short)

        # Stage 1: username → Next
        worker.page.wait_for_selector(selectors.USERNAME_XPATH, timeout=worker.timeout_nav)
        worker.page.fill(selectors.USERNAME_XPATH, worker.username)
        worker.page.click(selectors.NEXT_BTN_XPATH)
        worker.page.wait_for_load_state('domcontentloaded')
        worker.page.wait_for_timeout(worker.timeout_short)

        # Stage 2: password + LDAP → Sign In
        worker.page.wait_for_selector(selectors.PASSWORD_XPATH, timeout=worker.timeout_nav)
        worker.page.fill(selectors.PASSWORD_XPATH, worker.password)
        worker.page.select_option(selectors.DOMAIN_SELECT_XPATH, value="LDAP")
        worker.page.click(selectors.SIGN_IN_BTN_XPATH)

        worker.page.wait_for_selector(selectors.REPORTS_TAB_CSS, timeout=worker.timeout_nav)
        worker.logger.info("Login OK")
        worker.screenshot("01_login_ok")
        return True
    except Exception as e:
        worker.logger.error(f"Login failed: {e}")
        worker.screenshot("login_error", is_step=False)
        return False


def logout(worker) -> bool:
    """Sign out of CUIC so the session is released.
    Logout UI lives in the MAIN page (outside any iframe).

    Strategy: Multiple selectors (ID, class, XPath)
      1. Click user menu button (tries multiple selectors)
      2. Click sign-out link (tries multiple selectors)
      → Navigates to Logout.jsp
    
    Returns: True if logout succeeded, False if manual logout required
    """
    try:
        if not worker.context:
            worker.logger.warning("⚠ No browser context – skipping logout")
            return False

        # Always use the FIRST page (main CUIC tab) for logout
        pages = worker.context.pages
        if not pages:
            worker.logger.warning("⚠ No pages open – skipping logout")
            return False

        # Close all extra tabs/popups first
        worker.logger.info("Closing extra browser tabs...")
        while len(pages) > 1:
            try:
                pages[-1].close()
                worker.logger.info(f"  Closed tab — {len(pages)-1} remaining")
            except Exception:
                pass
            pages = worker.context.pages

        main_page = pages[0]
        if main_page.is_closed():
            worker.logger.warning("⚠ Main page already closed – skipping logout")
            return False

        worker.logger.info("="*60)
        worker.logger.info("LOGOUT SEQUENCE STARTING")
        worker.logger.info("="*60)

        # Dismiss any open dialogs/modals by pressing Escape
        worker.logger.info("Pressing Escape to dismiss any modals...")
        try:
            main_page.keyboard.press('Escape')
            main_page.wait_for_timeout(500)
            main_page.keyboard.press('Escape')
            main_page.wait_for_timeout(500)
        except Exception:
            pass

        # Screenshot before logout
        try:
            main_page.screenshot(path=f"{worker.log_dir}/logout_01_before.png")
            worker.logger.info("📸 Screenshot: logout_01_before.png")
        except Exception:
            pass

        logged_out = False

        # ── XPath/CSS multi-strategy clicks ──────────────────────────
        try:
            # IMPORTANT: User menu button is inside remote_iframe_0 iframe!
            worker.logger.info("STEP 1: Locating identity_gadget iframe...")
            
            identity_frame = main_page.frame(name='remote_iframe_0')
            if not identity_frame:
                worker.logger.error("  ✗ Could not find remote_iframe_0")
                try:
                    main_page.screenshot(path=f"{worker.log_dir}/logout_iframe_not_found.png")
                    worker.logger.info("📸 Screenshot: logout_iframe_not_found.png")
                except Exception:
                    pass
                return False
            
            worker.logger.info("  ✓ Found iframe: remote_iframe_0")

            # Try specific selectors for the user menu button INSIDE the iframe
            # Start with most specific, fall back to generic
            user_menu_selectors = [
                'div[id*="user"]',                         # Div with 'user' in ID
                'button[id*="user"]',                      # Button with 'user' in ID
                'a[id*="user"]',                           # Link with 'user' in ID
                'div.user-info',                           # Class-based
                'button:visible',                          # Any visible button (fallback)
                'a:visible',                               # Any visible link (fallback)
                'div:visible',                             # Any visible div (last resort)
            ]
            
            worker.logger.info("STEP 2: Clicking user menu button (inside iframe)...")
            menu_clicked = False
            
            for selector in user_menu_selectors:
                try:
                    worker.logger.info(f"  Trying: {selector}")
                    user_menu = identity_frame.locator(selector)
                    menu_count = user_menu.count()
                    
                    if menu_count > 0:
                        worker.logger.info(f"    Found {menu_count} element(s)")
                        user_menu.first.wait_for(state='visible', timeout=5000)
                        user_menu.first.click(force=True)
                        worker.logger.info(f"  ✓ Clicked user menu")
                        menu_clicked = True
                        break
                except Exception as e:
                    worker.logger.debug(f"    Failed: {e}")
                    continue
            
            if not menu_clicked:
                worker.logger.error("  ✗ All user menu selectors failed (tried inside iframe)")
                try:
                    main_page.screenshot(path=f"{worker.log_dir}/logout_menu_not_found.png")
                    worker.logger.info("📸 Screenshot: logout_menu_not_found.png")
                except Exception:
                    pass
                return False
            
            # Wait for dropdown menu to appear (more reliable than fixed timeout)
            worker.logger.info("STEP 3: Waiting for dropdown menu...")
            try:
                main_page.locator('ul#id-gt-ul').wait_for(state='visible', timeout=3000)
                worker.logger.info("  ✓ Dropdown menu visible")
            except Exception:
                worker.logger.warning("  ⚠ Dropdown didn't appear, trying anyway...")
                main_page.wait_for_timeout(1500)
            
            # Screenshot after menu click
            try:
                main_page.screenshot(path=f"{worker.log_dir}/logout_02_menu_opened.png")
                worker.logger.info("📸 Screenshot: logout_02_menu_opened.png")
            except Exception:
                pass

            # STEP 4: Click sign-out link (in MAIN page, not iframe)
            # The dropdown menu appears in the main page after clicking the iframe button
            signout_selectors = [
                '#so_anchor',                          # Most reliable - direct ID of <a>
                '#signout-btn1 a',                     # ID of <li> + descendant <a>
                'a:has-text("Sign Out")',             # Text match
                'ul#id-gt-ul a:has-text("Sign Out")', # Full path with text
                'xpath=//a[@id="so_anchor"]',         # XPath for anchor
                'xpath=//li[@id="signout-btn1"]/a',   # XPath with ID
            ]
            
            worker.logger.info("STEP 4: Clicking sign-out link (in main page)...")
            
            for selector in signout_selectors:
                try:
                    worker.logger.info(f"  Trying: {selector}")
                    signout_link = main_page.locator(selector)
                    signout_count = signout_link.count()
                    
                    if signout_count > 0:
                        worker.logger.info(f"    Found {signout_count} element(s)")
                        signout_link.first.wait_for(state='visible', timeout=5000)
                        signout_link.first.click(force=True)
                        worker.logger.info(f"  ✓ Clicked sign-out")
                        
                        # Wait for navigation to Logout.jsp
                        try:
                            main_page.wait_for_url('**/Logout.jsp**', timeout=5000)
                            worker.logger.info("  ✓ Navigated to Logout.jsp")
                        except Exception:
                            main_page.wait_for_timeout(3000)  # Fallback to fixed wait
                        
                        logged_out = True
                        break
                except Exception as e:
                    worker.logger.debug(f"    Failed: {e}")
                    continue
            
            if not logged_out:
                worker.logger.error("  ✗ All sign-out selectors failed")
                # Try to take a screenshot to see what's on screen
                try:
                    main_page.screenshot(path=f"{worker.log_dir}/logout_signout_not_found.png")
                    worker.logger.info("📸 Screenshot: logout_signout_not_found.png")
                except Exception:
                    pass
                
        except Exception as e:
            worker.logger.error(f"✗ Logout click sequence failed: {e}")

        # Screenshot final state
        try:
            main_page.screenshot(path=f"{worker.log_dir}/logout_03_complete.png")
            worker.logger.info("📸 Screenshot: logout_03_complete.png")
        except Exception:
            pass

        # ── Verification ─────────────────────────────────────────────
        main_page.wait_for_timeout(2000)
        try:
            final_url = main_page.url
            is_logout_page = 'logout' in final_url.lower()
            
            if logged_out and is_logout_page:
                worker.logger.info("="*60)
                worker.logger.info(f"✓✓✓ LOGOUT SUCCESSFUL ✓✓✓")
                worker.logger.info(f"Final URL: {final_url}")
                worker.logger.info("="*60)
            elif logged_out:
                worker.logger.warning("="*60)
                worker.logger.warning(f"⚠ Logout clicks completed but NOT on logout page")
                worker.logger.warning(f"Final URL: {final_url}")
                worker.logger.warning("="*60)
            else:
                worker.logger.error("="*60)
                worker.logger.error("✗✗✗ LOGOUT FAILED — MANUAL LOGOUT REQUIRED ✗✗✗")
                worker.logger.error(f"Final URL: {final_url}")
                worker.logger.error("To prevent session limit, manually visit:")
                worker.logger.error("https://148.151.32.77:8444/cuicui/Logout.jsp")
                worker.logger.error("="*60)
        except Exception:
            pass
        
        return logged_out

    except Exception as e:
        worker.logger.error("="*60)
        worker.logger.error(f"✗✗✗ LOGOUT EXCEPTION: {e}")
        worker.logger.error("MANUAL LOGOUT REQUIRED to prevent session limit!")
        worker.logger.error("="*60)
        try:
            if worker.context and worker.context.pages:
                worker.context.pages[0].screenshot(path=f"{worker.log_dir}/logout_error.png")
        except Exception:
            pass
        return False
