"""
Driver - The Orchestrator
=========================
Main entry point for the Modular Snapshot Scraper.

This script:
1. Scans the /workers folder for Python modules
2. Imports each worker and executes its scrape() function
3. Handles worker failures individually (one crash doesn't stop others)
4. Aggregates results into the central CSV

Designed to be run every 5 minutes via Windows Task Scheduler.
"""

import os
import sys
import importlib.util
import logging
from datetime import datetime
from typing import Dict, Any, List, Tuple
import traceback

# Ensure project root is on path
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from core.common_utils import process_worker_result, process_worker_result_long
from core.config import get_global_settings, get_worker_settings, get_log_dir, PROJECT_ROOT as CFG_ROOT
from core.database import init_db, export_csv, cleanup_old_data, migrate_csv_to_db

# Configure logging
LOG_DIR = get_log_dir()
os.makedirs(LOG_DIR, exist_ok=True)

log_filename = os.path.join(LOG_DIR, f"driver_{datetime.now().strftime('%Y%m%d')}.log")

# Configure root logger explicitly (force=True ensures it works even if
# basicConfig was already called by an imported module like base_worker)
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler(log_filename),
        logging.StreamHandler(sys.stdout)
    ],
    force=True
)
logger = logging.getLogger('driver')

# Configuration
WORKERS_DIR = os.path.join(CFG_ROOT, 'workers')


def discover_workers() -> List[str]:
    """
    Scan the /workers folder for Python modules and packages.
    
    Returns:
        List of worker module file paths or package directory paths
    """
    workers = []
    
    if not os.path.exists(WORKERS_DIR):
        logger.warning(f"Workers directory not found: {WORKERS_DIR}")
        os.makedirs(WORKERS_DIR, exist_ok=True)
        logger.info(f"Created workers directory: {WORKERS_DIR}")
        return workers
    
    for filename in os.listdir(WORKERS_DIR):
        # Check for .py files (not starting with _)
        if filename.endswith('.py') and not filename.startswith('_'):
            worker_path = os.path.join(WORKERS_DIR, filename)
            workers.append(worker_path)
            logger.info(f"Discovered worker module: {filename}")
        # Check for packages (directories with __init__.py)
        elif os.path.isdir(os.path.join(WORKERS_DIR, filename)) and not filename.startswith('_'):
            package_path = os.path.join(WORKERS_DIR, filename)
            init_file = os.path.join(package_path, '__init__.py')
            if os.path.exists(init_file):
                workers.append(package_path)
                logger.info(f"Discovered worker package: {filename}")
    
    return workers


def load_worker_module(worker_path: str):
    """
    Dynamically import a worker module or package.
    
    Args:
        worker_path: Full path to the worker .py file or package directory
        
    Returns:
        Loaded module object, or None if failed
    """
    try:
        module_name = os.path.splitext(os.path.basename(worker_path))[0]
        
        # Check if it's a package (directory) or a module (.py file)
        if os.path.isdir(worker_path):
            # It's a package - import from workers.package_name
            package_name = os.path.basename(worker_path)
            module = importlib.import_module(f'workers.{package_name}')
        else:
            # It's a .py file - use spec_from_file_location
            spec = importlib.util.spec_from_file_location(module_name, worker_path)
            module = importlib.util.module_from_spec(spec)
            sys.modules[module_name] = module
            spec.loader.exec_module(module)
        
        return module
    except Exception as e:
        logger.error(f"Failed to load worker {worker_path}: {e}")
        logger.error(traceback.format_exc())
        return None


def execute_worker(module) -> Tuple[str, Dict[str, Any], bool]:
    """
    Execute a worker's scrape function.
    
    Args:
        module: The loaded worker module
        
    Returns:
        Tuple of (source_name, data_dict, success_bool)
    """
    try:
        # Check if module has a Worker class (preferred) or scrape function
        if hasattr(module, 'Worker'):
            worker_instance = module.Worker()
            source_name = worker_instance.SOURCE_NAME
            data = worker_instance.run()
        elif hasattr(module, 'scrape'):
            # Fallback to simple scrape() function
            source_name = getattr(module, 'SOURCE_NAME', module.__name__)
            data = module.scrape()
        else:
            logger.error(f"Worker {module.__name__} has no Worker class or scrape() function")
            return (module.__name__, {}, False)
        
        if data:
            logger.info(f"Worker {source_name} returned: {data}")
            return (source_name, data, True)
        else:
            logger.warning(f"Worker {source_name} returned no data")
            return (source_name, {}, False)
            
    except Exception as e:
        logger.error(f"Worker execution failed: {e}")
        logger.error(traceback.format_exc())
        return (getattr(module, '__name__', 'unknown'), {}, False)


