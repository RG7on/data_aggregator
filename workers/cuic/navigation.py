"""
CUIC Navigation
===============
Navigation helpers for CUIC reports, including:
- Frame access 
- Folder navigation
- Report selection in ng-grid
"""

import re
from . import selectors


def close_report_page(worker):
    """Close any extra browser tabs opened by a report."""
    try:
        pages = worker.context.pages
        while len(pages) > 1:
            pages[-1].close()
            pages = worker.context.pages
        # Ensure focus is on the main page
        worker.page.bring_to_front()
    except Exception:
        pass


def navigate_to_reports_root(worker):
    """Reset back to the reports list. If the ngGrid is still hidden
    after clicking the Reports tab, reload the page to restore UI state."""
    try:
        # Attempt 1: click the Reports tab
        worker.page.click(selectors.REPORTS_TAB_CSS)
        worker.page.wait_for_timeout(worker.timeout_medium)

        # Check if the ngGrid is visible in the reports iframe
        frame = worker.page.frame(name=selectors.REPORTS_IFRAME_NAME)
        if frame:
            try:
                grid = frame.query_selector(selectors.GRID_CONTAINER)
                if grid and grid.is_visible():
                    worker.logger.info("Reports grid visible after tab click")
                    return
            except Exception:
                pass

        # Attempt 2: full page reload to reset CUIC UI state
        # (session cookie persists — no re-login needed)
        worker.logger.info("ngGrid hidden after tab click — reloading page")
        worker.page.goto(worker.url, wait_until='domcontentloaded',
                       timeout=worker.timeout_nav)
        worker.page.wait_for_timeout(worker.timeout_medium)
        worker.page.wait_for_selector(selectors.REPORTS_TAB_CSS,
                                    timeout=worker.timeout_nav)
    except Exception as e:
        worker.logger.warning(f"Navigate to reports root: {e}")


def get_reports_frame(worker):
    """Get the reports iframe containing the ng-grid."""
    try:
        worker.page.click(selectors.REPORTS_TAB_CSS)
        worker.page.wait_for_timeout(worker.timeout_medium)

        frame = worker.page.frame(name=selectors.REPORTS_IFRAME_NAME)
        if not frame:
            # fallback: find frame with ng-grid
            for f in worker.page.frames:
                try:
                    if f.query_selector(selectors.GRID_CONTAINER):
                        frame = f
                        break
                except Exception:
                    pass
        if not frame:
            worker.logger.error("Reports iframe not found")
            worker.screenshot("iframe_missing", is_step=False)
            return None

        frame.wait_for_selector(selectors.GRID_CONTAINER, timeout=worker.timeout_nav)
        worker.logger.info("Reports iframe ready")
        return frame
    except Exception as e:
        worker.logger.error(f"Reports iframe error: {e}")
        worker.screenshot("iframe_error", is_step=False)
        return None


def open_report(worker, frame, folder_path: str, report_name: str) -> bool:
    """Navigate through a folder path (e.g. 'Stock/CCE/CCE_AF_Historical')
    then click the report. Supports any nesting depth."""
    try:
        # Split folder path into segments — supports / or \ delimiters
        folders = [f.strip() for f in folder_path.replace('\\', '/').split('/') if f.strip()]

        # Defensive: remove report name from folder segments if it slipped in
        if folders and report_name and folders[-1] == report_name:
            worker.logger.warning(f"Report name '{report_name}' found in folder path — removing duplicate")
            folders = folders[:-1]

        for depth, folder in enumerate(folders):
            if not _click_grid_item(worker, frame, folder, is_folder=True):
                # Try scrolling to find it
                if not _scroll_and_click_folder(worker, frame, folder):
                    worker.logger.error(f"Folder '{folder}' not found (depth {depth})")
                    _dump_grid(worker, frame)
                    worker.screenshot("folder_not_found", is_step=False)
                    return False
            worker.logger.info(f"Opened folder '{folder}' (depth {depth})")

            worker.page.wait_for_timeout(worker.timeout_medium)

            # Re-acquire frame if it detached
            frame = _reacquire_frame(worker, frame)
            if not frame:
                return False

            # Wait for grid to refresh with new folder contents
            try:
                frame.wait_for_selector(selectors.GRID_CONTAINER, timeout=worker.timeout_nav)
            except Exception:
                worker.page.wait_for_timeout(worker.timeout_short)

        # Click the report itself
        if not _click_grid_item(worker, frame, report_name, is_folder=False):
            if not _scroll_and_click(worker, frame, report_name):
                worker.logger.error(f"Report '{report_name}' not found")
                _dump_grid(worker, frame)
                worker.screenshot("report_not_found", is_step=False)
                return False
        worker.logger.info(f"Clicked report '{report_name}'")
        worker.page.wait_for_timeout(worker.timeout_medium)
        worker.screenshot("02_report_clicked")
        return True
    except Exception as e:
        worker.logger.error(f"Open report failed: {e}")
        worker.screenshot("open_report_error", is_step=False)
        return False


