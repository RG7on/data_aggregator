"""
Example Worker - Template for creating new workers
==================================================
This is a template/example worker that demonstrates how to create
a new data source scraper.

To create a new worker:
1. Copy this file and rename it (e.g., smax_worker.py)
2. Update SOURCE_NAME and DESCRIPTION
3. Implement the scrape() method with your site-specific logic
4. Add any required credentials/config
"""

import os
import sys

# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from base_worker import BaseWorker
from typing import Dict, Any


class Worker(BaseWorker):
    """
    Example worker that demonstrates the structure.
    Replace this with actual scraping logic for your target site.
    """
    
    # REQUIRED: Unique identifier for this data source
    SOURCE_NAME = "example"
    
    # REQUIRED: Human-readable description
    DESCRIPTION = "Example worker template - replace with actual implementation"
    
    # Configuration (move to environment variables or config file in production)
    LOGIN_URL = "https://example.com/login"
    DASHBOARD_URL = "https://example.com/dashboard"
    USERNAME = os.getenv('EXAMPLE_USERNAME', '')
    PASSWORD = os.getenv('EXAMPLE_PASSWORD', '')
    
    def scrape(self) -> Dict[str, Any]:
        """
        Main scraping logic - MUST return a dictionary of KPIs.
        
        Returns:
            Dict with KPI names as keys and values.
            Keys should be prefixed with source name for clarity.
            
        Example return:
            {
                'example_total_tickets': 102,
                'example_open_requests': 45,
                'example_pending_items': 12
            }
        """
        self.logger.info(f"Starting scrape for {self.SOURCE_NAME}")
        
        # ============================================================
        # EXAMPLE: This is a demo that returns fake data
        # Replace this entire section with your actual scraping logic
        # ============================================================
        
        # Example: Navigate to login page
        # self.page.goto(self.LOGIN_URL)
        
        # Example: Use the login helper from BaseWorker
        # login_success = self.login_with_form(
        #     url=self.LOGIN_URL,
        #     username=self.USERNAME,
        #     password=self.PASSWORD,
        #     username_selector='#username',
        #     password_selector='#password', 
        #     submit_selector='#login-button',
        #     success_indicator='.dashboard-header'
        # )
        #
        # if not login_success:
        #     self.logger.error("Login failed")
        #     return {}
        
        # Example: Navigate to dashboard and extract data
        # self.page.goto(self.DASHBOARD_URL)
        # self.wait_for_data_load('.kpi-widget')
        
        # Example: Extract KPIs using safe_get_number
        # total_tickets = self.safe_get_number('.ticket-count', default=0)
        # open_requests = self.safe_get_number('.request-count', default=0)
        
        # For demo purposes, return sample data
        # In production, replace with actual scraped values
        self.logger.info("Demo mode - returning sample data")
        
        return {
            'example_total_items': 42,
            'example_pending_count': 7,
            'example_completed_today': 15
        }


# ============================================================
# Alternative: Simple function-based approach (less preferred)
# ============================================================
# 
# SOURCE_NAME = "example_simple"
# 
# def scrape() -> Dict[str, Any]:
#     """Simple function-based worker (no BaseWorker inheritance)."""
#     # Your scraping logic here
#     return {'example_simple_value': 100}


# For testing the worker directly
if __name__ == '__main__':
    print("Testing Example Worker...")
    worker = Worker()
    result = worker.run()
    print(f"Result: {result}")