def run_all_workers() -> Dict[str, Any]:
    """
    Main orchestration function.
    Discovers, loads, and executes all workers.
    
    Returns:
        Summary dict with results
    """
    start_time = datetime.now()
    logger.info("=" * 60)
    logger.info(f"DRIVER STARTED - {start_time.strftime('%Y-%m-%d %H:%M:%S')}")
    logger.info("=" * 60)
    
    # Initialise SQLite database (creates table if first run)
    init_db()
    
    # One-time migration: import existing CSV rows into SQLite
    try:
        migrate_csv_to_db()
    except Exception as e:
        logger.debug(f"CSV migration check: {e}")
    
    summary = {
        'start_time': start_time.isoformat(),
        'workers_found': 0,
        'workers_succeeded': 0,
        'workers_failed': 0,
        'results': {}
    }
    
    # Discover workers
    worker_paths = discover_workers()
    summary['workers_found'] = len(worker_paths)
    
    if not worker_paths:
        logger.warning("No workers found in /workers directory")
        logger.info("Add worker modules to the /workers folder to start scraping")
        return summary
    
    # Execute each worker independently
    for worker_path in worker_paths:
        worker_name = os.path.basename(worker_path)
        module_stem = os.path.splitext(worker_name)[0]  # e.g. "cuic_worker" → "cuic_worker"
        logger.info(f"\n--- Processing: {worker_name} ---")
        
        try:
            # Load module
            module = load_worker_module(worker_path)
            if module is None:
                summary['workers_failed'] += 1
                summary['results'][worker_name] = {'status': 'load_failed'}
                continue
            
            # Check if worker is enabled in settings
            source_name = getattr(module, 'Worker', None)
            if source_name and hasattr(source_name, 'SOURCE_NAME'):
                ws = get_worker_settings(source_name.SOURCE_NAME)
                if ws and ws.get('enabled') is False:
                    logger.info(f"  Worker '{source_name.SOURCE_NAME}' is disabled in settings. Skipping.")
                    summary['results'][worker_name] = {'status': 'disabled'}
                    continue
            
            # Execute worker
            source_name, data, success = execute_worker(module)
            
            if success and data:
                # Process and save results
                # Detect format: list = long format, dict = wide format
                if isinstance(data, list):
                    # Long format: List of {metric_title, category, value}
                    save_success = process_worker_result_long(source_name, data)
                else:
                    # Wide format: Dict of {column_name: value}
                    save_success = process_worker_result(source_name, data)
                
                if save_success:
                    summary['workers_succeeded'] += 1
                    summary['results'][worker_name] = {
                        'status': 'success',
                        'source': source_name,
                        'data': data
                    }
                else:
                    summary['workers_failed'] += 1
                    summary['results'][worker_name] = {'status': 'save_failed'}
            else:
                summary['workers_failed'] += 1
                summary['results'][worker_name] = {'status': 'no_data'}
                
        except Exception as e:
            # Catch-all to ensure one worker can't crash the entire process
            logger.error(f"Unexpected error with {worker_name}: {e}")
            logger.error(traceback.format_exc())
            summary['workers_failed'] += 1
            summary['results'][worker_name] = {
                'status': 'error',
                'error': str(e)
            }
    
    # ── Post-run: export CSV + retention cleanup ──────────────────────
    if summary['workers_succeeded'] > 0:
        try:
            export_csv()  # writes local CSV + shared drive if configured
            logger.info("CSV export complete")
        except Exception as e:
            logger.error(f"CSV export failed: {e}")

        try:
            cleanup_old_data()
            logger.info("Retention cleanup complete")
        except Exception as e:
            logger.error(f"Retention cleanup failed: {e}")

    # Log summary
    end_time = datetime.now()
    duration = (end_time - start_time).total_seconds()
    summary['end_time'] = end_time.isoformat()
    summary['duration_seconds'] = duration
    
    logger.info("\n" + "=" * 60)
    logger.info("DRIVER COMPLETED")
    logger.info(f"  Duration: {duration:.2f} seconds")
    logger.info(f"  Workers Found: {summary['workers_found']}")
    logger.info(f"  Succeeded: {summary['workers_succeeded']}")
    logger.info(f"  Failed: {summary['workers_failed']}")
    logger.info("=" * 60)
    
    return summary


def main():
    """Entry point for the driver."""
    try:
        summary = run_all_workers()
        
        # Exit with error code if any workers failed
        if summary['workers_failed'] > 0:
            sys.exit(1)
        sys.exit(0)
        
    except Exception as e:
        logger.critical(f"Driver crashed: {e}")
        logger.critical(traceback.format_exc())
        sys.exit(2)


if __name__ == '__main__':
    main()