def _reacquire_frame(worker, frame):
    """Re-acquire the reports iframe if it detached after a click.""" 
    try:
        frame.query_selector('body')
        return frame
    except Exception:
        frame = worker.page.frame(name=selectors.REPORTS_IFRAME_NAME)
        if not frame:
            worker.logger.error("Frame detached and could not be re-acquired")
        return frame


def _scroll_and_click_folder(worker, frame, name: str, max_scrolls: int = 20) -> bool:
    """Scroll through the ng-grid viewport to find and click a folder."""
    try:
        vp = frame.query_selector(selectors.GRID_VIEWPORT)
        if not vp:
            return False
        for _ in range(max_scrolls):
            frame.evaluate('''s => {
                const vp = document.querySelector(s);
                if (vp) vp.scrollTop += vp.clientHeight;
            }''', selectors.GRID_VIEWPORT)
            worker.page.wait_for_timeout(400)
            if _click_grid_item(worker, frame, name, is_folder=True):
                return True
        return False
    except Exception:
        return False


# ──────────────────────────────────────────────────────────────────────
#  Grid helpers
# ──────────────────────────────────────────────────────────────────────
def _norm(text: str) -> str:
    """Normalize whitespace in text."""
    return re.sub(r'\s+', ' ', text.strip())


def _click_grid_item(worker, frame, name: str, is_folder: bool = False) -> bool:
    """Single-click an item in the ng-grid. Returns True if clicked."""
    target = _norm(name)

    # Fast path: title attribute (most reliable, one query)
    try:
        el = frame.query_selector(f'.nameCell span[title="{name}"]')
        if el:
            container = el.evaluate_handle(
                'el => el.closest(".name_cell_container") || el'
            ).as_element()
            container.click()
            return True
    except Exception:
        pass

    # DOM scan (handles whitespace / class variations)
    try:
        for row in frame.query_selector_all(selectors.GRID_ROW):
            name_el = row.query_selector(selectors.NAME_TEXT)
            if not name_el:
                continue
            txt = _norm(name_el.inner_text())
            title = _norm(name_el.get_attribute('title') or '')
            if txt != target and title != target:
                continue
            # Verify icon type
            icon_sel = selectors.FOLDER_ICON if is_folder else selectors.REPORT_ICON
            if not row.query_selector(icon_sel):
                continue
            (row.query_selector(selectors.NAME_CELL) or name_el).click()
            return True
    except Exception:
        pass

    # JS fallback
    try:
        result = frame.evaluate('''(t) => {
            const norm = s => s.replace(/\\s+/g,' ').trim();
            const target = norm(t);
            for (const sp of document.querySelectorAll('.nameCell span')) {
                if (norm(sp.textContent||'')===target || norm(sp.title||'')===target) {
                    const p = sp.closest('.name_cell_container') || sp.closest('.ngCellText');
                    if (p) { p.click(); return true; }
                }
            }
            return false;
        }''', name)
        if result:
            return True
    except Exception:
        pass

    return False


def _scroll_and_click(worker, frame, name: str, max_scrolls: int = 20) -> bool:
    """Scroll through the ng-grid viewport to find and click an item."""
    try:
        vp = frame.query_selector(selectors.GRID_VIEWPORT)
        if not vp:
            return False
        for _ in range(max_scrolls):
            frame.evaluate('''s => {
                const vp = document.querySelector(s);
                if (vp) vp.scrollTop += vp.clientHeight;
            }''', selectors.GRID_VIEWPORT)
            worker.page.wait_for_timeout(400)
            if _click_grid_item(worker, frame, name, is_folder=False):
                return True
        return False
    except Exception:
        return False


def _dump_grid(worker, frame):
    """Debug helper: print grid contents to log."""
    try:
        for i, row in enumerate(frame.query_selector_all(selectors.GRID_ROW)[:30]):
            el = row.query_selector(selectors.NAME_TEXT)
            txt = el.inner_text().strip() if el else '?'
            worker.logger.info(f"  Grid[{i}]: {txt}")
    except Exception:
        pass
